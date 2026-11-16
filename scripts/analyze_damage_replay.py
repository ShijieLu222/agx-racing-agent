"""Offline incident analysis of public samples, never controller observations.

python3 scripts/analyze_damage_replay.py data/private/damage-2026-11-16
Optional --plot needs matplotlib; the racing agent has no new dependencies.
"""
import argparse
from bisect import bisect_right
import collections
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from track_data import SOURCE_HASHES, geometry_at
from analyze_race_comparison import checked


def analyze(root):
    descriptor = json.loads((root / 'descriptor.json').read_text())
    streams = {}
    for name in ('public_static', 'public_events'):
        spec = descriptor['streams'][name]
        raw = checked(root / (name + '.jsonl'), spec['sha256'])
        streams[name] = [json.loads(line) for line in raw.splitlines()]
        assert len(raw) == spec['raw_bytes'] and len(streams[name]) == spec['rows']
    meta = streams['public_static'][-1]['metadata']
    start = next(p['start_tick'] for p in meta['phases'] if p['phase'] == 'race')
    hz, length = descriptor['physics_hz'], meta['track']['length_m']
    geometry_hash = SOURCE_HASHES['crossover']['asset_sha256']
    center = json.loads(checked(root / 'crossover.json', geometry_hash))['centerline']
    stations = [p['s'] for p in center]

    def sample(row, car):
        i = bisect_right(stations, car['s']) - 1
        a, b = center[i], center[(i + 1) % len(center)]
        end = b['s'] if i + 1 < len(center) else length
        f = (car['s'] - a['s']) / (end - a['s'])
        cx, cy = (a[k] + f * (b[k] - a[k]) for k in ('x', 'y'))
        yaw = math.atan2(b['y'] - a['y'], b['x'] - a['x'])
        heading = (car['yaw'] - yaw + math.pi) % (2 * math.pi) - math.pi
        n = -(car['x'] - cx) * math.sin(yaw) + (car['y'] - cy) * math.cos(yaw)
        return dict(race_time_s=(row['tick'] - start) / hz, tick=row['tick'],
                    lap=car['lap'] + 1, s=car['s'], status=car['status'],
                    speed_kmh=car['speed_mps'] * 3.6, heading_deg=math.degrees(heading),
                    n_m=n, brake=car['brake'], throttle=car['throttle'],
                    steer_rad=car['steer'], compound=car['compound'],
                    max_tyre_temp_c=max(car['tyre_temp_c']),
                    max_tyre_wear=max(car['tyre_wear']), fuel_kg=car['fuel_kg'],
                    position=car['position'], road_widths_m=geometry_at(length, car['s'])[2:])

    chunks = sorted((int(p.stem.split('-')[1]), p) for p in root.glob('frames-*.bin'))
    indices = [i for i, _ in chunks]
    expected = descriptor['static']['streams']['public_frames']
    assert indices and indices == list(range(indices[0], len(expected)))
    own, corners, others, first, previous, count = [], collections.defaultdict(list), {}, None, None, 0
    nearest = float('inf')
    wetness = set()

    def consume(row):
        nonlocal first, previous, count, nearest
        if row['phase'] != 'race':
            return
        tick = row['tick']
        if previous is None:
            assert 0 <= tick - start <= 2
            first = tick
        else:
            assert 0 < tick - previous <= 3
        previous, count = tick, count + 1
        if 'weather' in row:
            wetness.add(row['weather'].get('track_wetness'))
        cars = {c['seat']: c for c in row['cars']}
        c = cars[8]
        t = (tick - start) / hz
        if not own or c['status'] == 'racing' or own[-1]['status'] == 'racing':
            own.append(sample(row, c))
        if 464 <= t <= 467.28334:
            distances = [math.sqrt(sum((c[k] - other[k]) ** 2 for k in ('x', 'y', 'z')))
                         for other in row['cars'] if other['seat'] != 8 and other['status'] == 'racing']
            nearest = min(nearest, *distances)
        for seat in (8, 1):
            c = cars[seat]
            if c['status'] == 'racing' and 3580 <= c['s'] <= 3700:
                corners[f'{seat}:{c["lap"] + 1}'].append(sample(row, c))
        for seat in (2, 3):
            if seat not in others or cars[seat]['status'] == 'racing' or others[seat]['status'] == 'racing':
                others[seat] = sample(row, cars[seat])

    tail = b''
    for index, path in chunks:
        lines = (tail + checked(path, expected[index])).split(b'\n')
        tail = lines.pop()
        if index == indices[0] and index > 0:
            lines = lines[1:]
        for line in lines:
            consume(json.loads(line))
    if tail.strip():
        consume(json.loads(tail))
    assert previous == descriptor['steps']
    event = next(e for e in streams['public_events'] if e['kind'] == 'retired' and 8 in e['seats'])
    report = dict(match_id=descriptor['job_id'], track=meta['track']['id'],
                  race_start_tick=start, physics_hz=hz, public_frame_hz=descriptor['frame_hz'],
                  verified_chunk_indices=indices, verified_race_frames=count,
                  geometry_sha256=geometry_hash, retirement_event=event,
                  retirement_race_time_s=(event['tick']-start)/hz,
                  initial=own[0], last_running_sample=own[-2], first_retired_sample=own[-1],
                  fuel_consumed_kg=own[0]['fuel_kg']-own[-1]['fuel_kg'],
                  minimum_active_opponent_distance_m_last_3s=nearest,
                  sampled_wetness_values=list(wetness),
                  corner_3640m={k: min(v, key=lambda c: abs(c['s']-3640)) for k, v in corners.items()},
                  incident_samples=[c for c in own if c['race_time_s'] >= 464],
                  own_events=[e for e in streams['public_events'] if e['phase']=='race' and 8 in e['seats'] and e['kind']!='energy_mode'],
                  event_kind_counts=dict(collections.Counter(e['kind'] for e in streams['public_events'])),
                  other_retirements=others,
                  limitations=['Position/heading relative to road derived from rounded 24 Hz public frames and map centerline.',
                               'No private damage counter, power-unit temperature, controller target or actual observation available.',
                               'Exact damage mechanism and individual causal contributions are not observable.',
                               'Public frame chunks cover complete race, not complete qualifying; every selected chunk is SHA256 checked.'])
    return report, corners


def plot(report, corners, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 10), layout='constrained')
    colors = ['#94a3b8', '#64748b', '#169d8f', '#dc3545']
    for lap, color in enumerate(colors, 1):
        points = corners[f'8:{lap}']
        axes[0].plot([p['s'] for p in points], [p['speed_kmh'] for p in points],
                     label=f'Your lap {lap} / {points[0]["compound"]}', color=color, lw=2)
    axes[0].axvline(3640, color='#999', ls=':', lw=1)
    axes[0].set(xlabel='Distance around lap (m)', ylabel='Speed (km/h)', xlim=(3580,3700),
                title='Same corner, four passes: lap 4 loses stability')
    axes[0].legend(ncol=2, fontsize=9)
    p = [p for p in report['incident_samples'] if p['status']=='racing']
    ts = [v['race_time_s'] for v in p]
    axes[1].plot(ts, [v['heading_deg'] for v in p], color='#dc3545', lw=2, label='Heading relative to road')
    axes[1].set(ylabel='Heading error (degrees)', title='Car rotates before the brief 100% brake command')
    axes[2].plot(ts, [100*v['brake'] for v in p], color='#334155', lw=2, label='Brake (%)')
    axes[2].plot(ts, [100*v['steer_rad']/.3 for v in p], color='#169d8f', lw=2,
                 label='Steering (% of mechanical range; negative = countersteer here)')
    axes[2].set(xlabel='Seconds since race start', ylabel='Control (%)', ylim=(-110,110))
    for ax in axes[1:]:
        ax.axvline(report['retirement_race_time_s'], color='#dc3545', ls='--', lw=1)
        ax.set_xlim(464,467.4)
        ax.legend(fontsize=8, loc='upper left')
    for ax in axes:
        ax.grid(alpha=.2)
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('AGX Crossover | car #9 | 16 Nov 2026', fontsize=16, weight='bold')
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    fig.savefig(path.with_suffix('.svg'))
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path, default=Path('experiments/damage-analysis-2026-11-16.json'))
    parser.add_argument('--plot', type=Path)
    args = parser.parse_args()
    report, corners = analyze(args.directory)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    if args.plot:
        plot(report, corners, args.plot)
    print(json.dumps({k:v for k,v in report.items() if k not in ('incident_samples','verified_chunk_indices','own_events')}, ensure_ascii=False))
