"""Verify a public contact-retirement window; never manufacture policy inputs."""
import argparse
from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from track_data import SOURCE_HASHES,geometry_at
from analyze_race_comparison import checked


def analyze(root,geometry_file,seat,rival):
    d=json.loads((root/'descriptor.json').read_text())
    streams={}
    for name in ('public_static','public_events'):
        spec=d['streams'][name];raw=checked(root/(name+'.jsonl'),spec['sha256'])
        rows=[json.loads(l) for l in raw.splitlines()]
        if len(raw)!=spec['raw_bytes'] or len(rows)!=spec['rows']:raise ValueError('Incomplete '+name)
        streams[name]=rows
    meta=streams['public_static'][-1]['metadata'];track=meta['track']['id'];length=meta['track']['length_m']
    start=next(p['start_tick'] for p in meta['phases'] if p['phase']=='race')
    events=[e for e in streams['public_events'] if e['phase']=='race' and seat in e['seats']]
    retirement=next(e for e in events if e['kind']=='retired')
    retire_t=(retirement['tick']-start)/d['physics_hz']
    digest=SOURCE_HASHES[track]['asset_sha256']
    center=json.loads(checked(geometry_file,digest))['centerline'];stations=[p['s'] for p in center]

    def car_info(c):
        i=bisect_right(stations,c['s'])-1;a,b=center[i],center[(i+1)%len(center)]
        end=b['s'] if i+1<len(center) else length
        f=(c['s']-a['s'])/(end-a['s'])
        cx,cy=[a[k]+f*(b[k]-a[k]) for k in ('x','y')]
        road_yaw=math.atan2(b['y']-a['y'],b['x']-a['x'])
        n=-(c['x']-cx)*math.sin(road_yaw)+(c['y']-cy)*math.cos(road_yaw)
        heading=(c['yaw']-road_yaw+math.pi)%(2*math.pi)-math.pi
        return dict(seat=c['seat'],status=c['status'],s_m=c['s'],speed_kmh=c['speed_mps']*3.6,
                    n_m=n,heading_deg=math.degrees(heading),throttle=c['throttle'],brake=c['brake'],
                    steer_rad=c['steer'],position=c['position'],fuel_kg=c['fuel_kg'],
                    tyre_temp_c=c['tyre_temp_c'],tyre_wear=c['tyre_wear'],
                    road_half_widths_m=geometry_at(length,c['s'])[2:])
    chunks=sorted((int(p.stem.split('-')[1]),p) for p in root.glob('frames-*.bin'))
    indices=[i for i,p in chunks]
    if not indices or indices!=list(range(indices[0],indices[-1]+1)):raise ValueError('Noncontiguous window')
    tail=b'';samples=[];first=previous=None;initial=last_running=first_retired=None
    for i,p in chunks:
        raw=checked(p,d['static']['streams']['public_frames'][i])
        lines=(tail+raw).split(b'\n');tail=lines.pop()
        if i==indices[0] and i>0:lines=lines[1:]
        for line in lines:
            r=json.loads(line)
            if r['phase']!='race':continue
            if previous is not None and not 0<r['tick']-previous<=3:raise ValueError('Missing/duplicate sample')
            first=first if first is not None else r['tick'];previous=r['tick']
            t=(r['tick']-start)/d['physics_hz']
            cars={c['seat']:c for c in r['cars']};c=cars[seat];other=cars[rival]
            if initial is None:initial=car_info(c)
            own=car_info(c)
            if c['status']=='racing':last_running=own
            elif first_retired is None:first_retired=own
            if 59<=t<=retire_t+1:
                samples.append(dict(race_time_s=t,tick=r['tick'],wetness=r.get('weather',{}).get('track_wetness'),
                                    own=own,rival=car_info(other),gap_m=other['s']-c['s'],
                                    center_distance_m=math.sqrt(sum((other[k]-c[k])**2 for k in ('x','y','z')))))
    if first is None or not 0<=first-start<=2 or previous<retirement['tick']+60:raise ValueError('Missing race start/retirement window')
    summary_times=(60,62.4,62.5,63,65,78,80,82,82.45,82.55,83,83.5,84,84.5,84.7,84.8)
    return dict(match_id=d['job_id'],track=track,seat=seat,opponent_seat=rival,
                classification=next(c for c in d['result']['classification'] if c['seat']==seat),
                retirement_event=retirement,retirement_race_time_s=retire_t,
                own_events=[dict(race_time_s=(e['tick']-start)/d['physics_hz'],**e) for e in events
                            if e['kind'] not in ('energy_mode','overtaking_aid','manual_override')],
                verified_frame_chunks=indices,first_race_tick=first,last_window_tick=previous,
                frame_scope='Contiguous sampled race start through after own retirement; not full field race/qualifying.',
                source_geometry_sha256=digest,initial=initial,last_running=last_running,first_retired=first_retired,
                nearest_time_samples={str(t):min(samples,key=lambda s:abs(s['race_time_s']-t)) for t in summary_times},
                incident_samples=samples,
                limitations=['24 Hz public frames with rounded positions; road offset/heading are derived approximations.',
                             'No private damage counters, actual policy observations or per-call faults are exposed here.',
                             'Contact events plus subsequent displacement support a contact-related sequence, not an exact damage-component diagnosis.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('--geometry',type=Path,required=True)
    p.add_argument('--seat',type=int,required=True);p.add_argument('--rival',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=analyze(a.directory,a.geometry,a.seat,a.rival)
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k not in ['incident_samples','nearest_time_samples']},ensure_ascii=False))
