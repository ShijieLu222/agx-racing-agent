"""Performance-control invariants; no claim about the private race engine."""
import copy
import unittest
from unittest.mock import patch

import agent
from track_data import TRACKS, geometry_at
from test_agent import advance, observation


class PerformanceControlTests(unittest.TestCase):
    def test_public_window_keeps_original_peaks_between_moving_probe_stations(self):
        track = TRACKS['parkland']
        rows = track['rows']
        peak = max(rows, key=lambda r: abs(r[1]))
        station = peak[0] - 101.3
        window = agent.Driver().public_window(track['length'], station, 150)
        matching = [r for r in window if abs(r[0] - 101.3) < 1e-6]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0][1], peak[1])
        self.assertGreater(len(rows), track['length'] / 2.1)

    def test_public_window_preserves_both_sides_of_rounded_lap_seam(self):
        for track in TRACKS.values():
            for delta in (-.1, 0, .1):
                length = track['length'] + delta
                station = length - 20.3
                window = agent.Driver().public_window(length, station, 60)
                self.assertEqual(window[0][0], 0)
                self.assertEqual(window[-1][0], 60)
                self.assertTrue(all(a[0] < b[0] for a, b in zip(window, window[1:])))
                for row in window:
                    for actual, expected in zip(row[1:5], geometry_at(length, station + row[0])):
                        self.assertAlmostEqual(actual, expected, places=5)

    def test_clear_straight_accelerates_above_old_dry_and_wet_speed_ceilings(self):
        for wet in (0.0, 1.0):
            for speed in (58.0, 85.0, 100.0):
                with self.subTest(wet=wet, speed=speed):
                    action = agent.Driver().act(observation(speed=speed, wet=wet))
                    self.assertEqual(action['brake'], 0.0)
                    self.assertEqual(action['throttle'], 1.0)

    def test_uninitialized_force_telemetry_does_not_cap_launch_throttle(self):
        row = observation(speed=0.0)
        row['self']['drive_force_n'] = [0.0] * 4
        action = agent.Driver().act(row)
        self.assertEqual(action['throttle'], 1.0)

    def test_engine_force_drop_does_not_create_false_straight_line_braking(self):
        row = observation(speed=50.0)
        driver = agent.Driver()
        self.assertEqual(driver.act(row)['brake'], 0.0)
        row = advance(row)
        row['self']['drive_force_n'] = [500.0] * 4
        action = driver.act(row)
        self.assertEqual(action['brake'], 0.0)
        self.assertEqual(action['throttle'], 1.0)

    def test_low_absolute_fuel_and_old_temperature_threshold_do_not_cap_power(self):
        row = observation(speed=60.0)
        row['self'].update(fuel_kg=3.0, pu_temp_c=126.0)
        driver = agent.Driver()
        # Measured fuel need is 0.199 kg, far below the actual 3 kg supply.
        driver.fuel_per_m = 0.00001
        action = driver.act(row)
        self.assertEqual(action['throttle'], 1.0)
        self.assertEqual(action['brake'], 0.0)

    def test_attack_does_not_hold_a_fixed_battery_reserve(self):
        row = observation(speed=45.0)
        row['self']['ers_soc_mj'] = 0.2
        self.assertEqual(agent.Driver().act(row)['ers_mode'], 3)

    def test_corner_exit_can_request_attack(self):
        row = observation(speed=20.0, curve=.004)
        self.assertEqual(agent.Driver().act(row)['ers_mode'], 3)

    def test_opening_route_releases_braking_without_a_target_ramp(self):
        row = observation(speed=35.0)
        driver = agent.Driver()
        with patch.object(driver, 'speed_plan', side_effect=[20.0, 80.0]):
            self.assertGreater(driver.act(row)['brake'], 0.0)
            action = driver.act(advance(row))
        self.assertEqual(action['brake'], 0.0)
        self.assertEqual(action['throttle'], 1.0)

    def test_falling_braking_envelope_is_followed_before_overspeed(self):
        row = observation(speed=55.0)
        driver = agent.Driver()
        with patch.object(driver, 'speed_plan', side_effect=[60.0, 59.0]):
            self.assertGreater(driver.act(row)['throttle'], 0.0)
            action = driver.act(advance(row))
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreater(action['brake'], 0.0)

    def test_phase_transition_clears_learned_downforce_and_target_rate(self):
        driver = agent.Driver()
        qualifying = observation('qualifying', speed=60.0, curve=.005)
        qualifying['self']['downforce_n'] = 10000.0
        driver.act(qualifying)
        race = observation('race', speed=0.0, curve=.005)
        race['self']['downforce_n'] = 0.0
        self.assertEqual(driver.act(copy.deepcopy(race)), agent.Driver().act(race))


if __name__ == '__main__':
    unittest.main()
