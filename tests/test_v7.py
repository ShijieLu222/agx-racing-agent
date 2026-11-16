"""Stability regressions on synthetic legal inputs, not a physical simulator."""
import copy
import math
import unittest
from unittest.mock import patch

import agent
from test_agent import advance, observation
from track_data import TRACKS, geometry_at


class StabilityTests(unittest.TestCase):
    def test_station_allocation_matters_not_just_medium_label(self):
        row = observation()
        parkland = agent.tyre_mu(row)
        row['tyres']['allocation']['medium'] = 'C2'
        self.assertLess(agent.tyre_mu(row), parkland)

    def test_cold_rear_axle_reduces_planned_grip_even_with_warm_fronts(self):
        row = observation()
        warm = agent.tyre_mu(row)
        row['self']['tyre_temp_c'] = [90, 90, 65, 65]
        self.assertLess(agent.tyre_mu(row), warm)
        row['self']['tyre_temp_c'] = [90] * 4
        self.assertEqual(agent.tyre_mu(row), warm)

    def test_crossover_cold_medium_corner_plan_is_below_warm_soft(self):
        row = observation(speed=35)
        track = TRACKS['crossover']
        row['track_length_m'] = track['length']
        row['self'].update(s=3640, distance=3640, compound='soft')
        row['tyres']['allocation'] = {'soft':'C3', 'medium':'C2', 'hard':'C1'}
        row['preview']['rows'] = [[d, *geometry_at(track['length'],3640+d),0] for d in range(15,361,15)]
        geometry = geometry_at(track['length'],3640)
        warm = agent.Driver().speed_plan(row, agent.preview_rows(row), geometry, 1/30)
        row['self'].update(compound='medium',tyre_temp_c=[65]*4)
        cold = agent.Driver().speed_plan(row, agent.preview_rows(row), geometry, 1/30)
        self.assertLess(cold, warm)
        self.assertLess(cold, 128/3.6)

    def test_combined_force_does_not_exceed_estimated_grip(self):
        for g_lat in (0, 1, 1.8, 2.5):
            row = observation(speed=35)
            row['self']['g_lat'] = g_lat
            for target in (10, 80):
                driver = agent.Driver()
                with patch.object(driver,'speed_plan',return_value=target):
                    action = driver.act(row)
                longitudinal = max(action['brake']*row['self']['brake_force_max_n'],
                                   action['throttle']*row['self']['drive_force_n'][action['ers_mode']])
                grip = agent.tyre_mu(row)*(900*9.81+2500)
                allowance = math.sqrt(max(0,grip**2-(900*g_lat*9.81)**2))
                self.assertLessEqual(longitudinal,allowance+1e-8)
                self.assertFalse(action['throttle']>0 and action['brake']>0)

    def test_early_oversteer_stops_boost_before_old_heading_threshold(self):
        row = observation(speed=35,curve=.015)
        row['self'].update(heading_error=.10,vy=-3.5,yaw_rate=1.0,steer=.04,aid_available=True)
        action = agent.Driver().act(row)
        self.assertEqual(action['throttle'],0)
        self.assertLessEqual(action['ers_mode'],1)
        self.assertFalse(action['aid'])
        self.assertLess(action['steer']*.3,row['self']['steer'])

    def test_old_heading_threshold_does_not_create_full_brake_impulse(self):
        row = observation(speed=33,curve=.014)
        row['self'].update(vy=-6,yaw_rate=.6,heading_error=.299)
        driver = agent.Driver()
        before = driver.act(row)
        row = advance(row)
        row['self']['heading_error'] = .301
        after = driver.act(row)
        self.assertLess(after['brake'],.5)
        self.assertLess(abs(after['brake']-before['brake']),.05)

    def test_pose_does_not_jump_route_target_at_old_thresholds(self):
        for h in (.30,.65):
            row = observation(speed=33,curve=.014)
            driver = agent.Driver()
            geometry=(.014,0,8,8)
            row['self']['heading_error']=h-.001
            a=driver.speed_plan(row,agent.preview_rows(row),geometry,1/30)
            row['self']['heading_error']=h+.001
            b=driver.speed_plan(row,agent.preview_rows(row),geometry,1/30)
            self.assertAlmostEqual(a,b)

    def test_recovery_does_not_hold_down_power_after_state_clears(self):
        row=observation(speed=35)
        row['self'].update(heading_error=.2,vy=-5,yaw_rate=.6)
        driver=agent.Driver()
        self.assertEqual(driver.act(row)['throttle'],0)
        clean=advance(observation(speed=35))
        action=driver.act(clean)
        self.assertEqual(action['brake'],0)
        self.assertEqual(action['throttle'],1)
        self.assertEqual(action['ers_mode'],3)

    def test_collision_emergency_still_has_priority_during_spin(self):
        row=observation(speed=35)
        row['self'].update(heading_error=.3,vy=-8,yaw_rate=1.2)
        row['rivals']=[{'seat':1,'gap_m':3,'dn':0,'speed_mps':0,'status':'racing'}]
        action=agent.Driver().act(row)
        self.assertGreaterEqual(action['brake'],.75)
        self.assertEqual(action['throttle'],0)

    def test_recovery_steering_is_mirrored_and_respects_actuator(self):
        actions=[]
        for sign in (-1,1):
            row=observation(speed=35,curve=sign*.014)
            row['self'].update(heading_error=sign*.14,vy=-sign*4,yaw_rate=sign*1,steer=sign*.04)
            a=agent.Driver().act(row)
            self.assertLessEqual(abs(a['steer']*.3-sign*.04),1.6/30+1e-10)
            actions.append(a)
        self.assertAlmostEqual(actions[0]['steer'],-actions[1]['steer'])
        self.assertAlmostEqual(actions[0]['brake'],actions[1]['brake'])

    def test_missing_tyre_metadata_is_finite_and_conservative(self):
        row=observation()
        known=agent.tyre_mu(row)
        row.pop('tyres')
        row['self'].pop('compound')
        row['self']['tyre_temp_c']=[]
        self.assertGreater(agent.tyre_mu(row),0)
        self.assertLess(agent.tyre_mu(row),known)


if __name__=='__main__':
    unittest.main()
