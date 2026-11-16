"""Compare fuel, route targets and passing on complete historical own inputs.

No physics advances; target gains and passing requests are not measured time gains.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay_check import baseline_source, complete_rows, load_policy


def probe(module):
    class Probe(module.Driver):
        def speed_plan(self, o, rows, geometry, dt):
            value = super().speed_plan(o, rows, geometry, dt)
            self.route_target = value
            return value
    return Probe()


def run(log, baseline):
    sources = [baseline_source(baseline), (ROOT/'agent.py').read_bytes()]
    modules = [load_policy(source, 'diagnostic_' + str(i)) for i, source in enumerate(sources)]
    drivers = [probe(m) for m in modules]
    stats = [dict(source_sha256=hashlib.sha256(s).hexdigest(), saving_calls=0,
                  risk_calls=0, ontrack_calls=0, first_slow_car_pass=None,
                  first_incident_response=None, samples={}) for s in sources]
    count = 0
    for record in complete_rows(log):
        if 'observation' not in record:
            continue
        count += 1
        o = record['observation']; c = o['self']
        actions = [d.act(o) for d in drivers]
        if o['phase'] != 'race' or c.get('pit_state') or c['status'] != 'racing':
            continue
        for m, d, action, st in zip(modules, drivers, actions, stats):
            g = d.current_geometry(o, m.preview_rows(o))
            risk, _, _ = m.stability_state(c, g)
            t = o['phase_tick']/60
            st['ontrack_calls'] += 1
            st['saving_calls'] += d.fuel_power_scale < 1
            st['risk_calls'] += risk > 0
            sample = dict(time_s=t, lap=c['lap']+1, station_m=c['s'],
                          observed_speed_kmh=c['speed_mps']*3.6,
                          route_target_kmh=d.route_target*3.6,
                          throttle=action['throttle'], brake=action['brake'],
                          fuel_scale=d.fuel_power_scale, risk=risk,
                          passing_seat=d.pass_seat, lane_target_m=d.lane)
            if c['lap'] == 0:
                for station in (104, 700, 1600, 2000):
                    old = st['samples'].get(str(station))
                    if old is None or abs(c['s']-station) < abs(old['station_m']-station):
                        st['samples'][str(station)] = sample
            if c['lap'] == 3 and 430 < t < 455 and d.pass_seat == 5 and st['first_slow_car_pass'] is None:
                st['first_slow_car_pass'] = sample
            if c['lap'] == 3 and 463.5 <= t <= 467.3 and risk > 0 and st['first_incident_response'] is None:
                st['first_incident_response'] = sample
    return dict(complete_export_verified=True, ordered_decisions=count, baseline_commit=baseline,
                baseline=stats[0], candidate=stats[1],
                limitation='Fixed historical own legal inputs; no changed motion, lap time, overtaking success or crash rescue is demonstrated.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=Path)
    p.add_argument('--baseline-ref', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = run(a.log, a.baseline_ref)
    a.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(result, indent=2))
