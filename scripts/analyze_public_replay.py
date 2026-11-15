"""Audit an AGX public replay. Public frames are never legal agent observations.

Provide downloaded descriptor/static/events and selected raw frame chunks:
  python3 scripts/analyze_public_replay.py --descriptor descriptor.json \
    --static static.jsonl --events events.jsonl --chunk 235=235.bin \
    --chunk 342=342.bin --output summary.json
Every input stream/chunk is checked against the descriptor before use. Event
mode counts are transitions, not mode duration. Sampled frames are explicitly
labelled; their means must not be reported as whole-race averages.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import statistics


def checked(path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected['sha256']:
        raise ValueError('Public artifact SHA256 mismatch: ' + str(path))
    if 'raw_bytes' in expected and len(raw) != expected['raw_bytes']:
        raise ValueError('Public artifact byte count mismatch')
    return raw


def analyze(descriptor, static_path, events_path, chunks):
    streams = descriptor['streams']
    static = [json.loads(line) for line in checked(static_path, streams['public_static']).splitlines()]
    events = [json.loads(line) for line in checked(events_path, streams['public_events']).splitlines()]
    if len(static) != streams['public_static']['rows'] or len(events) != streams['public_events']['rows']:
        raise ValueError('Public stream row count mismatch')
    initial = static[0]['metadata']
    terminal = static[-1]['metadata']
    race_start_tick = next(p['start_tick'] for p in terminal['phases'] if p['phase'] == 'race')
    frames, sources = {}, []
    for index, path in chunks:
        expected = descriptor['static']['streams']['public_frames'][index]
        raw = checked(path, {'sha256': expected})
        sources.append({'index': index, 'sha256': expected})
        # Chunks are raw byte fragments, so their first/last JSON line may be
        # incomplete. Retain only complete records; never join unrelated chunks.
        for line in raw.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and 'cars' in row and 'tick' in row:
                frames[row['tick']] = row
    race = sorted((r for r in frames.values() if r['phase'] == 'race'), key=lambda r: r['tick'])
    if not race or race[0]['tick'] != race_start_tick:
        raise ValueError('Include a verified chunk containing the exact race start')
    if race[-1]['tick'] != descriptor['steps']:
        raise ValueError('Include the verified terminal frame chunk')
    starts = {c['seat']: c for c in race[0]['cars']}
    ends = {c['seat']: c for c in race[-1]['cars']}
    cars = []
    for result in descriptor['result']['classification']:
        seat = result['seat']
        active = [c for r in race for c in r['cars'] if c['seat'] == seat and c['status'] == 'racing']
        modes = collections.Counter(e['payload']['ers_mode'] for e in events
                                    if e['phase'] == 'race' and e['kind'] == 'energy_mode' and seat in e['seats'])
        fuel = starts[seat]['fuel_kg']
        remaining = ends[seat]['fuel_kg']
        cars.append({
            'car_number': seat + 1, **{k: result[k] for k in ('position', 'status', 'laps', 'total_time_s', 'fastest_lap', 'pit_stops')},
            'starting_fuel_kg': fuel, 'ending_fuel_kg': remaining,
            'race_fuel_used_kg': round(fuel - remaining, 4),
            'race_energy_mode_event_counts': dict(modes),
            'sampled_active_race_frames': len(active),
            'sampled_mean_throttle': statistics.mean(c['throttle'] for c in active) if active else None,
            'sampled_speed_max_mps': max((c['speed_mps'] for c in active), default=None),
        })
    return {
        'format': 'agx-public-replay-audit.v1', 'match_id': descriptor['job_id'],
        'result_reason': descriptor['result']['reason'], 'rules_version': descriptor['rules_version'],
        'track': initial['track']['id'], 'race_start_time_s': race_start_tick / 60,
        'race_end_time_s': race[-1]['time'], 'verified_public_events': len(events),
        'verified_frame_chunks': sorted(sources, key=lambda s: s['index']),
        'sampled_race_frames': len(race), 'cars': cars,
        'qualifying_events': [e for e in events if e['kind'] == 'qualifying_lap'],
        'weather_events': [e for e in events if e['kind'] == 'weather_change'],
        'own_car_incidents': [e for e in events if e['kind'] == 'incident' and 3 in e['seats']],
        'limitations': 'Verified complete events/static and selected frame chunks only. '
                       'Sampled throttle/speed statistics are not whole-race statistics. '
                       'Other participants source code and private decisions are unavailable. '
                       'Historical public frames are fixed inputs, not a simulation '
                       'of any new controller or evidence of its future performance.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', required=True, type=Path)
    parser.add_argument('--static', required=True, type=Path)
    parser.add_argument('--events', required=True, type=Path)
    parser.add_argument('--chunk', action='append', default=[])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    chunks = [(int(value.split('=', 1)[0]), Path(value.split('=', 1)[1])) for value in args.chunk]
    report = analyze(json.loads(args.descriptor.read_text()), args.static, args.events, chunks)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print('Verified audit written to', args.output)


if __name__ == '__main__':
    main()
