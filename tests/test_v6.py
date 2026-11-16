"""Energy allocation checks; synthetic inputs do not predict race lap times."""
import unittest

import agent
from test_agent import advance, observation


class EnergyAllocationTests(unittest.TestCase):
    def mode(self, row, force=30000, rate=0):
        driver = agent.Driver()
        return driver.energy_mode(row, (0, 0, 8, 8), force, rate, True)

    def test_neutral_when_it_already_meets_requested_force(self):
        self.assertEqual(self.mode(observation(), force=6500), 1)

    def test_balanced_when_attack_adds_no_required_force(self):
        self.assertEqual(self.mode(observation(), force=8500), 2)

    def test_clear_acceleration_uses_attack(self):
        self.assertEqual(self.mode(observation()), 3)

    def test_high_lateral_load_saves_attack_for_exit(self):
        row = observation(speed=40)
        row['self']['g_lat'] = 2.0
        self.assertEqual(self.mode(row), 2)
        # Near the current estimated lateral capacity, regardless of calibration.
        c = row['self']
        row['self']['g_lat'] = .99 * agent.tyre_mu(row) * (1 + c['downforce_n'] / (c['effective_mass_kg'] * 9.81))
        self.assertEqual(self.mode(row), 1)

    def test_geometry_load_also_prevents_spending_attack(self):
        row = observation(speed=40)
        self.assertEqual(agent.Driver().energy_mode(
            row, (.0123, 0, 8, 8), 30000, 0, True), 2)

    def test_approaching_braking_plan_does_not_spend_boost(self):
        self.assertEqual(self.mode(observation(), rate=-2), 1)

    def test_lateral_load_releases_attack_immediately_at_exit(self):
        row = observation(speed=45)
        row['self']['g_lat'] = 2.0
        driver = agent.Driver()
        action = driver.act(row)
        self.assertEqual(action['ers_mode'], 2)
        self.assertEqual(action['throttle'], 1)
        row = advance(row)
        row['self']['g_lat'] = 0.0
        action = driver.act(row)
        self.assertEqual(action['ers_mode'], 3)
        self.assertEqual(action['throttle'], 1)

    def test_wet_load_reduces_power_tier_without_fixed_speed_cap(self):
        row = observation(speed=40, wet=1)
        row['self']['g_lat'] = 1.5
        self.assertEqual(self.mode(row), 1)
        row['self']['g_lat'] = 0
        row['self']['ers_soc_mj'] = .1
        action = agent.Driver().act(row)
        self.assertEqual(action['ers_mode'], 3)
        self.assertEqual(action['throttle'], 1)

    def test_braking_keeps_priority_over_energy_allocation(self):
        driver = agent.Driver()
        driver.braking = True
        self.assertEqual(driver.energy_mode(observation(), (0, 0, 8, 8), 30000, 0, True), 0)

    def test_missing_extra_motor_force_does_not_spend_energy(self):
        row = observation()
        row['self']['drive_force_n'] = [7000] * 4
        self.assertEqual(self.mode(row), 1)


if __name__ == '__main__':
    unittest.main()
