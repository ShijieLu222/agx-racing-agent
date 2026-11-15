import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import track_data
from pack import FILES, pack
from validate_design import strict_json, validate


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.book = json.loads((ROOT / 'design.json').read_text())

    def test_actual_design_passes_all_published_track_constraints(self):
        self.assertTrue(validate(self.book))

    def test_bool_nan_missing_extra_and_off_grid_rejected(self):
        for value in (True, float('nan'), 20.1, 100):
            with self.subTest(value=value):
                book = copy.deepcopy(self.book)
                book['design']['mass']['ballast_kg'] = value
                with self.assertRaises(ValueError):
                    validate(book)
        for change in ('missing', 'extra'):
            book = copy.deepcopy(self.book)
            if change == 'missing':
                del book['design']['aero']['front_wing']
            else:
                book['design']['aero']['magic'] = 1
            with self.assertRaises(ValueError):
                validate(book)

    def test_low_ballast_cannot_support_extreme_weight_distribution(self):
        self.book['design']['mass'].update(ballast_kg=20, weight_front_pct=46)
        with self.assertRaises(ValueError):
            validate(self.book)

    def test_generic_valid_pressure_must_still_pass_all_tracks(self):
        self.book['design']['tyres']['pressure_front_psi'] = 26
        with self.assertRaisesRegex(ValueError, 'highland|crossover'):
            validate(self.book)

    def test_gears_must_pass_both_individual_and_ratio_constraints(self):
        self.book['design']['gearbox']['ratios'][0] = 4.8
        with self.assertRaises(ValueError):
            validate(self.book)

    def test_rain_alternate_is_independently_checked(self):
        self.book['rain_design'] = copy.deepcopy(self.book['design'])
        self.book['rain_design']['suspension']['camber_rear_deg'] = -2
        with self.assertRaises(ValueError):
            validate(self.book)

    def test_json_duplicate_keys_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'design.json'
            for text in ('{"design":{},"design":{}}', '{"design":NaN}'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    strict_json(path)


class TrackTests(unittest.TestCase):
    def test_three_tracks_have_monotone_sample_stations_and_finite_geometry(self):
        self.assertEqual(set(track_data.TRACKS), {'parkland', 'highland', 'crossover'})
        for data in track_data.TRACKS.values():
            rows = data['rows']
            self.assertEqual(rows[0][0], 0)
            self.assertLess(rows[-1][0], data['length'])
            self.assertTrue(all(a[0] < b[0] for a, b in zip(rows, rows[1:])))
            self.assertTrue(all(all(math.isfinite(x) for x in row) for row in rows))
            self.assertTrue(all(row[3] > 0 and row[4] > 0 for row in rows))

    def test_geometry_uses_current_station_and_wraps_lap_seam(self):
        for data in track_data.TRACKS.values():
            length = data['length']
            row = data['rows'][100]
            for actual, expected in zip(track_data.geometry_at(length, row[0]), row[1:]):
                self.assertAlmostEqual(actual, expected)
            self.assertEqual(track_data.geometry_at(length, 0),
                             track_data.geometry_at(length, length))
            for a, b in zip(track_data.geometry_at(length, -1),
                            track_data.geometry_at(length, length - 1)):
                self.assertAlmostEqual(a, b)

    def test_unknown_circuit_does_not_silently_use_wrong_map(self):
        for length in (0, 4000, float('nan'), None, True):
            self.assertIsNone(track_data.geometry_at(length, 0))
            self.assertIsNone(track_data.pit_distance(length, 0))
            self.assertIsNone(track_data.aero_remaining(length, 0))

    def test_pit_distance_wraps_and_is_zero_at_entry(self):
        for data in track_data.TRACKS.values():
            length, entry = data['length'], data['pit_entry']
            self.assertAlmostEqual(track_data.pit_distance(length, entry), 0)
            self.assertAlmostEqual(track_data.pit_distance(length, entry - 10), 10)
            self.assertAlmostEqual(track_data.pit_distance(length, entry + 1), length - 1)

    def test_x_mode_zones_include_start_finish_seam(self):
        for data in track_data.TRACKS.values():
            length = data['length']
            for start, end in data['aero_zones']:
                span = (end - start) % length
                midpoint = (start + span / 2) % length
                self.assertAlmostEqual(track_data.aero_remaining(length, midpoint), span / 2)
                self.assertEqual(track_data.aero_remaining(length, end), 0)


class PackTests(unittest.TestCase):
    def test_pack_is_reproducible_and_includes_only_reviewed_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in FILES:
                (root / name).write_bytes((ROOT / name).read_bytes())
            (root / '.env').write_text('NEVER_PUBLISH=private')
            (root / 'training.jsonl').write_text('private log')
            first, hash1 = pack(root, root / 'one.zip')
            second, hash2 = pack(root, root / 'two.zip')
            self.assertEqual(hash1, hash2)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(set(archive.namelist()), set(FILES))
                self.assertIsNone(archive.testzip())

    def test_packer_refuses_invalid_python_before_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in FILES:
                (root / name).write_bytes((ROOT / name).read_bytes())
            (root / 'agent.py').write_text('def invalid(:')
            with self.assertRaises(SyntaxError):
                pack(root)


if __name__ == '__main__':
    unittest.main()
