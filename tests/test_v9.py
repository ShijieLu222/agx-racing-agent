"""Fuel-estimation, bounded warm-grip and passing behavior regressions."""
import copy
import unittest

import agent
from test_agent import observation


class FuelTests(unittest.TestCase):
    def sample(self, driver, distance, fuel, stops=0):
        row = observation()
        row['self'].update(distance=distance, s=distance % 5000, fuel_kg=fuel, pit_stops=stops)
        row['self']['lap'] = int(distance // 5000)
        return driver.fuel_saving(row)

    def test_launch_cost_does_not_force_8kg_car_to_save(self):
        d = agent.Driver()
        for distance, fuel in [(0, 8), (150, 7.915), (300, 7.84)]:
            self.assertFalse(self.sample(d, distance, fuel))
        for distance in range(550, 2301, 250):
            self.assertFalse(self.sample(d, distance, 7.84 - (distance-300)*.0002))
        self.assertAlmostEqual(d.fuel_per_m, .0002)
        self.assertEqual(d.fuel_power_scale, 1)

    def test_mature_estimate_still_saves_when_supply_is_insufficient(self):
        d = agent.Driver()
        self.sample(d, 0, 2)
        self.sample(d, 300, 1.9)
        for distance in range(550, 1551, 250):
            saving = self.sample(d, distance, 1.9-(distance-300)*.0002)
        self.assertTrue(saving)
        self.assertLess(d.fuel_power_scale, .6)

    def test_almost_empty_tank_can_save_before_maturity(self):
        d = agent.Driver()
        self.sample(d, 0, .45)
        self.sample(d, 300, .40)
        self.assertTrue(self.sample(d, 550, .35))

    def test_one_short_high_cost_window_cannot_project_a_whole_race(self):
        d = agent.Driver()
        self.sample(d, 0, 8)
        self.sample(d, 300, 7.8)
        self.assertFalse(self.sample(d, 550, 7.5))
        self.assertEqual(d.fuel_power_scale, 1)

    def test_reset_distance_discards_stale_consumption(self):
        d = agent.Driver()
        self.sample(d, 0, 8)
        self.sample(d, 300, 7.8)
        self.sample(d, 550, 7.7)
        self.sample(d, 0, 8)
        self.assertEqual(d.fuel_windows, [])
        self.assertIsNone(d.fuel_per_m)

    def test_pit_exit_does_not_mix_pit_distance_into_consumption_window(self):
        d = agent.Driver()
        self.sample(d, 0, 8)
        self.sample(d, 300, 7.8)
        self.sample(d, 550, 7.75)
        old = list(d.fuel_windows)
        self.sample(d, 1300, 7.74, stops=1)
        self.assertEqual(d.fuel_windows, old)


class GripAndPassingTests(unittest.TestCase):
    def test_warm_bonus_fades_before_cold_or_wet_conditions(self):
        warm = observation()
        cool = copy.deepcopy(warm)
        cool['self']['tyre_temp_c'] = [65]*4
        self.assertAlmostEqual(agent.tyre_mu(warm), 1.75*1.28)
        self.assertAlmostEqual(agent.tyre_mu(cool), 1.75*.94)
        warm['weather']['track_wetness'] = .3
        self.assertAlmostEqual(agent.tyre_mu(warm), 1.75*.91)

    def slow_car(self, speed=25, curve=.01):
        row = observation(speed=speed, curve=curve)
        row['rivals'] = [dict(seat=1, gap_m=30, dn=0, speed_mps=15, status='racing')]
        return row

    def test_moving_slow_car_can_be_passed_in_clear_moderate_curve(self):
        row = self.slow_car(); d = agent.Driver()
        target, lane, emergency, straight = d.traffic_plan(row, agent.preview_rows(row), 40, 1/30)
        self.assertFalse(straight)
        self.assertEqual(d.pass_seat, 1)
        self.assertNotEqual(lane, 0)
        self.assertLess(target, 40)  # following stays binding during lane change
        self.assertFalse(emergency)

    def test_pass_does_not_start_at_high_speed_or_in_tight_hairpin(self):
        for row in [self.slow_car(speed=45), self.slow_car(curve=.08)]:
            d = agent.Driver(); d.traffic_plan(row, agent.preview_rows(row), 50, 1/30)
            self.assertIsNone(d.pass_seat)

    def test_narrow_or_occupied_lanes_prevent_moving_pass(self):
        for narrow in (True, False):
            row = self.slow_car()
            if narrow:
                for r in row['preview']['rows']: r[3:5] = [4, 4]
            else:
                row['rivals'] += [dict(seat=i, gap_m=10, dn=n, speed_mps=25, status='racing')
                                   for i, n in [(2, -3), (3, 3)]]
            d = agent.Driver();d.traffic_plan(row, agent.preview_rows(row), 40, 1/30)
            self.assertIsNone(d.pass_seat)

    def test_newly_occupied_lane_stops_lateral_command_progress(self):
        row = self.slow_car();d = agent.Driver()
        d.traffic_plan(row, agent.preview_rows(row), 40, 1/30)
        lane = d.lane
        row['rivals'].append(dict(seat=2, gap_m=-5, dn=d.pass_lane, speed_mps=30, status='racing'))
        d.traffic_plan(row, agent.preview_rows(row), 40, 1/30)
        self.assertEqual(d.lane, lane)

    def test_committed_pass_still_brakes_for_imminent_collision(self):
        row = self.slow_car();d = agent.Driver()
        d.act(row)
        row['rivals'][0]['gap_m'] = 3
        a = d.act(row)
        self.assertEqual(a['throttle'], 0)
        self.assertGreaterEqual(a['brake'], .75)


if __name__ == '__main__':
    unittest.main()
