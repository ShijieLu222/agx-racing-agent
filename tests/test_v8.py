"""Regressions for normal tight-turn motion and blocked-corner avoidance."""
import math
import unittest
from unittest.mock import patch

import agent
from test_agent import observation, advance


class HairpinTests(unittest.TestCase):
    def test_compensating_heading_and_beta_are_not_a_spin(self):
        for sign in (-1,1):
            row=observation(speed=10,curve=sign*.08)
            row['self'].update(heading_error=-sign*.12,vy=sign*1.2,
                               yaw_rate=sign*.75,steer=sign*.26)
            risk,_,_=agent.stability_state(row['self'],(sign*.08,0,8,8))
            self.assertEqual(risk,0)
            with patch.object(agent.Driver,'speed_plan',return_value=13):
                action=agent.Driver().act(row)
            self.assertGreater(action['throttle'],0)
            self.assertEqual(action['brake'],0)

    def test_highland_low_speed_exit_does_not_wait_for_5mps_cutoff(self):
        row=observation(speed=8.5,curve=-.084)
        row['self'].update(heading_error=.146,vy=-1.07,yaw_rate=-.728,
                           g_lat=-.73,steer=-.27)
        with patch.object(agent.Driver,'speed_plan',return_value=12):
            action=agent.Driver().act(row)
        self.assertGreater(action['throttle'],0)
        self.assertEqual(action['brake'],0)

    def test_excess_yaw_oversteer_still_cuts_power_early(self):
        for sign in (-1,1):
            row=observation(speed=34.4,curve=sign*.017)
            row['self'].update(heading_error=sign*.09,vy=-sign*3.425,
                               yaw_rate=sign*.953,g_lat=sign*2.23)
            action=agent.Driver().act(row)
            self.assertEqual(action['throttle'],0)
            self.assertFalse(action['aid'])
            self.assertGreater(agent.stability_state(row['self'],(sign*.017,0,8,8))[0],0)

    def test_course_departure_is_protected_without_oversteer_signature(self):
        row=observation(speed=30)
        row['self'].update(heading_error=.22,vy=3,yaw_rate=0)
        self.assertGreater(agent.stability_state(row['self'],(0,0,8,8))[0],0)
        self.assertEqual(agent.Driver().act(row)['throttle'],0)

    def blocked_corner(self, gap=6.3):
        row=observation(speed=.3,curve=-.08)
        row['self'].update(n=-.9,heading_error=.10)
        row['rivals']=[{'seat':1,'gap_m':gap,'dn':-.9,'speed_mps':0,'status':'racing'}]
        return row

    def test_stopped_car_can_be_passed_in_wide_corner_at_creep_speed(self):
        row=self.blocked_corner()
        d=agent.Driver(); rows=agent.preview_rows(row)
        target,lane,emergency,straight=d.traffic_plan(row,rows,8,1/30)
        self.assertFalse(straight)
        self.assertFalse(emergency)
        self.assertEqual(d.pass_seat,1)
        self.assertGreater(lane,0)  # stopped car is to our right; pass left
        self.assertGreater(target,0)
        self.assertLess(target,2)  # following clearance remains binding

    def test_stopped_pass_persists_on_curve_while_obstacle_is_ahead(self):
        row=self.blocked_corner(gap=15)
        d=agent.Driver();d.traffic_plan(row,agent.preview_rows(row),8,1/30)
        lane=d.lane
        d.traffic_plan(advance(row),agent.preview_rows(row),8,1/30)
        self.assertEqual(d.pass_seat,1)
        self.assertGreater(d.lane,lane)

    def test_corner_does_not_enable_high_speed_overtaking(self):
        row=self.blocked_corner();row['self']['speed_mps']=20
        d=agent.Driver();d.traffic_plan(row,agent.preview_rows(row),30,1/30)
        self.assertIsNone(d.pass_seat)

    def test_blocked_escape_lanes_do_not_force_a_pass(self):
        row=self.blocked_corner()
        row['rivals'] += [dict(seat=i,gap_m=4,dn=n-row['self']['n'],speed_mps=0,status='racing')
                          for i,n in [(2,-3),(3,3)]]
        d=agent.Driver();d.traffic_plan(row,agent.preview_rows(row),8,1/30)
        self.assertIsNone(d.pass_seat)

    def test_narrow_corner_does_not_force_a_pass(self):
        row=self.blocked_corner()
        for r in row['preview']['rows']:r[3:5]=[3,3]
        d=agent.Driver();d.traffic_plan(row,agent.preview_rows(row),8,1/30)
        self.assertIsNone(d.pass_seat)

    def test_imminent_collision_still_overrides_creeping_pass(self):
        row=self.blocked_corner(gap=3)
        a=agent.Driver().act(row)
        self.assertEqual(a['throttle'],0)
        self.assertGreaterEqual(a['brake'],.75)


if __name__=='__main__':
    unittest.main()
