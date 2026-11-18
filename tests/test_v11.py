"""Synthetic cut-in geometry checks; these do not recreate private race inputs."""
import unittest
import agent
from test_agent import observation


class ContactSafetyTests(unittest.TestCase):
    def row(self, dn, gap=25, now=10, speed=30, front_speed=25):
        o=observation(speed=speed,curve=.01,wet=.8)
        o['time']=now
        o['rivals']=[dict(seat=2,status='racing',gap_m=gap,dn=dn,speed_mps=front_speed)]
        return o

    def plan(self,d,o):
        return d.traffic_plan(o,agent.preview_rows(o),45,1/30)

    def test_offset_overlap_preserves_six_metre_emergency_buffer(self):
        o=self.row(2.1,gap=4.7,speed=21,front_speed=19)
        target,lane,emergency,_=self.plan(agent.Driver(),o)
        self.assertTrue(emergency)
        self.assertLessEqual(target,14)

    def test_act_keeps_emergency_braking_ahead_of_throttle(self):
        action=agent.Driver().act(self.row(2.1,gap=4.7,speed=21,front_speed=19))
        self.assertEqual(action['throttle'],0)
        self.assertGreaterEqual(action['brake'],.75)

    def test_detects_cut_in_before_current_side_clearance_is_lost(self):
        d=agent.Driver();self.plan(d,self.row(3.3,now=10,gap=18))
        o=self.row(3.1,now=10+1/30,gap=18)
        moving=self.plan(d,o)
        steady=self.plan(agent.Driver(),o)
        self.assertLess(moving[0],steady[0])
        self.assertFalse(moving[2])  # early following intervention, not full emergency

    def test_stable_parallel_car_remains_clear(self):
        d=agent.Driver();self.plan(d,self.row(3.1,now=10,gap=5))
        target,_,emergency,_=self.plan(d,self.row(3.1,now=10+1/30,gap=5))
        self.assertEqual(target,45)
        self.assertFalse(emergency)

    def test_sparse_history_cannot_invent_cut_in_velocity(self):
        d=agent.Driver();self.plan(d,self.row(5,now=10,gap=18))
        target,_,emergency,_=self.plan(d,self.row(3.1,now=11,gap=18))
        self.assertEqual(target,45)
        self.assertFalse(emergency)

    def test_prediction_detects_crossing_then_leaving_our_lane(self):
        d=agent.Driver();self.plan(d,self.row(3.0,now=10,gap=18))
        target,_,_,_=self.plan(d,self.row(2.75,now=10+1/30,gap=18))
        self.assertLess(target,45)

    def test_missing_rival_discards_history(self):
        d=agent.Driver();self.plan(d,self.row(4,now=10))
        o=self.row(3,now=10+1/30);o['rivals']=[];self.plan(d,o)
        self.assertEqual(d.traffic_history,{})

    def test_close_rear_car_does_not_trigger_front_emergency(self):
        target,_,emergency,_=self.plan(agent.Driver(),self.row(0,gap=-4))
        self.assertFalse(emergency)
        self.assertEqual(target,45)


if __name__=='__main__':unittest.main()
