"""Stress legal action output and local CPU on synthetic racing observations.

Usage: python3 scripts/benchmark.py --calls 30000
The field shapes come from the official observation fixture and road geometry
from the public track data. Scripted states are not physical transitions: this
does not simulate a race, predict finishing time or prove the 55 CPU-s budget.
Observation construction, validation and JSON transport are outside act timing.
"""
import argparse
from bisect import bisect_right
import copy
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import agent
from track_data import TRACKS


ALLOWED = {"throttle", "brake", "steer", "ers_mode", "aero_mode",
           "override", "aid", "pit_request", "pit_compound"}


def validate(action):
    if not isinstance(action, dict) or set(action) - ALLOWED:
        raise ValueError("action must be an object with only documented fields")
    for name, lower, upper in (("throttle", 0, 1), ("brake", 0, 1),
                               ("steer", -1, 1)):
        value = action.get(name)
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not lower <= value <= upper):
            raise ValueError("invalid required control: " + name)
    for name, allowed in (("ers_mode", range(4)), ("aero_mode", range(2))):
        if name in action and (type(action[name]) is not int
                               or action[name] not in allowed):
            raise ValueError("invalid integer mode: " + name)
    for name in ("override", "aid", "pit_request"):
        if name in action and type(action[name]) is not bool:
            raise ValueError("invalid boolean: " + name)
    if action.get("pit_compound") not in (None, "soft", "medium", "hard"):
        raise ValueError("invalid tyre key")


class PublicGeometry:
    """Independent interpolation for synthetic observation construction."""
    def __init__(self, track):
        self.track = track
        self.rows = track["rows"]
        self.stations = [r[0] for r in self.rows]
        self.length = track["length"]

    def at(self, station):
        station %= self.length
        left = bisect_right(self.stations, station) - 1
        left = max(0, left)
        right = (left + 1) % len(self.rows)
        a, b = self.rows[left], self.rows[right]
        end = b[0] if right else self.length + b[0]
        ratio = (station - a[0]) / max(1e-9, end - a[0])
        return [a[j] + ratio * (b[j] - a[j]) for j in range(1, 5)]

    def in_aero(self, station):
        station %= self.length
        for start, end in self.track.get("aero_zones", ()):
            if start <= end and start <= station < end:
                return 1
            if start > end and (station >= start or station < end):
                return 1
        return 0


def make_observation(base, geo, wet, index, count):
    """Sweep geometry and legal status combinations, not an engine model."""
    row = copy.deepcopy(base)
    fraction = index / max(1, count - 1)
    qualifying = fraction < 0.08
    race_fraction = max(0.0, (fraction - 0.08) / 0.92)
    progress = (fraction if qualifying else race_fraction * 3.99) * geo.length
    station = progress % geo.length
    phase_tick = index * 2 if qualifying else max(0, index - int(count * .08)) * 2
    row.update(phase="qualifying" if qualifying else "race",
               laps_total=1 if qualifying else 4, track_length_m=geo.length,
               tick=index * 2, phase_tick=phase_tick, time=index / 30,
               decision=index, hold_ticks=2)
    car = row["self"]
    speed = 20 + 30 * (0.5 + 0.5 * math.sin(index * .017))
    pit_fraction = (race_fraction - .47) / .035
    pit_state = min(3, 1 + int(pit_fraction * 3)) if 0 <= pit_fraction < 1 else 0
    after_stop = race_fraction >= .505
    stops = int(after_stop and not qualifying)
    compound = "medium" if after_stop else "soft"
    wear = (race_fraction - .505) * .95 if after_stop else race_fraction * 1.5
    curvature = geo.at(station)[0]
    car.update(s=station, distance=progress, lap=int(progress / geo.length),
               speed_mps=speed if not pit_state else 12.0,
               vx=speed if not pit_state else 12.0, vy=.2 * math.sin(index * .05),
               n=.35 * math.sin(index * .023), heading_error=.025 * math.sin(index * .031),
               yaw_rate=speed * curvature, steer=math.atan(3.4 * curvature),
               pit_state=pit_state, pit_stops=stops, compound=compound,
               tyre_wear=[max(0, min(.95, wear))] * 4,
               tyre_temp_c=[85 + 25 * race_fraction] * 4,
               fuel_kg=max(4, 60 - 51 * race_fraction),
               ers_soc_mj=.4 + 3.2 * (.5 + .5 * math.sin(index * .01)),
               front_sliding=index % 800 in range(620, 625),
               rear_sliding=index % 900 in range(710, 715),
               aid_available=not qualifying and wet < .5 and not pit_state,
               override_available=not qualifying and wet < .5 and not pit_state,
               status="racing", effective_mass_kg=900.0,
               drag_n=1200.0, downforce_n=2500.0,
               rolling_resistance_n=110.0, drive_force_n=[3500, 6000, 8500, 11000],
               brake_force_max_n=40000.0)
    if index == count - 2:
        car["status"] = "finished"
    elif index == count - 1:
        car["status"] = "retired"
    row["weather"].update(track_wetness=wet,
                          condition="wet" if wet >= .5 else "damp" if wet > .05 else "dry",
                          rain_intensity=.6 if wet >= .5 else 0.0)
    row["tyres"]["allocation"] = {
        "parkland": {"hard": "C3", "medium": "C4", "soft": "C5"},
        "highland": {"hard": "C2", "medium": "C3", "soft": "C4"},
        "crossover": {"hard": "C1", "medium": "C2", "soft": "C3"},
    }[geo.track["id"]]
    row["preview"]["rows"] = []
    for i in range(1, 25):
        distance = 15.0 * i
        geometry = geo.at(station + distance)
        row["preview"]["rows"].append([distance, *geometry, geo.in_aero(station + distance)])
    # Traffic deliberately changes: output legality, not collision proof.
    row["rivals"] = [] if qualifying else [
        {"seat": 1, "gap_m": 9 + 38 * (.5 + .5 * math.sin(index * .02)),
         "dn": .1, "speed_mps": 25.0, "lap": car["lap"], "status": "racing"},
        {"seat": 2, "gap_m": -8.0, "dn": -3.3,
         "speed_mps": 31.0, "lap": car["lap"], "status": "racing"},
        {"seat": 3, "gap_m": 28.0, "dn": 3.2,
         "speed_mps": 30.0, "lap": car["lap"], "status": "racing"},
    ]
    return row


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=30000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.calls < 90:
        parser.error("at least 90 calls are needed for the nine scenario segments")
    base = json.loads((ROOT / "tests/fixtures/official_observation.json").read_text())
    from pack import FILES
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in FILES}
    scenarios = [(track, wet) for track in TRACKS.values() for wet in (0.0, .3, .8)]
    timings, errors, summaries = [], [], []
    init_cpu_ns = 0
    wall_start = time.perf_counter()
    for scenario_index, (track, wet) in enumerate(scenarios):
        count = args.calls // len(scenarios) + int(scenario_index < args.calls % len(scenarios))
        geo = PublicGeometry(track)
        started = time.process_time_ns()
        agent.init({"seat": 0, "role": "driver", "seed": 0,
                    "contract_id": "rsi-racing-4.4", "weights_dir": str(ROOT)})
        init_cpu_ns += time.process_time_ns() - started
        local_times = []
        requests = {"pit": 0, "aero_x": 0, "aid": 0, "brake": 0}
        for i in range(count):
            row = make_observation(base, geo, wet, i, count)
            started = time.process_time_ns()
            try:
                action = agent.act(row)
            except Exception as error:
                elapsed = time.process_time_ns() - started
                errors.append({"track": track["id"], "wetness": wet, "index": i,
                               "error": repr(error)})
                local_times.append(elapsed)
                continue
            local_times.append(time.process_time_ns() - started)
            try:
                validate(action)
            except ValueError as error:
                errors.append({"track": track["id"], "wetness": wet, "index": i,
                               "error": str(error)})
                continue
            requests["pit"] += bool(action.get("pit_request"))
            requests["aero_x"] += action.get("aero_mode") == 1
            requests["aid"] += bool(action.get("aid") or action.get("override"))
            requests["brake"] += action["brake"] > 0
        timings.extend(local_times)
        summaries.append({"track": track["id"], "wetness": wet, "calls": count,
                          "cpu_ms": sum(local_times) / 1e6, "requests": requests})
    result = {
        "python_version": sys.version.split()[0], "source_sha256": source_hashes,
        "calls": len(timings), "scenario_segments": summaries,
        "init_cpu_ms": init_cpu_ns / 1e6, "act_cpu_seconds": sum(timings) / 1e9,
        "act_p50_ms": statistics.median(timings) / 1e6,
        "act_p99_ms": percentile(timings, .99) / 1e6,
        "act_max_ms": max(timings) / 1e6,
        "act_calls_above_200ms": sum(t > 200_000_000 for t in timings),
        "invalid_or_exception_count": len(errors), "first_errors": errors[:5],
        "harness_elapsed_seconds": time.perf_counter() - wall_start,
        "limitation": "Synthetic scripted field combinations, not a physical race. "
                      "Act CPU excludes observation generation, validation, JSON and platform overhead. "
                      "No lap-time, ranking, collision or total-match CPU compliance claim.",
    }
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
