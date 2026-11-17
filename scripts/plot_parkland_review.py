"""Plot verified observed differences; never plot candidate targets as race results."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=FontProperties(fname='/System/Library/Fonts/Hiragino Sans GB.ttc')
    data=json.loads((ROOT/'experiments/latest-podium-2026-11-17.json').read_text())
    stations=json.loads((ROOT/'experiments/parkland-podium-stations.json').read_text())
    own=data['cars'][0];third=next(c for c in data['cars'] if c['classification']['position']==3)
    fig,axes=plt.subplots(2,1,figsize=(11,8),layout='constrained',facecolor='#f7f8fc')
    colors=['#d45247','#168d84','#456dd8','#9a68c8']
    selected=[1100,3050,4130,4320,5350]
    for i,(seat,label) in enumerate([(8,'你 · 第9'),(0,'冠军'),(2,'亚军'),(3,'季军')]):
        axes[0].bar([j+(i-1.5)*.19 for j in range(len(selected))],
                    [stations[f'{seat}:{s}']['speed_mps']*3.6 for s in selected],
                    width=.18,color=colors[i],label=label)
    axes[0].set_xticks(range(len(selected)),[f'{s} m' for s in selected])
    axes[0].set_title('最后一圈同位置实际速度：差距主要在弯道',fontproperties=font,fontsize=14)
    axes[0].set_ylabel('km/h');axes[0].legend(prop=font,ncol=4)
    bins=own['ontrack_distance_bins'];delta=[a['seconds']-b['seconds'] for a,b in zip(bins,third['ontrack_distance_bins'])]
    axes[1].bar(range(20),delta,color=['#d45247' if x>0 else '#168d84' for x in delta])
    axes[1].set_xticks(range(0,20,2),[str(round(bins[i]['start_m'])) for i in range(0,20,2)])
    axes[1].set_title('四圈赛道分段：你比第三名多用的时间（不含维修区）',fontproperties=font,fontsize=14)
    axes[1].set_xlabel('赛道位置 / m',fontproperties=font);axes[1].set_ylabel('s')
    axes[1].annotate(f'{max(delta):.2f} s',xy=(delta.index(max(delta)),max(delta)),xytext=(0,6),textcoords='offset points',ha='center')
    for ax in axes:
        ax.set_facecolor('#ffffff');ax.grid(axis='y',alpha=.16);ax.set_axisbelow(True)
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Parkland · 2026-11-17 08:34 · 第九名复盘',fontproperties=font,fontsize=18)
    fig.supxlabel('来自完整公开正赛采样；展示真实历史成绩，不代表 v10 优化后的成绩。',fontproperties=font,fontsize=10)
    out=ROOT/'docs/assets/parkland-2026-11-17.png';out.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(out,dpi=160);plt.close(fig);print(out)


if __name__=='__main__':main()
