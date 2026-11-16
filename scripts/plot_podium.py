"""Offline podium plot from the hash-verified public replay aggregate."""
import argparse
import json
from pathlib import Path


def plot(source, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data=json.loads(source.read_text())
    own=next(c for c in data['cars'] if c['role']=='own')
    opponents=sorted((c for c in data['cars'] if c is not own),key=lambda c:c['classification']['position'])
    fig,axes=plt.subplots(2,1,figsize=(11,8),layout='constrained')
    stations=['245','6600','6650']
    for i,(car,color,label) in enumerate(zip([own,*opponents],['#dc3545','#169d8f','#4263eb'],['You (P3)','Winner (P1)','Runner-up (P2)'])):
        xs=[j+(i-1)*.24 for j in range(3)]
        axes[0].bar(xs,[car['last_lap_station_samples'][s]['speed_mps']*3.6 for s in stations],width=.22,label=label,color=color)
    axes[0].set_xticks(range(3),[f'{s} m' for s in stations])
    axes[0].set(ylabel='Speed (km/h)',xlabel='Track position on final lap',title='Tight turns: v7 slows far below the leading cars')
    axes[0].legend()
    deltas=[a['seconds']-b['seconds'] for a,b in zip(own['ontrack_distance_bins'],opponents[0]['ontrack_distance_bins'])]
    axes[1].bar(range(20),deltas,color=['#dc3545' if x>0 else '#169d8f' for x in deltas])
    axes[1].set_xticks(range(0,20,2),[str(round(own['ontrack_distance_bins'][i]['start_m'])) for i in range(0,20,2)])
    axes[1].set(xlabel='Distance bin start (m; each bin about 350 m)',ylabel='Your extra time vs winner (s)',title='All four laps, on-track only: most loss occurs in the final 700 m')
    axes[1].axhline(0,color='#64748b',lw=.7)
    for ax in axes:
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('AGX Highland | 16 Nov 2026 | observed race, not a v8 prediction',fontsize=15)
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=170)
    svg=output.with_suffix('.svg');fig.savefig(svg)
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args();plot(a.source,a.output)
