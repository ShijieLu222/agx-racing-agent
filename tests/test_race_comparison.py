import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_race_comparison import analyze


class PublicRaceIntegrityTests(unittest.TestCase):
    def fixture(self, root, ticks=(2, 5, 8)):
        def store(name, rows):
            raw = b''.join((json.dumps(r) + '\n').encode() for r in rows)
            (root / name).write_bytes(raw)
            return {'sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw), 'rows': len(rows)}
        meta = {'phases': [{'phase': 'race', 'start_tick': 1}],
                'track': {'id': 'test', 'length_m': 1000},
                'cars': [{'seat': 0, 'design_summary': {}}]}
        static = store('public_static.jsonl', [{'metadata': meta}])
        events = store('public_events.jsonl', [])
        frames = []
        for tick in ticks:
            frames.append({'tick': tick, 'time': tick / 60, 'phase': 'race', 'cars': [{
                'seat': 0, 'status': 'finished' if tick == 8 else 'racing',
                'lap': 0, 's': tick * 10, 'throttle': 1, 'brake': 0,
                'ers_soc_mj': 2, 'ers_mode': 1, 'aero_mode': 0,
                'aid_available': False, 'aid_active': False, 'fuel_kg': 10,
                'speed_mps': 20} ]})
        raw = store('frames-0.bin', frames)
        descriptor = {'job_id': 'test', 'physics_hz': 60, 'steps': 8,
                      'streams': {'public_static': static, 'public_events': events},
                      'static': {'streams': {'public_frames': [raw['sha256']]}},
                      'result': {'classification': [{'seat': 0, 'position': 1}]}}
        (root / 'descriptor.json').write_text(json.dumps(descriptor))

    def test_phase_start_between_sampling_ticks_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            report = analyze(root, 0)
            self.assertEqual(report['race_frames'], 3)
            self.assertEqual(report['first_sample_tick'], 2)

    def test_corrupt_frame_chunk_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            with (root / 'frames-0.bin').open('ab') as output:
                output.write(b' ')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                analyze(root, 0)

    def test_valid_hash_with_missing_middle_sample_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, (2, 8))
            with self.assertRaisesRegex(ValueError, 'Missing/duplicate'):
                analyze(root, 0)

    def test_missing_terminal_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, (2, 5))
            with self.assertRaisesRegex(ValueError, 'exact end'):
                analyze(root, 0)
