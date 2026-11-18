import math
import unittest

import agent
import parkland_line as line
from test_agent import observation
from track_data import TRACKS, geometry_at


def corner_observation(station=4130):
    row = observation(phase='race', speed=25, wet=.5)
    ref = line.reference(station)
    offset, heading = ref[:2] if ref else (0, 0)
    row['track_length_m'] = line.LENGTH
    row['self'].update(s=station, distance=station, n=offset, heading_error=heading)
    row['preview']['rows'] = [[d, *geometry_at(line.LENGTH, station+d), 0]
                              for d in range(15, 361, 15)]
    return row


class ParklandGeometryTests(unittest.TestCase):
    def test_spline_is_bounded_and_joins_the_centerline(self):
        for s, (offset, heading, correction, metric, _) in line.SAMPLES.items():
            _, _, left, right = geometry_at(line.LENGTH, s)
            self.assertGreaterEqual(min(left-offset, right+offset), 2.99)
            self.assertGreater(metric, .8)
            self.assertLess(abs(heading), .3)
        for start, controls in line.CONTROLS.items():
            for station in (start, start+10*(len(controls)-1)):
                self.assertEqual(line.reference(station)[:3], (0., 0., 0.))

    def test_curvature_agrees_with_independent_cartesian_three_point_arc(self):
        # Integrate the road tangent on each side of the sample, then place
        # the offset along the local road normals to form three actual points.
        for station in (2319, 2363, 2704, 3050, 4130, 4320):
            pts = []
            for delta in (-1, 0, 1):
                x = y = angle = 0.
                ds = delta/20
                for i in range(20):
                    k = geometry_at(line.LENGTH, station+(i+.5)*ds)[0]
                    x += ds*math.cos(angle+.5*k*ds)
                    y += ds*math.sin(angle+.5*k*ds)
                    angle += k*ds
                n = line.reference(station+delta)[0]
                pts.append((x-n*math.sin(angle), y+n*math.cos(angle)))
            a,b,c = pts
            cross = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
            measured = 2*cross/(math.dist(a,b)*math.dist(b,c)*math.dist(a,c))
            ref = line.reference(station)
            self.assertAlmostEqual(measured, ref[2]+ref[4], delta=.0025)

    def test_preview_keeps_unexpected_live_curvature_and_path_distance(self):
        rows = [(0,.12,0), (2,.12,0), (4,.12,0)]
        plan = line.planning_window(rows, 4130, tracked=True)
        self.assertTrue(all(abs(k) >= .12 for _,k,_ in plan))
        self.assertTrue(0 < plan[1][0] < plan[2][0] < 4)


class ParklandDrivingTests(unittest.TestCase):
    def test_tracked_apex_relaxes_speed_and_commands_the_same_curve(self):
        o = corner_observation()
        d = agent.Driver()
        rows = agent.preview_rows(o)
        geo = d.current_geometry(o, rows)
        center_speed = d.speed_plan(o, rows, geo, 1/30)
        ref = line.reference(4130)
        path_k = geo[0]+ref[2]
        o['self'].update(yaw_rate=25*path_k, steer=math.atan(3.4*path_k))
        action = d.act(o)
        self.assertTrue(d.line_active and d.line_tracked)
        self.assertGreater(d.last_target, center_speed+3)
        self.assertAlmostEqual(action['steer']*.3, math.atan(3.4*path_k))
        self.assertAlmostEqual(d.lane, ref[0])

    def test_missing_line_keeps_conservative_corner_speed(self):
        o = corner_observation()
        o['self']['n'] = -1
        d = agent.Driver()
        rows = agent.preview_rows(o)
        geo = d.current_geometry(o, rows)
        baseline = d.speed_plan(o, rows, geo, 1/30)
        d.line_active = True
        d.select_line(o, geo)
        self.assertFalse(d.line_tracked)
        self.assertLessEqual(d.speed_plan(o, rows, geo, 1/30), baseline+1e-8)

    def test_alongside_car_freezes_return_at_actual_offset(self):
        d = agent.Driver()
        o = corner_observation()
        d.act(o)
        self.assertTrue(d.line_active)
        o['self']['n'] = 2.1
        o['rivals'] = [dict(seat=2,status='racing',gap_m=-2,dn=-1.,speed_mps=24)]
        o['time'] += 1/30
        d.act(o)
        self.assertFalse(d.line_active)
        self.assertTrue(d.returning_from_line)
        self.assertAlmostEqual(d.lane, 2.1)

    def test_close_leader_preserves_v11_emergency_and_fast_rear_blocks_line(self):
        for gap, speed in ((4, 12), (-49, 55)):
            o = corner_observation()
            o['rivals'] = [dict(seat=2,status='racing',gap_m=gap,dn=0,speed_mps=speed)]
            d = agent.Driver()
            action = d.act(o)
            self.assertFalse(d.line_active)
            if gap > 0:
                self.assertEqual(action['throttle'], 0)
                self.assertGreaterEqual(action['brake'], .75)

    def test_other_maps_and_pit_do_not_select_a_parkland_apex(self):
        for length in (TRACKS['highland']['length'], TRACKS['crossover']['length'], 5000):
            o = corner_observation()
            o['track_length_m'] = length
            d = agent.Driver()
            d.act(o)
            self.assertFalse(d.line_active)
        o = corner_observation()
        o['self']['pit_state'] = 1
        d = agent.Driver()
        self.assertEqual(d.act(o), agent.neutral())
        self.assertFalse(d.line_active)
