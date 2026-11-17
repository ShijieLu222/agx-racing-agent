"""Cold/dry calibration boundaries and independently bounded approach braking."""
import math
import unittest

import agent
from test_agent import observation


class CoolDryTests(unittest.TestCase):
    def row(self, temp, wet=0):
        o = observation(wet=wet)
        o['self']['tyre_temp_c'] = [temp]*4
        return o

    def test_cool_dry_calibration_is_continuous_monotone_and_bounded(self):
        values = [agent.tyre_mu(self.row(t)) for t in range(35, 91)]
        self.assertEqual(values, sorted(values))
        self.assertLessEqual(max(values), 1.75*1.28+1e-12)
        for threshold in (40, 55, 65, 80):
            self.assertLess(abs(agent.tyre_mu(self.row(threshold+.0001))-
                                agent.tyre_mu(self.row(threshold-.0001))), .0001)

    def test_cold_tyres_keep_penalty_but_dry_correction_is_not_disabled(self):
        self.assertGreater(agent.tyre_mu(self.row(55)), 1.75*.90)
        self.assertLess(agent.tyre_mu(self.row(55)), agent.tyre_mu(self.row(80)))

    def test_very_cold_and_wet_conditions_do_not_gain_dry_bonus(self):
        self.assertAlmostEqual(agent.tyre_mu(self.row(40)), 1.75*.84)
        for wet in (.3, .6, 1):
            for temp in (40, 55, 65, 80):
                cold = max(.80, 1-.004*max(0,80-temp))
                self.assertAlmostEqual(agent.tyre_mu(self.row(temp,wet)),1.75*(1-.3*wet)*cold)


class AeroBrakingTests(unittest.TestCase):
    def approach(self, downforce=7000, brake=56000, wet=0):
        o = observation(speed=75, wet=wet)
        o['track_length_m'] = 5000  # explicit unknown map; only legal preview
        o['self'].update(s=600, distance=600, downforce_n=downforce,
                         effective_mass_kg=1100, brake_force_max_n=brake)
        o['preview']['rows'] = [[float(d), .04 if d>=180 else 0., 0., 8., 8., 0]
                                for d in range(15,361,15)]
        return o

    def target(self, o):
        d=agent.Driver()
        return d.speed_plan(o,agent.preview_rows(o),(0,0,8,8),1/30)

    def test_aero_supports_later_braking_without_removing_corner(self):
        high=self.approach()
        low=self.approach(downforce=0)
        self.assertGreater(self.target(high),self.target(low)+2)
        self.assertLess(self.target(high),120)

    def test_mechanical_brake_capacity_still_limits_the_envelope(self):
        self.assertLess(self.target(self.approach(brake=6000)),
                        self.target(self.approach(brake=56000))-10)

    def test_envelope_is_below_ideal_integrated_braking_bound(self):
        # Independent scalar ODE: backward integrate max straight-line force
        # from the exact steady corner speed. Real route/combined-force
        # constraints can only require an equal or slower approach.
        o=self.approach();c=o['self'];mu=agent.tyre_mu(o);mass=c['effective_mass_kg']
        aero=c['downforce_n']/c['speed_mps']**2
        v2=mu*agent.LATERAL_RESERVE*9.81/(.04-mu*agent.LATERAL_RESERVE*aero/mass)
        dx=.01
        for _ in range(int((180-3-75/30)/dx)):
            decel=min(c['brake_force_max_n']/mass,mu*(9.81+aero*v2/mass))
            v2+=2*decel*dx
        self.assertLessEqual(self.target(o),math.sqrt(v2)+.01)

    def test_wet_approach_keeps_lower_braking_budget(self):
        self.assertLess(self.target(self.approach(wet=.3)),
                        self.target(self.approach())-5)


if __name__=='__main__':
    unittest.main()
