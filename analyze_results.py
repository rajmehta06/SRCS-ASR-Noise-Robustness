"""Create plots/tables exclusively from actual predictions.csv."""
from pathlib import Path
import pandas as pd, matplotlib.pyplot as plt, numpy as np
from src.pipeline import corpus_scores
root=Path('results'); csv=root/'predictions.csv'
if not csv.exists(): raise SystemExit('No actual results/predictions.csv; run the experiment first.')
df=pd.read_csv(csv); (root/'plots').mkdir(parents=True,exist_ok=True); (root/'tables').mkdir(parents=True,exist_ok=True)
summary=[]
for condition,g in df.groupby('condition',sort=False): summary.append({'condition':condition,**corpus_scores(g.reference,g.prediction),'mean_latency_seconds':g.latency_seconds.mean(),'mean_rtf':g.rtf.mean(),'samples':len(g)})
s=pd.DataFrame(summary); s.to_csv(root/'tables/condition_summary.csv',index=False)
for metric in ('corpus_wer','corpus_cer'):
 plt.figure()
 for category in ('noise','music','speech'):
  for reduced in (False,True):
   family=category+'_reduced' if reduced else category
   vals=[]
   for snr in (0,10,20):
    condition=f'{family}_{snr}dB'; row=s[s.condition==condition]
    vals.append(row[metric].iloc[0] if len(row) else np.nan)
   plt.plot([0,10,20],vals,marker='o',label=f'{category}'+(' reduced' if reduced else ' noisy'))
 plt.xlabel('SNR (dB)'); plt.ylabel(metric.replace('_',' ').upper()); plt.title(f'{metric.upper()} by noise condition'); plt.legend(ncol=2); plt.tight_layout(); plt.savefig(root/f'plots/{metric}_vs_snr.png',dpi=180); plt.close()
plt.figure(); plt.bar(s.condition,s.mean_latency_seconds); plt.xticks(rotation=70,ha='right'); plt.ylabel('Mean inference latency (s)'); plt.tight_layout(); plt.savefig(root/'plots/latency.png',dpi=180); plt.close()
# Fixed-seed example spectrogram, clean/noisy/reduced, shared dB limits and captions.
import soundfile as sf, librosa, librosa.display
from config import SAMPLE_RATE
example=df[df.noise_type!='none'].iloc[0]; sid=example.sample_id; folder=Path('data/derived');
clean,_=sf.read(folder/f'{sid}_clean.wav'); noisy,_=sf.read(folder/f'{sid}_noisy.wav'); reduced,_=sf.read(folder/f'{sid}_reduced.wav')
arrays=[clean,noisy,reduced]; specs=[librosa.amplitude_to_db(abs(librosa.stft(x)),ref=1.0) for x in arrays]; lo=min(x.min() for x in specs); hi=max(x.max() for x in specs)
fig,axes=plt.subplots(3,1,figsize=(10,8));
mesh=None
for ax,x,z,title in zip(axes,arrays,specs,[f'{sid}: clean speech',f'{sid}: MUSAN noise at 0 dB SNR',f'{sid}: noise reduced']): mesh=librosa.display.specshow(z,sr=SAMPLE_RATE,x_axis='time',y_axis='hz',vmin=lo,vmax=hi,ax=ax); ax.set_title(title)
fig.suptitle(f'Clean, noisy, and reduced audio for {sid}; shared dB color range [{lo:.1f}, {hi:.1f}]')
fig.colorbar(mesh,ax=axes,format='%+2.0f dB',label='Magnitude (dB)')
fig.tight_layout(rect=[0,0,1,.95]); fig.savefig(root/'plots/spectrogram.png',dpi=180); plt.close(fig)
