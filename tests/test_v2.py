"""Wet-control regressions updated for v5; synthetic inputs are not physics."""
import copy
import unittest
from unittest.mock import patch

import agent
from test_agent import advance, observation


class WetControlRegressionTests(unittest.TestCase):
    def setUp(self):
        agent.init({})

    def test_one_frame_slip_does_not_leave_false_braking_after_flag_clears(self):
        row = observation(speed=20.0, curve=.003, wet=1.0)
        agent.act(row)
        row = advance(row)
        row['self']['rear_sliding'] = True
        pulse = agent.act(row)
        self.assertEqual(pulse['brake'], 0.0)
        self.assertGreater(pulse['throttle'], .28)
        row = advance(row)
        row['self']['rear_sliding'] = False
        recovered = agent.act(row)
        self.assertEqual(recovered['brake'], 0.0)
        self.assertGreater(recovered['throttle'], 0.0)

    def test_repeated_isolated_slip_flags_do_not_ratchet_clean_speed_control_down(self):
        row = observation(speed=20.0, curve=.003, wet=1.0)
        clean_actions = []
        for i in range(90):
            row['self']['rear_sliding'] = i % 3 == 1
            action = agent.act(row)
            if i % 3 == 2:
                clean_actions.append(action)
            row = advance(row)
        self.assertTrue(clean_actions)
        self.assertTrue(all(a['brake'] == 0 for a in clean_actions))
        self.assertTrue(all(a['throttle'] > 0 for a in clean_actions))

    def test_sustained_measured_sideslip_retains_active_deceleration(self):
        row = observation(speed=25.0, curve=.003, wet=1.0)
        agent.act(row)
        row['self']['rear_sliding'] = True
        row['self']['vy'] = 8.0
        actions = []
        for _ in range(18):
            row = advance(row)
            actions.append(agent.act(row))
        self.assertTrue(all(a['throttle'] <= .28 for a in actions))
        self.assertTrue(any(a['brake'] > 0 for a in actions[-6:]))
        self.assertTrue(all(not a['aid'] for a in actions))

    def test_slip_flags_without_measured_instability_do_not_force_braking(self):
        row = observation(speed=25.0, curve=.003, wet=1.0)
        agent.act(row)
        actions = []
        for i in range(24):
            row = advance(row)
            # A persistently unstable tyre with brief interruptions remains risky.
            row['self']['rear_sliding'] = i % 8 != 7
            actions.append(agent.act(row))
        self.assertTrue(all(a['brake'] == 0 for a in actions))

    def test_large_heading_error_brakes_immediately_after_transient_slip(self):
        row = observation(speed=25.0, wet=1.0)
        row['self']['rear_sliding'] = True
        agent.act(row)
        row = advance(row)
        row['self'].update(rear_sliding=False, heading_error=.8)
        action = agent.act(row)
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreater(action['brake'], 0.0)
        self.assertFalse(action['aid'])

    def test_off_track_margin_brakes_without_waiting_for_slip_confirmation(self):
        row = observation(speed=30.0, wet=1.0)
        agent.act(row)
        row = advance(row)
        row['self']['n'] = 8.4
        action = agent.act(row)
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreater(action['brake'], 0.0)

    def test_nearby_stopped_car_interrupts_established_boost_immediately(self):
        row = observation(speed=25.0)
        row['self'].update(aid_available=True, override_available=True)
        before = agent.act(row)
        self.assertGreater(before['throttle'], 0)
        row = advance(row)
        row['rivals'] = [{'seat': 1, 'gap_m': 4.0, 'dn': 0.0,
                          'speed_mps': 0.0, 'lap': 0, 'status': 'racing'}]
        action = agent.act(row)
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreaterEqual(action['brake'], .75)
        self.assertEqual(action['ers_mode'], 0)
        self.assertFalse(action['aid'])

    def test_new_sharp_corner_interrupts_power_without_hysteresis_delay(self):
        row = observation(speed=45.0)
        agent.act(row)
        row = advance(row)
        for sample in row['preview']['rows']:
            sample[1] = .06
        action = agent.act(row)
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreater(action['brake'], .1)

    def test_phase_reset_discards_slip_and_longitudinal_hysteresis(self):
        row = observation('qualifying', speed=35.0, wet=1.0)
        row['self']['rear_sliding'] = True
        for _ in range(30):
            agent.act(row)
            row = advance(row)
        race = observation('race', speed=20.0, wet=.2)
        transitioned = agent.act(copy.deepcopy(race))
        agent.init({})
        self.assertEqual(transitioned, agent.act(copy.deepcopy(race)))

    def test_init_clears_intermittent_slip_history(self):
        row = observation(speed=25.0, wet=1.0)
        for i in range(20):
            row['self']['rear_sliding'] = i % 5 != 4
            agent.act(row)
            row = advance(row)
        agent.init({})
        fresh = observation(speed=20.0, wet=1.0)
        action = agent.act(fresh)
        self.assertEqual(action['brake'], 0.0)
        self.assertGreater(action['throttle'], 0.0)

    def test_alternating_slip_flags_do_not_accumulate_a_pace_penalty(self):
        row = observation(speed=25.0, curve=.003, wet=1.0)
        agent.act(row)
        tail = []
        for i in range(60):
            row = advance(row)
            row['self']['rear_sliding'] = i % 2 == 0
            action = agent.act(row)
            if i >= 50:
                tail.append(action)
        self.assertTrue(all(a['brake'] == 0 for a in tail))

    def test_severe_sideways_velocity_brakes_on_first_observation(self):
        row = observation(speed=25.0, wet=1.0)
        row['self'].update(vx=25.0, vy=10.0, aid_available=True)
        action = agent.act(row)
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreater(action['brake'], 0.0)
        self.assertFalse(action['aid'])

    def test_boost_does_not_chatter_around_its_entry_threshold(self):
        row = observation(speed=39.0)
        # v6 additionally requires force demand beyond the lower power tiers.
        row['self']['drive_force_n'] = [1000, 2000, 2500, 3000]
        modes = []
        with patch.object(agent.Driver, 'speed_plan', return_value=40.0):
            for error in (1.0, 1.6, 1.4, 1.6, 1.4, .4):
                row['self'].update(speed_mps=40.0-error, vx=40.0-error)
                modes.append(agent.act(row)['ers_mode'])
                row = advance(row)
        self.assertEqual(modes, [1, 3, 3, 3, 3, 1])

    def test_braking_hysteresis_preserves_small_overspeed_then_releases(self):
        row = observation(speed=39.0)
        actions = []
        with patch.object(agent.Driver, 'speed_plan', return_value=40.0):
            for error in (1.6, -.6, -.3, -.1):
                row['self'].update(speed_mps=40.0-error, vx=40.0-error)
                actions.append(agent.act(row))
                row = advance(row)
        # Neutral already covers this small acceleration demand in v6.
        self.assertEqual(actions[0]['ers_mode'], 1)
        for action in actions[1:3]:
            self.assertEqual(action['throttle'], 0.0)
            self.assertGreater(action['brake'], 0.0)
            self.assertEqual(action['ers_mode'], 0)
        self.assertEqual(actions[-1]['brake'], 0.0)

    def test_boost_restarts_immediately_when_measured_instability_clears(self):
        row = observation(speed=25.0)
        self.assertEqual(agent.act(row)['ers_mode'], 3)
        row = advance(row)
        row['self'].update(rear_sliding=True, heading_error=.8)
        self.assertNotEqual(agent.act(row)['ers_mode'], 3)
        modes = []
        for _ in range(10):
            row = advance(row)
            row['self'].update(rear_sliding=False, heading_error=0.0)
            modes.append(agent.act(row)['ers_mode'])
        self.assertTrue(all(mode == 3 for mode in modes))

    def test_repeated_slip_flags_do_not_disable_ers_when_car_tracks_cleanly(self):
        row = observation(speed=25.0)
        self.assertEqual(agent.act(row)['ers_mode'], 3)
        for i in range(30):
            row = advance(row)
            row['self']['rear_sliding'] = i % 3 == 0
            self.assertEqual(agent.act(row)['ers_mode'], 3)

    def test_boost_recovery_wait_does_not_delay_emergency_braking(self):
        row = observation(speed=35.0)
        self.assertEqual(agent.act(row)['ers_mode'], 3)
        row = advance(row)
        row['self']['rear_sliding'] = True
        agent.act(row)
        row = advance(row)
        row['self']['rear_sliding'] = False
        row['rivals'] = [{'seat': 1, 'gap_m': 3.0, 'dn': 0.0,
                          'speed_mps': 0.0, 'lap': 0, 'status': 'racing'}]
        action = agent.act(row)
        self.assertEqual(action['throttle'], 0.0)
        self.assertGreaterEqual(action['brake'], .75)
        self.assertEqual(action['ers_mode'], 0)

    def test_slip_does_not_clear_latched_wet_compound_waiver(self):
        row = observation(wet=.5)
        agent.act(row)
        for _ in range(12):
            row = advance(row)
            row['self']['rear_sliding'] = True
            agent.act(row)
        row = advance(row)
        row['weather']['track_wetness'] = 0.0
        row['self'].update(rear_sliding=False, lap=2, distance=10100.0)
        self.assertFalse(agent.act(row)['pit_request'])


if __name__ == '__main__':
    unittest.main()
