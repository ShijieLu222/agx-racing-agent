"""Diagnostic closed-loop bicycle model on public geometry, NOT the AGX engine.

This checks steering signs, gross oscillation and a planning time scale. It has
NO tyre slip limit, load sensitivity, suspension, collisions, tyre/fuel/ERS
consumption, weather dynamics, pit transit or engine/gearbox map. Its forces are
explicit invented test inputs. Never report its lap times as AGX performance.

Usage: python3 scripts/kinematic_check.py  # No fixed speed cap by default.
       python3 scripts/kinematic_check.py --compare 58 90  # Diagnostic caps only.
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import track_data

MASS_KG = 1000.0
DRIVE_FORCE_N = [7000.0, 9000.0, 13000.0, 18000.0]
BRAKE_FORCE_N = 40000.0
DRAG_COEFFICIENT = 0.7
ROLLING_FORCE_N = 100.0


def run(track, speed_cap, seconds=400.0, body_sideslip=False, downforce_coefficient=0.0, tyre_temp=85.0):
    old_cap = agent.DRY_SPEED_CAP
    agent.DRY_SPEED_CAP = speed_cap
    length = track["length"]
    station = offset = heading = wheel_angle = yaw_rate = travelled = 0.0
    speed = 15.0
    max_offset = max_heading = max_lateral_demand = 0.0
    offtrack = False
    driver = agent.Driver()
    try:
        for decision in range(int(seconds * 30)):
            beta = math.atan(.5 * math.tan(wheel_angle)) if body_sideslip else 0.0
            rows = []
            for distance in range(15, 361, 15):
                curvature, grade, left, right = track_data.geometry_at(length, station + distance)
                rows.append([distance, curvature, grade, left, right, 0])
            observation = {
                "phase": "qualifying", "time": decision / 30,
                "track_length_m": length, "laps_total": 1,
                "weather": {"track_wetness": 0}, "rivals": [],
                "preview": {"columns": list(agent.COLUMNS), "rows": rows},
                "self": {
                    "s": station, "distance": travelled, "n": offset,
                    "heading_error": heading, "speed_mps": speed,
                    "vx": speed * math.cos(beta), "vy": speed * math.sin(beta), "yaw_rate": yaw_rate,
                    "steer": wheel_angle, "fuel_kg": 60, "pu_temp_c": 90,
                    "tyre_wear": [0] * 4, "tyre_temp_c": [tyre_temp] * 4,
                    "downforce_n": downforce_coefficient * speed * speed,
                    "ers_soc_mj": 3, "effective_mass_kg": MASS_KG,
                    "drag_n": DRAG_COEFFICIENT * speed * speed,
                    "rolling_resistance_n": ROLLING_FORCE_N,
                    "drive_force_n": DRIVE_FORCE_N,
                    "brake_force_max_n": BRAKE_FORCE_N,
                    "status": "racing", "lap": 0, "compound": "soft",
                    "pit_state": 0, "pit_stops": 0,
                },
            }
            action = driver.act(observation)
            for _ in range(2):
                dt = 1 / 60
                curvature, grade, left, right = track_data.geometry_at(length, station)
                wheel_angle += agent.clip(action["steer"] * 0.3 - wheel_angle,
                                          -1.6 * dt, 1.6 * dt)
                force = (action["throttle"] * DRIVE_FORCE_N[action["ers_mode"]]
                         - action["brake"] * BRAKE_FORCE_N
                         - DRAG_COEFFICIENT * speed * speed - ROLLING_FORCE_N)
                speed = max(0.0, speed + (force / MASS_KG - 9.81 * grade) * dt)
                beta = math.atan(.5 * math.tan(wheel_angle)) if body_sideslip else 0.0
                yaw_rate = speed * math.cos(beta) / 3.4 * math.tan(wheel_angle)
                along = speed * math.cos(heading + beta) / max(0.3, 1 - offset * curvature)
                heading += (yaw_rate - along * curvature) * dt
                offset += speed * math.sin(heading + beta) * dt
                station = (station + along * dt) % length
                travelled += along * dt
                max_offset = max(max_offset, abs(offset))
                max_heading = max(max_heading, abs(heading))
                max_lateral_demand = max(max_lateral_demand, speed * abs(yaw_rate))
                offtrack = offtrack or offset > left or offset < -right
            if travelled >= length:
                break
        return {
            "track": track["id"], "assumed_speed_cap_mps": speed_cap,
            "kinematic_body_sideslip": body_sideslip,
            "assumed_driver_lateral_mps2": agent.DRY_LATERAL_ACCEL,
            "approx_one_lap_seconds": round((decision + 1) / 30, 3),
            "completed_one_synthetic_lap": travelled >= length,
            "max_abs_offset_m": round(max_offset, 4),
            "max_abs_heading_rad": round(max_heading, 4),
            "max_unlimited_lateral_demand_mps2": round(max_lateral_demand, 3),
            "crossed_public_road_edge": offtrack,
        }
    finally:
        agent.DRY_SPEED_CAP = old_cap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs="+", type=float,
                        default=[agent.DRY_SPEED_CAP])
    parser.add_argument("--body-sideslip", action='store_true',
                        help='Include normal kinematic body sideslip at a centered wheelbase; still no dynamic tyre model.')
    parser.add_argument('--downforce-coefficient', type=float, default=0.0)
    parser.add_argument('--tyre-temp', type=float, default=85.0)
    args = parser.parse_args()
    if any(v is not None and (not math.isfinite(v) or v <= 0) for v in args.compare):
        parser.error("speed caps must be finite positive values")
    if not math.isfinite(args.downforce_coefficient) or args.downforce_coefficient<0 or not math.isfinite(args.tyre_temp):
        parser.error('downforce coefficient must be finite/nonnegative and temperature finite')
    output = {
        "diagnostic_only": True,
        "limitation": "Invented force constants and unlimited-slip bicycle model; not race physics, qualifying, finish validation or performance evidence.",
        "assumptions": {"mass_kg": MASS_KG, "drive_force_n": DRIVE_FORCE_N,
                        "brake_force_n": BRAKE_FORCE_N,
                        "drag_coefficient": DRAG_COEFFICIENT,
                        "rolling_force_n": ROLLING_FORCE_N,
                        'downforce_coefficient': args.downforce_coefficient,
                        'constant_tyre_temp_c': args.tyre_temp},
        "results": [run(track, cap, body_sideslip=args.body_sideslip,
                        downforce_coefficient=args.downforce_coefficient,
                        tyre_temp=args.tyre_temp) for cap in args.compare
                    for track in track_data.TRACKS.values()],
    }
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
