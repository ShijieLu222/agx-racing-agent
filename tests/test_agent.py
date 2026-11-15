"""Behavioral checks on legal synthetic observations, not a race simulator."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


COLUMNS = ["distance_m", "curvature_1pm", "grade",
           "half_width_left_m", "half_width_right_m", "aero_zone"]


def observation(phase="race", speed=35.0, curve=0.0, wet=0.0):
    """AGX 4.4 field shapes; a synthetic unknown track prevents map leakage."""
    return {
        "game_id": "racing", "rules_version": "rsi-racing-4.4",
        "kernel_version": "rsi-formula-4.0", "seat": 0, "decision": 300,
        "tick": 600, "phase_tick": 600, "time": 10.0, "hold_ticks": 2,
        "phase": phase, "laps_total": 4 if phase == "race" else 1,
        "position": 1, "track_length_m": 5000.0,
        "self": {
            "aid_mode": "electrical_override_v1", "aid_available": False,
            "aid_zone": None, "aid_active": False, "aid_extra_recharge_mj": 0.0,
            "ers_deployed_mj": 0.0, "ers_harvested_mj": 0.0,
            "aid_extra_deployed_mj": 0.0, "ers_power_kw": 0.0,
            "override_available": False, "override_active": False,
            "lap": 0, "s": 100.0, "distance": 100.0,
            "n": 0.0, "heading_error": 0.0, "speed_mps": speed,
            "vx": speed, "vy": 0.0, "yaw_rate": speed * curve,
            "steer": 0.0, "gear": 4, "rpm": 9000.0,
            "throttle": 0.0, "brake": 0.0, "ers_soc_mj": 3.0,
            "ers_mode": 1, "aero_mode": 0,
            "tyre_temp_c": [84.0] * 4, "tyre_wear": [0.0] * 4,
            "fuel_kg": 70.0, "brake_temp_c": [500.0] * 4,
            "pu_temp_c": 88.0, "ride_height_mm": [40.0, 75.0],
            "g_lat": speed * speed * curve / 9.81, "g_long": 0.0,
            "compound": "medium", "pit_state": 0, "pit_stops": 0,
            "status": "racing", "x": 100.0, "y": 0.0, "z": 0.0,
            "yaw": 0.0, "drag_n": 1500.0, "downforce_n": 2500.0,
            "effective_mass_kg": 900.0, "rolling_resistance_n": 100.0,
            "drive_force_n": [5000.0, 7000.0, 9000.0, 11000.0],
            "brake_force_max_n": 40000.0,
            "front_sliding": False, "rear_sliding": False,
        },
        "preview": {"columns": COLUMNS[:], "rows": [
            [15.0 * i, curve, 0.0, 8.0, 8.0, 0] for i in range(1, 25)
        ]},
        "rivals": [],
        "weather": {"condition": "wet" if wet >= .5 else "damp" if wet > .05 else "dry",
                    "rain_probability": 0.15, "rain_intensity": 0.0,
                    "track_wetness": wet, "air_temp_c": 24.0, "track_temp_c": 30.0},
        "forecast": {"condition": "dry", "rain_probability": .15,
                     "rain_intensity": 0.0, "track_wetness": 0.0,
                     "air_temp_c": 24.0, "track_temp_c": 30.0},
        "tyres": {"allocation": {"hard": "C3", "medium": "C4", "soft": "C5"}},
        "limits": {"recharge_mj": 8.5, "soc_window_mj": 4.0},
    }


def advance(row, distance=1.0):
    result = copy.deepcopy(row)
    result["tick"] += 2
    result["phase_tick"] += 2
    result["time"] += 1 / 30
    result["decision"] += 1
    result["self"]["distance"] += distance
    result["self"]["s"] = (result["self"]["s"] + distance) % result["track_length_m"]
    return result


class DriverTests(unittest.TestCase):
    def setUp(self):
        agent.init({})

    def fresh(self, row):
        agent.init({})
        return agent.act(copy.deepcopy(row))

    def assertLegal(self, action):
        self.assertIsInstance(action, dict)
        allowed = {"throttle", "brake", "steer", "ers_mode", "aero_mode",
                   "override", "aid", "pit_request", "pit_compound"}
        self.assertLessEqual(set(action), allowed)
        for field, bounds in (("throttle", (0, 1)), ("brake", (0, 1)), ("steer", (-1, 1))):
            self.assertIn(field, action)
            self.assertIn(type(action[field]), (int, float))
            self.assertTrue(math.isfinite(action[field]))
            self.assertGreaterEqual(action[field], bounds[0])
            self.assertLessEqual(action[field], bounds[1])
        for field, values in (("ers_mode", range(4)), ("aero_mode", range(2))):
            if field in action:
                self.assertIs(type(action[field]), int)
                self.assertIn(action[field], values)
        for field in ("override", "aid", "pit_request"):
            if field in action:
                self.assertIs(type(action[field]), bool)
        self.assertIn(action.get("pit_compound"), (None, "soft", "medium", "hard"))
        self.assertFalse(action["throttle"] > 0 and action["brake"] > 0)

    def test_legal_actions_across_normal_extreme_operating_states(self):
        for phase in ("qualifying", "race"):
            for speed in (0.0, 22.0, 60.0, 95.0):
                for wet in (0.0, .49, .5, 1.0):
                    for sign in (-1, 1):
                        row = observation(phase, speed, sign * .025, wet)
                        row["self"].update(n=sign * 6.0, heading_error=sign * .8)
                        with self.subTest(phase=phase, speed=speed, wet=wet, sign=sign):
                            self.assertLegal(self.fresh(row))

    def test_preview_column_order_does_not_change_decision(self):
        original = observation(curve=.006, wet=.2)
        original["preview"]["rows"][12][1] = -.025
        reordered = copy.deepcopy(original)
        order = [5, 3, 1, 0, 4, 2]
        reordered["preview"]["columns"] = [COLUMNS[i] for i in order]
        reordered["preview"]["rows"] = [[r[i] for i in order] for r in original["preview"]["rows"]]
        self.assertEqual(self.fresh(original), self.fresh(reordered))

    def test_far_corner_beyond_first_twelve_rows_changes_speed_control(self):
        changed = False
        for speed in (40.0, 50.0, 60.0, 70.0, 80.0):
            straight = observation(speed=speed)
            corner = copy.deepcopy(straight)
            for row in corner["preview"]["rows"][12:]:
                row[1] = .04
            free = self.fresh(straight)
            bounded = self.fresh(corner)
            free_command = free["throttle"] - free["brake"]
            bounded_command = bounded["throttle"] - bounded["brake"]
            self.assertLessEqual(bounded_command, free_command + 1e-12)
            changed |= bounded_command < free_command - 1e-6
        self.assertTrue(changed, "A corner at 195–360 m was ignored at every tested approach speed")

    def test_public_geometry_detects_narrow_bend_between_preview_samples(self):
        row = observation(speed=45.0)
        # A bend 42 m ahead is between the 30 m and 45 m preview samples.
        # Both policies see exactly the same 24 straight preview rows.
        def narrow_bend(length, station):
            curvature = .05 if abs(station - 142.0) < .5 else 0.0
            return curvature, 0.0, 8.0, 8.0

        with patch.object(agent, "geometry_at", return_value=(0.0, 0.0, 8.0, 8.0)):
            free = self.fresh(row)
        with patch.object(agent, "geometry_at", side_effect=narrow_bend):
            bend = self.fresh(row)
        self.assertGreater(free["throttle"], 0.0)
        self.assertEqual(bend["throttle"], 0.0)
        self.assertGreater(bend["brake"], free["brake"])

        # An unrecognized track still drives from legal preview information.
        with patch.object(agent, "geometry_at", return_value=None):
            preview_only = self.fresh(row)
        self.assertEqual(preview_only, free)

    def test_wetness_reduces_estimated_corner_grip(self):
        for risk in ("wet",):
            changed = False
            for speed in (25.0, 35.0, 45.0, 55.0, 65.0):
                row = observation(speed=speed, curve=.008)
                bad = copy.deepcopy(row)
                if risk == "wet":
                    bad["weather"].update(track_wetness=.8, condition="wet")
                else:
                    bad["self"][risk] = True
                a, b = self.fresh(row), self.fresh(bad)
                delta = (b["throttle"] - b["brake"]) - (a["throttle"] - a["brake"])
                self.assertLessEqual(delta, 1e-12, risk)
                changed |= delta < -1e-6
            self.assertTrue(changed, risk)

    def test_position_and_heading_feedback_steer_back_towards_center(self):
        for field, magnitude in (("n", 2.0), ("heading_error", .15)):
            for sign in (-1, 1):
                row = observation(speed=30.0)
                row["self"][field] = sign * magnitude
                action = self.fresh(row)
                self.assertLess(action["steer"] * sign, 0, (field, sign))

    def test_curvature_feedforward_uses_left_positive_convention(self):
        for sign in (-1, 1):
            row = observation(speed=25.0, curve=sign * .006)
            self.assertGreater(self.fresh(row)["steer"] * sign, 0)

    def test_steering_respects_published_actuator_rate(self):
        for actual in (-.25, .25):
            row = observation(speed=25.0)
            row["self"].update(steer=actual, n=5.0 if actual > 0 else -5.0)
            action = self.fresh(row)
            self.assertLessEqual(abs(.3 * action["steer"] - actual), 1.6 / 30 + 1e-12)

    def test_imminent_same_lane_collision_takes_priority_over_boost(self):
        row = observation(speed=45.0)
        row["self"].update(aid_available=True, override_available=True)
        row["rivals"] = [{"seat": 1, "gap_m": 5.0, "dn": 0.0,
                          "speed_mps": 10.0, "lap": 0, "status": "racing"}]
        action = self.fresh(row)
        self.assertEqual(action["throttle"], 0.0)
        self.assertGreater(action["brake"], .5)
        self.assertFalse(action.get("aid", False))
        self.assertFalse(action.get("override", False))

    def test_slow_driver_starts_passing_stationary_car_with_clear_side(self):
        for gap in (8.0, 10.0, 12.0):
            agent.init({})
            row = observation(speed=3.0)
            row["rivals"] = [{"seat": 1, "gap_m": gap, "dn": 0.0,
                              "speed_mps": 0.0, "lap": 0, "status": "racing"}]
            first = agent.act(row)
            second = agent.act(advance(row, distance=.1))
            with self.subTest(gap=gap):
                self.assertNotEqual(first["steer"], 0.0)
                self.assertGreater(first["steer"] * second["steer"], 0.0)
                self.assertLegal(first)
                self.assertLegal(second)
        # This checks the decision to start a clear-side pass, not a simulated
        # guarantee of physically getting around an arbitrarily close obstacle.

    def test_phase_transition_discards_qualifying_decision_state(self):
        qualify = observation("qualifying", curve=.012, wet=.8)
        for _ in range(8):
            agent.act(qualify)
            qualify = advance(qualify)
        race = observation("race", speed=28.0)
        race["tick"] = qualify["tick"] + 2
        race["phase_tick"] = 0
        transitioned = agent.act(copy.deepcopy(race))
        self.assertEqual(transitioned, self.fresh(race))

    def test_init_clears_previous_match_state(self):
        original = observation()
        expected = self.fresh(original)
        row = observation(curve=.018, wet=.8)
        row["self"].update(lap=2, tyre_wear=[.9] * 4)
        agent.act(row)
        self.assertEqual(self.fresh(original), expected)

    def test_official_opening_observation_produces_legal_action(self):
        path = Path(__file__).parent / "fixtures" / "official_observation.json"
        self.assertLegal(self.fresh(json.loads(path.read_text())))

    def test_electrical_aid_respects_safety_and_availability(self):
        for excluded in ("unavailable", "qualifying", "wet", "sliding", "pit", "braking"):
            row = observation(speed=25.0)
            row["self"].update(aid_available=True, override_available=True)
            if excluded == "unavailable":
                row["self"].update(aid_available=False, override_available=False)
            elif excluded == "qualifying":
                row["phase"] = "qualifying"
            elif excluded == "wet":
                row["weather"].update(track_wetness=.5, condition="wet")
            elif excluded == "sliding":
                row["self"]["rear_sliding"] = True
            elif excluded == "pit":
                row["self"]["pit_state"] = 1
            else:
                row = observation(speed=95.0, curve=.05)
                row["self"].update(aid_available=True, override_available=True)
            with self.subTest(excluded=excluded):
                action = self.fresh(row)
                self.assertFalse(action.get("aid", False))
                self.assertFalse(action.get("override", False))

    def test_preview_alone_does_not_certify_current_aero_zone(self):
        row = observation(speed=40.0)
        for point in row["preview"]["rows"]:
            point[5] = 1
        self.assertEqual(self.fresh(row).get("aero_mode", 0), 0)

    def test_pit_transit_has_neutral_driving_actions(self):
        for pit_state in (1, 2, 3):
            row = observation(speed=22.0, curve=.025)
            row["self"].update(pit_state=pit_state, n=5.0, heading_error=.6)
            action = self.fresh(row)
            self.assertEqual((action["throttle"], action["brake"], action["steer"]), (0, 0, 0))
            self.assertEqual(action.get("aero_mode", 0), 0)
            self.assertFalse(action.get("aid", False))
            self.assertFalse(action.get("override", False))

    def test_mandatory_pit_request_persists_until_entry(self):
        row = observation()
        row["self"].update(lap=2, distance=10100.0)
        first = agent.act(row)
        self.assertTrue(first["pit_request"])
        self.assertNotEqual(first["pit_compound"], row["self"]["compound"])
        for _ in range(5):
            row = advance(row)
            action = agent.act(row)
            self.assertTrue(action["pit_request"])
            self.assertEqual(action["pit_compound"], first["pit_compound"])

    def test_damp_and_qualifying_wet_do_not_waive_race_compound_rule(self):
        for qualifier_wet, race_wet in ((0.0, .49), (.8, 0.0)):
            agent.init({})
            agent.act(observation("qualifying", wet=qualifier_wet))
            row = observation("race", wet=race_wet)
            row["self"].update(lap=2, distance=10100.0)
            self.assertTrue(agent.act(row)["pit_request"])

    def test_race_wet_waiver_persists_after_track_dries(self):
        wet = observation(wet=.5)
        agent.act(wet)
        dry = advance(wet)
        dry["weather"].update(track_wetness=0.0, condition="dry")
        dry["self"].update(lap=2, distance=10101.0)
        self.assertFalse(agent.act(dry)["pit_request"])

    def test_two_compounds_count_only_after_forward_on_track_use(self):
        row = observation()
        agent.act(row)
        row = advance(row)
        agent.act(row)  # medium has been driven on track
        row = advance(row)
        row["self"].update(pit_state=2, compound="hard")
        agent.act(row)
        row = advance(row)
        row["self"].update(pit_state=0, pit_stops=1)
        agent.act(row)
        row = advance(row)
        row["self"].update(lap=2, distance=10105.0)
        self.assertFalse(agent.act(row)["pit_request"])

    def test_stationary_compound_change_does_not_satisfy_dry_rule(self):
        row = observation()
        agent.act(row)
        row = advance(row)
        agent.act(row)
        row = advance(row, distance=0.0)
        row["self"].update(compound="hard", speed_mps=0.0, vx=0.0)
        agent.act(row)
        row = advance(row, distance=0.0)
        row["self"]["lap"] = 2
        self.assertTrue(agent.act(row)["pit_request"])

    def test_pit_exit_does_not_latch_a_second_unnecessary_stop(self):
        row = observation()
        agent.act(row)
        row = advance(row)
        agent.act(row)
        row["self"].update(lap=2, distance=10100.0)
        row = advance(row)
        requested = agent.act(row)
        self.assertTrue(requested["pit_request"])
        tyre = requested["pit_compound"]
        for state in (1, 2, 3):
            row = advance(row)
            row["self"].update(pit_state=state, compound=tyre)
            agent.act(row)
        row = advance(row)
        row["self"].update(pit_state=0, pit_stops=1)
        self.assertFalse(agent.act(row)["pit_request"])
        row = advance(row)
        self.assertFalse(agent.act(row)["pit_request"])


if __name__ == "__main__":
    unittest.main()
