"""Compare candidate/v9 on identical synthetic wet sequences, not race physics."""
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark import PublicGeometry,make_observation,validate
from replay_check import baseline_source,load_policy,action_difference
from track_data import TRACKS


def main():
    ref='e6c74b0102738fec53b1168f974645b97f9df106'
    old=load_policy(baseline_source(ref),'v9_wet')
    new=load_policy((ROOT/'agent.py').read_bytes(),'v10_wet')
    base=json.loads((ROOT/'tests/fixtures/official_observation.json').read_text())
    segments=[]
    for track in TRACKS.values():
        for wet in (.3,.8,1):
            drivers=[old.Driver(),new.Driver()];changed=0
            for i in range(1000):
                o=make_observation(base,PublicGeometry(track),wet,i,1000)
                o['self']['tyre_temp_c']=[35+55*(.5+.5*math.sin(i*.03))]*4
                a,b=[d.act(o) for d in drivers];validate(a);validate(b)
                changed+=action_difference(a,b)
            segments.append(dict(track=track['id'],wet=wet,calls=1000,changed_actions=changed))
    result=dict(baseline_ref=ref,calls=9000,changed_actions=sum(s['changed_actions'] for s in segments),
                segments=segments,limitation='Synthetic fixed legal-shape inputs, not the unavailable newest race trace or physical weather transitions.')
    (ROOT/'experiments/v10-wet-fallback.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));assert result['changed_actions']==0


if __name__=='__main__':main()
