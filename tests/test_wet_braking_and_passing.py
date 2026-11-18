import math
import unittest

import agent
from test_agent import observation


class CrawlPassingTests(unittest.TestCase):
    def committed(self, offset=-3.0, gap=7.3, dn=-.6):
        row = observation(speed=2.7, curve=.006, wet=.95)
        row["self"]["n"] = offset
        row["rivals"] = [dict(seat=1, gap_m=gap, dn=dn, speed_mps=2.7, status="racing")]
        driver = agent.Driver()
        driver.phase = row["phase"]
        driver.lane = driver.pass_lane = -3.0
        driver.pass_seat = 1
        return driver, row

    def test_crawling_car_in_committed_lane_prompts_new_side(self):
        driver, row = self.committed()
        driver.act(row)
        self.assertEqual(driver.pass_lane, 3.0)
        self.assertGreater(driver.lane, -3.0)

    def test_intervening_car_blocks_sweep_to_free_destination(self):
        driver, row = self.committed()
        row["rivals"].append(dict(seat=2, gap_m=-4, dn=3, speed_mps=4, status="racing"))
        driver.act(row)
        self.assertEqual(driver.lane, -3.0)

    def test_drift_into_future_lane_is_seen_before_current_overlap(self):
        driver, row = self.committed(offset=.5, dn=-3.5)
        driver.lane = .5
        driver.act(row)
        self.assertEqual(driver.pass_lane, 3.0)
        self.assertGreater(driver.lane, .5)

    def test_no_switch_across_close_leader(self):
        driver, row = self.committed(gap=4, dn=.6)
        action = driver.act(row)
        self.assertEqual(driver.lane, -3.0)
        self.assertGreaterEqual(action["brake"], .75)


class WetBrakeBudgetTests(unittest.TestCase):
    def approach(self, aero, brake=50_000):
        row = observation(speed=70, wet=.8)
        car = row["self"]
        car.update(downforce_n=aero, effective_mass_kg=1000, brake_force_max_n=brake)
        rows = [[d, .045 if d >= 150 else 0, 0, 8, 8, 0] for d in range(15, 361, 15)]
        target = agent.Driver().speed_plan(row, rows, (0, 0, 8, 8), 1/30)
        return target, agent.tyre_mu(row)

    def test_partial_wet_aero_credit_stays_below_integrated_braking_bound(self):
        target, mu = self.approach(6000)
        coefficient = 6000 / (1000 * 70**2)
        corner_v2 = mu * agent.LATERAL_RESERVE * 9.81 / (.045 - mu * agent.LATERAL_RESERVE * coefficient)
        distance = 150 - 3 - 70/30
        # Closed-form upper bound for straight braking at mu*g plus half the
        # aero load. The actual approach also has to turn into the corner.
        a, b = mu * 9.81, .5 * mu * coefficient
        ideal_v2 = (corner_v2 + a/b) * math.exp(2 * b * distance) - a/b
        self.assertLessEqual(target**2, ideal_v2 + .01)
        zero_aero, _ = self.approach(0)
        self.assertGreater(target, zero_aero)
        capped, _ = self.approach(6000, brake=5000)
        self.assertLessEqual(capped**2, corner_v2 + 2 * 5 * distance + .01)

    def test_no_aero_uses_wet_ground_grip(self):
        target, mu = self.approach(0)
        corner_v2 = mu * agent.LATERAL_RESERVE * 9.81 / .045
        self.assertLessEqual(target**2, corner_v2 + 2 * mu * 9.81 * (150 - 3 - 70/30) + .01)
