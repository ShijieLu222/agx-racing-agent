"""Validate/replay a complete *own-seat* AGX racing training export.

No game state is advanced: both policies receive the same historical legal
observations. Output changes and target speeds are not new lap times or wins.

Example:
  python3 scripts/replay_check.py data/private/training.jsonl --seat 4 \
    --baseline-ref f9ba63540f21d39c1634fe7beb53a77948c3fd30 \
    --output experiments/replay-v2.json

The optional baseline loads agent.py from the given full commit SHA and requires
identical public geometry modules. The public aggregate report omits account names,
job/agent/version IDs, seed, raw observations, and the input file path.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark import validate


def load_policy(source, name):
    module = types.ModuleType(name)
    module.__file__ = name
    exec(compile(source, name, 'exec'), module.__dict__)
    return module


def baseline_source(commit):
    if not re.fullmatch(r'[0-9a-fA-F]{40}', commit):
        raise ValueError('--baseline-ref must be a full 40-character commit SHA')
    def read(name):
        return subprocess.check_output(['git', 'show', commit + ':' + name], cwd=ROOT)
    for name in ('track_data.py', 'track_parkland.py', 'track_highland.py', 'track_crossover.py'):
        if read(name) != (ROOT / name).read_bytes():
            raise ValueError('baseline geometry differs; use an isolated matching checkout')
    return read('agent.py')


def complete_rows(path):
    """Yield records while strictly validating the final original-byte checksum.

    Consumers must exhaust this iterator before accepting any report.
    """
    metadata = None
    outcome = False
    complete = False
    count, byte_count = 0, 0
    seats = collections.Counter()
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for line_number, raw in enumerate(source, 1):
            if not raw.strip():
                continue
            if complete:
                raise ValueError('data after export_complete at line ' + str(line_number))
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError('record must be an object')
            kind = record.get('type')
            if kind == 'metadata':
                if metadata is not None or count or outcome:
                    raise ValueError('metadata must occur exactly once at the beginning')
                if record.get('game_id') != 'racing':
                    raise ValueError('expected a racing export')
                if record.get('schema') != 'agent-tournament.training-export.v2':
                    raise ValueError('unsupported export schema')
                metadata = record
            elif 'observation' in record and 'seat' in record:
                if metadata is None or outcome:
                    raise ValueError('decision outside metadata/outcome boundaries')
                count += 1
                byte_count += len(raw)
                seats[str(record['seat'])] += 1
                digest.update(raw)
            elif kind == 'outcome':
                if metadata is None or outcome:
                    raise ValueError('unexpected outcome')
                outcome = True
            elif kind == 'export_complete':
                if not metadata or not outcome or record.get('complete') is not True:
                    raise ValueError('missing metadata/outcome or incomplete export')
                if (record.get('rows') != count or record.get('raw_bytes') != byte_count
                        or record.get('sha256') != digest.hexdigest()
                        or record.get('seat_calls') != dict(seats)):
                    raise ValueError('export_complete row/byte/hash/seat counts do not match')
                complete = True
            else:
                raise ValueError('unexpected record at line ' + str(line_number))
            yield record
    if not complete:
        raise ValueError('missing export_complete: log may be truncated')


def action_difference(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return left != right
    for key in set(left) | set(right):
        a, b = left.get(key), right.get(key)
        if type(a) in (int, float) and type(b) in (int, float):
            if abs(a - b) > 1e-9:
                return True
        elif a != b:
            return True
    return False


def probe_class(module):
    class Probe(module.Driver):
        def speed_plan(self, observation, rows, geometry, dt):
            target = super().speed_plan(observation, rows, geometry, dt)
            self.probe_target = target
            return target

        def traffic_plan(self, observation, rows, target, dt):
            result = super().traffic_plan(observation, rows, target, dt)
            self.probe_target = result[0]
            return result

        def fuel_saving(self, observation):
            # The old controller used a fixed speed cap while saving; v3 only
            # scales fuel demand when its measured consumption exceeds supply.
            saving = super().fuel_saving(observation)
            if saving and not hasattr(self, 'fuel_power_scale'):
                self.probe_target = min(self.probe_target, 38.0)
            return saving
    return Probe


class PolicyStats:
    def __init__(self, module, source):
        self.driver = probe_class(module)()
        self.source_sha256 = hashlib.sha256(source).hexdigest()
        self.calls = 0
        self.invalid = 0
        self.exceptions = 0
        self.changed_recorded = 0
        self.timings = []
        self.samples = []
        self.first_error_types = []
        self.mode_switches = collections.Counter()
        self.longitudinal_switches = collections.Counter()
        self.previous_longitudinal = None
        self.previous_phase = None
        self.previous_mode = None

    def call(self, observation, recorded):
        self.driver.probe_target = 0.0  # Neutral/finished/pit callbacks have no driving target.
        started = time.process_time_ns()
        try:
            action = self.driver.act(observation)
        except Exception as error:
            self.timings.append(time.process_time_ns() - started)
            self.calls += 1
            self.exceptions += 1
            if len(self.first_error_types) < 3:
                self.first_error_types.append(type(error).__name__)
            return None
        self.timings.append(time.process_time_ns() - started)
        self.calls += 1
        try:
            validate(action)
        except ValueError:
            self.invalid += 1
            return None
        self.changed_recorded += action_difference(action, recorded)
        phase = observation['phase']
        mode = action.get('ers_mode', 1)
        if self.previous_phase == phase and self.previous_mode != mode:
            self.mode_switches[phase] += 1
        longitudinal = ('brake' if action['brake'] > 1e-9 else
                        'throttle' if action['throttle'] > 1e-9 else 'coast')
        if (self.previous_phase == phase and
                {self.previous_longitudinal, longitudinal} == {'throttle', 'brake'}):
            self.longitudinal_switches[phase] += 1
        self.previous_phase, self.previous_mode = phase, mode
        self.previous_longitudinal = longitudinal
        car = observation['self']
        self.samples.append({
            'phase': phase, 'time': observation['time'],
            'wet': observation.get('weather', {}).get('track_wetness', 0),
            'observed_speed_mps': car['speed_mps'],
            'selected_target_mps': getattr(self.driver, 'probe_target', car['speed_mps']),
            'throttle': action['throttle'], 'brake': action['brake'],
            'braking': int(action['brake'] > 0),
            'grip_scale': getattr(self.driver, 'grip_scale', 1.0),
            'slip_exposure_s': getattr(self.driver, 'slip_exposure', 0.0),
            'sliding': int(bool(car.get('front_sliding') or car.get('rear_sliding'))),
            'pit_request': int(bool(action.get('pit_request'))),
            'throttle_and_brake': int(action['throttle'] > 0 and action['brake'] > 0),
        })
        return action

    def report(self):
        samples = self.samples
        for i, row in enumerate(samples):
            following = samples[i + 1] if i + 1 < len(samples) else None
            row['dt'] = (following['time'] - row['time'] if following and
                         following['phase'] == row['phase'] else 1 / 30)
            if row['dt'] <= 0:
                raise ValueError('observation times must increase within a phase')
        keys = ('observed_speed_mps', 'selected_target_mps', 'throttle', 'brake',
                'braking', 'grip_scale', 'slip_exposure_s', 'sliding')
        def summarize(rows):
            seconds = sum(r['dt'] for r in rows)
            if not rows:
                return {'calls': 0, 'duration_s': 0}
            return {'calls': len(rows), 'duration_s': seconds,
                    **{key: sum(r[key] * r['dt'] for r in rows) / seconds for key in keys},
                    'pit_request_calls': sum(r['pit_request'] for r in rows)}
        race = [r for r in samples if r['phase'] == 'race']
        times = sorted(self.timings)
        return {
            'agent_source_sha256': self.source_sha256,
            'calls': self.calls, 'exceptions': self.exceptions,
            'invalid_actions': self.invalid,
            'changed_actions_vs_recorded': self.changed_recorded,
            'cpu_act_seconds': sum(times) / 1e9,
            'cpu_act_p50_ms': statistics.median(times) / 1e6 if times else 0,
            'cpu_act_p99_ms': times[max(0, math.ceil(len(times) * .99) - 1)] / 1e6 if times else 0,
            'cpu_act_max_ms': max(times, default=0) / 1e6,
            'calls_above_200ms': sum(t > 200_000_000 for t in times),
            'action_ers_mode_switches': dict(self.mode_switches),
            'direct_throttle_brake_switches': dict(self.longitudinal_switches),
            'simultaneous_throttle_brake_calls': sum(r['throttle_and_brake'] for r in samples),
            'first_exception_types': self.first_error_types,
            'race': summarize(race),
            'race_wet_ge_0_9': summarize([r for r in race if r['wet'] >= .9]),
        }


def replay(path, seat=None, baseline=None):
    current_source = (ROOT / 'agent.py').read_bytes()
    current = PolicyStats(load_policy(current_source, 'replay_candidate'), current_source)
    previous = (PolicyStats(load_policy(baseline, 'replay_baseline'), baseline)
                if baseline is not None else None)
    selected = seat
    logged_faults = 0
    complete = None
    changed_vs_baseline = 0
    rules_version = None
    for record in complete_rows(path):
        if record.get('type') == 'metadata':
            participants = record.get('participants') or []
            seats = {p['seat'] for p in participants}
            if selected is None:
                if len(seats) != 1:
                    raise ValueError('multiple seats require --seat')
                selected = next(iter(seats))
            if selected not in seats:
                raise ValueError('selected seat is absent from the export')
            rules_version = record.get('rules_version')
        elif record.get('type') == 'export_complete':
            complete = record
        elif 'observation' in record and record['seat'] == selected:
            observation = record['observation']
            if observation.get('seat') != selected or observation.get('game_id') != 'racing':
                raise ValueError('observation identity mismatch')
            logged_faults += bool(record.get('fault'))
            result = current.call(observation, record['action'])
            if previous is not None:
                before = previous.call(observation, record['action'])
                if result is not None and before is not None:
                    changed_vs_baseline += action_difference(result, before)
    if current.calls == 0:
        raise ValueError('no decisions for selected seat')
    report = {
        'format': 'agx-racing-historical-observation-check.v1',
        'python_version': sys.version.split()[0],
        'rules_version': rules_version,
        'export_integrity': {'complete': True, 'rows': complete['rows'],
                             'raw_bytes': complete['raw_bytes'],
                             'decision_sha256': complete['sha256'],
                             'rows_bytes_sha256_seat_counts_verified': True},
        'recorded_faults_for_selected_seat': logged_faults,
        'candidate': current.report(),
        'limitation': 'Policies run on identical recorded legal observations; no physics is advanced. '
                      'Target/action changes are not new lap-time, ranking or collision results. '
                      'CPU includes lightweight target probes but excludes JSON, validation and platform overhead; '
                      'this does not prove the complete server CPU budget.',
    }
    if previous is not None:
        report['baseline'] = previous.report()
        report['candidate_changed_actions_vs_baseline'] = changed_vs_baseline
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--seat', type=int)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    baseline = baseline_source(args.baseline_ref) if args.baseline_ref else None
    report = replay(args.log, args.seat, baseline)
    if args.baseline_ref:
        report['baseline_commit'] = args.baseline_ref
    encoded = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end='')
    checks = [report['candidate']] + ([report['baseline']] if 'baseline' in report else [])
    return int(any(r['exceptions'] or r['invalid_actions'] for r in checks))


if __name__ == '__main__':
    raise SystemExit(main())
