"""Compare v7 outputs with recorded own actions, with full ordered warm-up.

No simulated motion or new lap time is produced. Original private observations
remain outside the report. Usage: python3 scripts/check_stability_replay.py LOG
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from benchmark import validate
from replay_check import complete_rows


def run(path):
    driver = agent.Driver()
    samples, corners, first_slide = [], {}, {}
    count = 0
    for row in complete_rows(path):
        if 'observation' not in row:
            continue
        observation = row['observation']
        if row['seat'] != 8 or observation['seat'] != 8:
            raise ValueError('Expected only the authorized incident seat 8')
        action = driver.act(observation)
        validate(action)
        count += 1
        if observation['phase'] != 'race':
            continue
        c = observation['self']
        t = observation['phase_tick'] / 60
        geometry = driver.current_geometry(observation, agent.preview_rows(observation))
        risk, beta, yaw_error = agent.stability_state(c, geometry)
        data = dict(race_time_s=t, lap=c['lap']+1, s=c['s'],
                    observed_speed_kmh=c['speed_mps']*3.6,
                    route_target_kmh=driver.last_target*3.6,
                    heading_deg=math.degrees(c['heading_error']),
                    sideslip_deg=math.degrees(beta), yaw_error_rad_s=yaw_error,
                    stability_risk=risk, recorded_brake=row['action']['brake'],
                    candidate_brake=action['brake'], recorded_throttle=row['action']['throttle'],
                    candidate_throttle=action['throttle'], candidate_steer=action['steer'])
        if 3500 <= c['s'] <= 3700:
            key=str(c['lap']+1)
            if key not in corners or abs(c['s']-3640)<abs(corners[key]['s']-3640):
                corners[key]=data
        if c['lap']==3 and 3500<=c['s']<=3700:
            for axle in ('front','rear'):
                if c.get(axle+'_sliding') and axle not in first_slide:
                    first_slide[axle]=dict(race_time_s=t,s=c['s'],speed_kmh=c['speed_mps']*3.6)
        if 463.5<=t<=467.3:
            samples.append(data)
    positive = [s for s in samples if s['stability_risk']>0]
    result = dict(agent_sha256=hashlib.sha256(Path(agent.__file__).read_bytes()).hexdigest(),
                  complete_export_verified=True, ordered_decisions=count,
                  corner_targets=corners, first_slide_in_incident_approach=first_slide,
                  first_stability_response=positive[0] if positive else None,
                  max_recorded_brake_in_window=max(s['recorded_brake'] for s in samples),
                  max_candidate_brake_in_window=max(s['candidate_brake'] for s in samples),
                  samples=samples,
                  limitation='Full chronological replay on fixed historical legal observations. '
                              'Candidate actions do not change those observations; this is not a rescue, new lap, or closed-loop performance result.')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('log',type=Path)
    p.add_argument('--output',type=Path,default=Path('experiments/stability-replay-v7.json'))
    args=p.parse_args()
    result=run(args.log)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False))
