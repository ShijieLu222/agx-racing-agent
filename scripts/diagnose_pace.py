"""Diagnose a complete own-seat export without advancing historical physics."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay_check import complete_rows, load_policy, action_difference


def diagnose(log, source):
    module = load_policy(source, 'pace_policy')
    class Probe(module.Driver):
        def speed_plan(self, o, rows, geometry, dt):
            self.route = super().speed_plan(o, rows, geometry, dt)
            return self.route
        def traffic_plan(self, o, rows, target, dt):
            result = super().traffic_plan(o, rows, target, dt)
            self.traffic = result[0]
            return result
    driver = Probe()
    groups = collections.defaultdict(collections.Counter)
    samples = {}
    changed = calls = 0
    for record in complete_rows(log):
        if 'observation' not in record:
            continue
        o = record['observation']; c = o['self']
        a = driver.act(o)
        calls += 1
        changed += action_difference(a, record.get('action'))
        if c.get('pit_state') or c.get('status') != 'racing':
            continue
        geometry = driver.current_geometry(o, module.preview_rows(o))
        risk, beta, yaw_error = module.stability_state(c, geometry)
        speed = c['speed_mps']
        temps = c['tyre_temp_c']
        load = max(abs(c.get('g_lat',0))*9.81, speed*abs(c['yaw_rate']))
        mu = module.tyre_mu(o)
        wet = o.get('weather',{}).get('track_wetness',0)
        uncalibrated = module.tyre_mu({**o, 'weather': {'track_wetness': .3}}) / .91 * (1-.3*wet)
        grip = mu*(9.81+c['downforce_n']/c['effective_mass_kg'])
        bucket = int(c['s']//250)*250
        keys = [o['phase'], f"{o['phase']}:lap{c['lap']+1}"]
        if o['phase']=='race': keys.append(f'bin:{bucket}')
        values = dict(calls=1, speed_kmh=speed*3.6, route_kmh=driver.route*3.6,
                      traffic_kmh=driver.traffic*3.6, throttle=a['throttle'],brake=a['brake'],
                      risk=risk>0, risk_value=risk, traffic_limited=driver.traffic<driver.route-.1,
                      saving=driver.fuel_power_scale<1,mu=mu,min_temp=min(temps),
                      full=a['throttle']>.95,braking=a['brake']>.05,
                      grip_saturated=load>=grip,empty=c['ers_soc_mj']<.02,
                      soc=c['ers_soc_mj'],battery_power=c.get('ers_power_kw',0),
                      wet=o.get('weather',{}).get('track_wetness',0),
                      heading=abs(c['heading_error']),beta=abs(beta),load_fraction=load/max(grip,1),
                      dry_calibration=mu/uncalibrated)
        for key in keys: groups[key].update(values)
        if o['phase']=='race' and c['lap']==3:
            for station in range(0,5800,100):
                old=samples.get(station)
                if old is None or abs(c['s']-station)<abs(old['s']-station):
                    samples[station]=dict(s=c['s'],time=o['time'],**values,curve=geometry[0],
                                         target_error=driver.traffic-speed,temps=temps,
                                         yaw_error=yaw_error,drive=c['drive_force_n'],
                                         action=a,n=c['n'],downforce=c['downforce_n'],
                                         tyres=c.get('compound'),wear=c.get('tyre_wear'))
    return dict(calls=calls,changed_recorded=changed,source_sha256=hashlib.sha256(source).hexdigest(),
                complete_export_verified=True,
                groups={k:{q:(v if q=='calls' else v/c['calls']) for q,v in c.items()} for k,c in groups.items()},
                final_lap_samples=samples,
                limitation='Fixed historical legal observations; changed targets/actions are not achieved speeds or lap times.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log',type=Path)
    p.add_argument('--source',type=Path,default=ROOT/'agent.py')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=diagnose(a.log,a.source.read_bytes())
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='final_lap_samples'},indent=2))
