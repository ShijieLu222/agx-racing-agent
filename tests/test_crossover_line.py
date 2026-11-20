import unittest

import agent
import parkland_line as line
from test_agent import observation
from track_data import geometry_at


def crossover_observation(station, wet):
    row = observation(speed=25, wet=wet)
    row["track_length_m"] = line.CROSSOVER_LENGTH
    row["self"].update(s=station, distance=station)
    row["preview"]["rows"] = [
        [d, *geometry_at(line.CROSSOVER_LENGTH, station+d), 0]
        for d in range(15, 361, 15)
    ]
    return row


class CrossoverLineTests(unittest.TestCase):
    def test_reference_has_room_and_is_selected_on_clear_road(self):
        for s, (offset, angle, _, metric, _) in line.CROSSOVER_SAMPLES.items():
            _, _, left, right = geometry_at(line.CROSSOVER_LENGTH, s)
            self.assertGreaterEqual(min(left-offset, right+offset), 2.99)
            self.assertGreater(metric, .8)
            self.assertLess(abs(angle), .3)
        row = crossover_observation(2130, .9)
        offset, heading = line.reference(2130, line.CROSSOVER_SAMPLES)[:2]
        row["self"].update(n=offset,heading_error=heading)
        d = agent.Driver()
        d.act(row)
        self.assertTrue(d.line_tracked)
        self.assertIs(d.line_samples, line.CROSSOVER_SAMPLES)
        row["rivals"] = [dict(seat=1,status="racing",gap_m=4,dn=0,speed_mps=9)]
        row["time"] += 1/30
        action = d.act(row)
        self.assertFalse(d.line_active)
        self.assertGreaterEqual(action["brake"], .75)

    def test_wet_chicane_lowers_both_apex_targets(self):
        for station in (5225, 5235, 5280):
            o = crossover_observation(station, 1)
            d = agent.Driver()
            rows = agent.preview_rows(o)
            target = d.speed_plan(o, rows, d.current_geometry(o, rows), 1/30)
            self.assertLessEqual(target, 13)

    def test_high_wetness_applies_restriction_before_turn_in(self):
        o = crossover_observation(5170, 1)
        d = agent.Driver()
        rows = agent.preview_rows(o)
        geometry = d.current_geometry(o, rows)
        target = d.speed_plan(o, rows, geometry, 1/30)
        from unittest.mock import patch
        with patch.object(agent, "wet_chicane_speed", side_effect=lambda speed, *_: speed):
            baseline = agent.Driver().speed_plan(o, rows, geometry, 1/30)
        self.assertLess(target, baseline)

    def test_dry_track_does_not_apply_wet_reference(self):
        o = crossover_observation(5225, 0)
        d = agent.Driver()
        rows = agent.preview_rows(o)
        self.assertGreater(d.speed_plan(o, rows, d.current_geometry(o, rows), 1/30), 13)
