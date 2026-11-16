"""Compare complete public race windows; never turn replay frames into observations.

Usage: python3 scripts/analyze_race_comparison.py DIRECTORY --seat 9 --output report.json
DIRECTORY contains descriptor.json, public_static.jsonl, public_events.jsonl,
and a contiguous suffix of frames-N.bin chunks. All inputs are hash checked.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def checked(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('SHA256 mismatch: ' + str(path))
    return raw


def analyze(root, own):
    descriptor = json.loads((root / 'descriptor.json').read_text())
    streams = {}
    for name in ('public_static', 'public_events'):
        spec = descriptor['streams'][name]
        raw = checked(root / (name + '.jsonl'), spec['sha256'])
        streams[name] = [json.loads(line) for line in raw.splitlines()]
        if len(raw) != spec['raw_bytes'] or len(streams[name]) != spec['rows']:
            raise ValueError('Incomplete stream: ' + name)
    meta = streams['public_static'][-1]['metadata']
    start = next(p['start_tick'] for p in meta['phases'] if p['phase'] == 'race')
    chunks = sorted((int(p.stem.split('-')[1]), p) for p in root.glob('frames-*.bin'))
    indices = [i for i, _ in chunks]
    expected = descriptor['static']['streams']['public_frames']
    if not indices or indices != list(range(indices[0], len(expected))):
        raise ValueError('Require contiguous chunks through the final frame')
    frames = []
    tail = b''
    for index, path in chunks:
        raw = checked(path, expected[index])
        lines = (tail + raw).split(b'\n')
        tail = lines.pop()
        if index == indices[0] and index > 0:
            lines = lines[1:]  # First fragment may start halfway through a record.
        for line in lines:
            row = json.loads(line)
            if row['phase'] == 'race':
                frames.append(row)
    if tail.strip():
        row = json.loads(tail)
        if row['phase'] == 'race':
            frames.append(row)
    # Public sampling is 24 Hz on a 60 Hz simulation; phase boundaries may add
    # a frame, but no interval may be longer than three physics ticks.
    if not 0 <= frames[0]['tick'] - start <= 2 or frames[-1]['tick'] != descriptor['steps']:
        raise ValueError('Missing sampled race start or exact end')
    if any(not 0 < b['tick'] - a['tick'] <= 3 for a, b in zip(frames, frames[1:])):
        raise ValueError('Missing/duplicate race frames')
    winner = next(c['seat'] for c in descriptor['result']['classification'] if c['position'] == 1)
    length = meta['track']['length_m']
    result = {'match_id': descriptor['job_id'], 'track': meta['track']['id'],
              'race_start_tick': start, 'first_sample_tick': frames[0]['tick'], 'race_frames': len(frames),
              'verified_chunk_indices': indices, 'cars': [],
              'limitations': 'Public 24 Hz samples, not private controller observations. '
              'Time fractions use left-held samples; lap/sector crossing times are interpolated. '
              'No claim that changed actions produce these historical trajectories.'}
    podium = [c['seat'] for c in sorted(descriptor['result']['classification'], key=lambda c:c['position']) if c['position'] <= 3]
    for seat in dict.fromkeys((own, winner, *podium)):
        samples = [(r['time'], next(c for c in r['cars'] if c['seat'] == seat)) for r in frames]
        active = [(t, c) for t, c in samples if c['status'] == 'racing']
        crossings = {0: start / descriptor['physics_hz']}
        sectors = {0: start / descriptor['physics_hz']}
        totals = collections.defaultdict(float)
        ontrack = collections.defaultdict(float)
        bins = [collections.defaultdict(float) for _ in range(20)]
        slow_spells = []
        slow_start = None
        for (t, c), (nt, nc) in zip(samples, samples[1:]):
            if c['status'] != 'racing':
                continue
            dt = nt - t
            totals['active_seconds'] += dt
            for key, value in [('throttle', c['throttle']), ('brake', c['brake']),
                               ('braking', c['brake'] > .05), ('full_throttle', c['throttle'] > .95),
                               ('coasting', c['throttle'] < .01 and c['brake'] < .01),
                               ('empty_battery', c['ers_soc_mj'] < .02),
                               ('attack', c['ers_mode'] == 3), ('aero_x', c['aero_mode'] == 1),
                               ('aid_available', c['aid_available']), ('aid_active', c['aid_active'])]:
                totals[key] += dt * value
                if not c.get('pit_state', 0):
                    ontrack[key] += dt * value
            if not c.get('pit_state', 0):
                ontrack['seconds'] += dt
                bucket = bins[min(19, max(0, int(c['s'] / length * 20)))]
                bucket['seconds'] += dt
                bucket['speed_integral'] += dt * c['speed_mps'] * 3.6
                bucket['below_1mps_seconds'] += dt * (c['speed_mps'] < 1)
                if c['speed_mps'] < 1:
                    if slow_start is None:
                        slow_start = (t, c['s'], c['lap'])
                elif slow_start is not None:
                    if t - slow_start[0] > 2:
                        slow_spells.append({'race_start_s': slow_start[0] - start / descriptor['physics_hz'],
                                            'duration_s': t - slow_start[0], 'station_m':slow_start[1], 'lap':slow_start[2]+1})
                    slow_start = None
            else:
                slow_start = None
            d0, d1 = c['lap'] * length + c['s'], nc['lap'] * length + nc['s']
            if d1 > d0:
                for k in range(int(d0 // length) + 1, int(d1 // length) + 1):
                    crossings[k] = t + dt * (k * length - d0) / (d1 - d0)
                # 20 equally spaced sectors per lap, independent of speed.
                for k in range(int(d0 // (length / 20)) + 1, int(d1 // (length / 20)) + 1):
                    sectors[k] = t + dt * (k * length / 20 - d0) / (d1 - d0)
        events = [e for e in streams['public_events'] if e['phase'] == 'race' and seat in e['seats']]
        classification = next(c for c in descriptor['result']['classification'] if c['seat'] == seat)
        result['cars'].append({
            'seat': seat, 'role': 'own' if seat == own else ('winner' if seat == winner else 'runner_up'), 'classification': classification,
            'design': next(c['design_summary'] for c in meta['cars'] if c['seat'] == seat),
            'laps_seconds': [crossings[k] - crossings[k-1] for k in sorted(crossings) if k > 0 and k-1 in crossings],
            'sector_times': {str(k): v - sectors[k-1] for k, v in sectors.items() if k-1 in sectors},
            'time_weighted': {k: v / totals['active_seconds'] for k, v in totals.items() if k != 'active_seconds'},
            'time_weighted_ontrack': {k:v/ontrack['seconds'] for k,v in ontrack.items() if k!='seconds'},
            'ontrack_distance_bins': [{'start_m':i*length/20,'end_m':(i+1)*length/20,
                                       'seconds':b['seconds'], 'below_1mps_seconds':b['below_1mps_seconds'],
                                       'mean_speed_kmh':b['speed_integral']/b['seconds'] if b['seconds'] else None} for i,b in enumerate(bins)],
            'slow_spells':slow_spells,
            'last_lap_station_samples': {str(s):{k:c[k] for k in ('s','speed_mps','throttle','brake','ers_soc_mj','tyre_temp_c') if k in c}
                                        for s in (235,245,6585,6600,6650,6675)
                                        for c in [min((c for _,c in active if c['lap']==3),key=lambda c:abs(c['s']-s),default={})]},
            'fuel_used_kg': samples[0][1]['fuel_kg'] - samples[-1][1]['fuel_kg'],
            'fuel_remaining_kg': samples[-1][1]['fuel_kg'],
            'speed_max_kmh': max(c['speed_mps'] for _, c in active) * 3.6,
            'energy_mode_events': dict(collections.Counter(e['payload']['ers_mode'] for e in events if e['kind'] == 'energy_mode')),
            'incidents_and_pits': [e for e in events if e['kind'] in ('incident', 'pit_entry', 'pit_exit')],
        })
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--seat', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.directory, args.seat)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    for car in report['cars']:
        print(json.dumps({k: v for k, v in car.items() if k != 'sector_times'}, ensure_ascii=False))
