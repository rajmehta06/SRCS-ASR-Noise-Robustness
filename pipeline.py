"""Speech robustness experiment. Download/model execution requires explicit opt-in."""
import argparse,json,random,re,string,time
from importlib.metadata import PackageNotFoundError,version
from pathlib import Path
import numpy as np,pandas as pd,soundfile as sf,torch,whisper,noisereduce as nr,librosa
from jiwer import wer,cer
from config import *
COLS=['sample_id','speaker_id','noise_type','condition','snr_db','reference','prediction','wer','cer','latency_seconds','audio_seconds','rtf']
def normalize_text(text):
 return re.sub(r'\s+',' ',str(text).lower().translate(str.maketrans('','',string.punctuation))).strip()
def power_snr_mix(speech,noise,snr_db):
 x=np.asarray(speech,np.float32); n=np.asarray(noise,np.float32)
 if x.ndim!=1 or n.ndim!=1 or not x.size or not n.size or not np.isfinite(x).all() or not np.isfinite(n).all(): raise ValueError('signals must be finite, nonempty mono arrays')
 if np.mean(x*x)<=0 or np.mean(n*n)<=0: raise ValueError('signals must have nonzero power')
 if len(n)<len(x): n=np.tile(n,int(np.ceil(len(x)/len(n))))
 n=n[:len(x)]; scaled=n*np.sqrt(np.mean(x*x)/(np.mean(n*n)*10**(snr_db/10)))
 y=x+scaled; peak=np.max(np.abs(y)); gain=min(1.0,.999/peak) if peak else 1.0
 y=y*gain; speech_component=x*gain; noise_component=scaled*gain
 actual=10*np.log10(np.mean(speech_component**2)/np.mean(noise_component**2))
 return y.astype(np.float32),float(actual)
def corpus_scores(refs,hyps):
 refs=[normalize_text(x) for x in refs]; hyps=[normalize_text(x) for x in hyps]
 return {'corpus_wer':float(wer(refs,hyps)),'corpus_cer':float(cer(refs,hyps))}
def prepare_dataset(root):
 from src.data import ensure_librispeech
 folder=ensure_librispeech(root); entries=[]
 for t in folder.rglob('*.trans.txt'):
  speaker=t.parent.parent.name
  for line in t.read_text(encoding='utf8').splitlines():
   key,sep,ref=line.partition(' '); wav=t.parent/(key+'.flac')
   if sep and wav.exists(): entries.append((speaker,key,ref,wav))
 rng=random.Random(SEED); rng.shuffle(entries); selected=[]; speakers=set()
 for speaker,key,ref,wav in entries:
  if speaker not in speakers: selected.append((speaker,key,ref,wav)); speakers.add(speaker)
  if len(selected)==SAMPLE_COUNT: break
 if len(selected)<SAMPLE_COUNT: raise RuntimeError('Not enough distinct speakers in dev-clean')
 result=[]
 for speaker,key,ref,wav in selected:
  x,sr=sf.read(wav,dtype='float32'); x=x.mean(axis=1) if x.ndim==2 else x
  if sr!=SAMPLE_RATE: x=librosa.resample(x,orig_sr=sr,target_sr=SAMPLE_RATE)
  result.append(dict(speaker_id=speaker,sample_id=key,reference=ref,audio=x))
 return result
def run(root=DATA_ROOT,results=RESULTS_ROOT,resume=True):
 root=Path(root); results=Path(results); results.mkdir(parents=True,exist_ok=True); ck=results/'predictions.csv'
 rows=pd.read_csv(ck).to_dict('records') if resume and ck.exists() else []; done={(r['sample_id'],r['condition']) for r in rows}
 samples=prepare_dataset(root); from src.data import musan_noise
 noises=musan_noise(root,[s['sample_id'] for s in samples],{s['sample_id']:len(s['audio'])/SAMPLE_RATE for s in samples})
 for cat in NOISE_CATEGORIES:
  if any(s['sample_id'] not in noises.get(cat,{}) for s in samples): raise FileNotFoundError(f'Need one matched clip per utterance in data/musan_selected/{cat}')
 device='cuda' if torch.cuda.is_available() else 'cpu'; model=whisper.load_model(MODEL_NAME,device=device)
 for s in samples:
  x=s['audio']; dur=len(x)/SAMPLE_RATE; variants=[('clean',x,'none',None)]
  for cat in NOISE_CATEGORIES:
   for snr in SNR_DB:
    mixed,actual=power_snr_mix(x,noises[cat][s['sample_id']],snr); variants.append((f'{cat}_{snr}dB',mixed,cat,actual)); variants.append((f'{cat}_reduced_{snr}dB',nr.reduce_noise(y=mixed,sr=SAMPLE_RATE),cat,actual))
  if s is samples[0]:
   dest=Path('data/derived'); dest.mkdir(parents=True,exist_ok=True)
   sf.write(dest/f"{s['sample_id']}_clean.wav",x,SAMPLE_RATE)
   chosen=variants[1][1]; sf.write(dest/f"{s['sample_id']}_noisy.wav",chosen,SAMPLE_RATE)
   sf.write(dest/f"{s['sample_id']}_reduced.wav",nr.reduce_noise(y=chosen,sr=SAMPLE_RATE),SAMPLE_RATE)
  for condition,a,cat,snr in variants:
   if (s['sample_id'],condition) in done: continue
   if device.startswith('cuda'): torch.cuda.synchronize()
   start=time.perf_counter(); pred=model.transcribe(a.astype(np.float32),fp16=device.startswith('cuda'),language='en')['text'].strip()
   if device.startswith('cuda'): torch.cuda.synchronize()
   latency=time.perf_counter()-start; ref=s['reference']
   rows.append(dict(sample_id=s['sample_id'],speaker_id=s['speaker_id'],noise_type=cat,condition=condition,snr_db=snr,reference=ref,prediction=pred,wer=wer(normalize_text(ref),normalize_text(pred)),cer=cer(normalize_text(ref),normalize_text(pred)),latency_seconds=latency,audio_seconds=dur,rtf=latency/dur))
   pd.DataFrame(rows,columns=COLS).to_csv(ck,index=False)
 frame=pd.DataFrame(rows,columns=COLS); frame.to_csv(ck,index=False); summary=[]
 for cond,g in frame.groupby('condition',sort=False): summary.append(dict(condition=cond,**corpus_scores(g.reference,g.prediction),mean_latency_seconds=g.latency_seconds.mean(),mean_rtf=g.rtf.mean(),samples=len(g)))
 pd.DataFrame(summary).to_csv(results/'condition_summary.csv',index=False)
 packages={}
 for package in ('openai-whisper','numpy','librosa','noisereduce','jiwer','datasets','huggingface_hub','soundfile','pandas','matplotlib','scipy'):
  try: packages[package]=version(package)
  except PackageNotFoundError: packages[package]='not installed'
 meta=dict(model=f'Whisper {MODEL_NAME}',device=device,torch_version=torch.__version__,package_versions=packages,sample_rate=SAMPLE_RATE,sample_count=len(samples),speaker_count=len({s['speaker_id'] for s in samples}),audio_seconds_total=sum(len(s['audio'])/SAMPLE_RATE for s in samples),seed=SEED,snr_db=SNR_DB,noise_categories=NOISE_CATEGORIES,noise_dataset={'id':MUSAN_DATASET_ID,'revision':MUSAN_REVISION,'manifest':'data/musan_selected/musan_manifest.csv'},normalization='lowercase; remove ASCII punctuation; collapse whitespace',generated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
 (results/'metadata.json').write_text(json.dumps(meta,indent=2)); return frame
def main():
 p=argparse.ArgumentParser(); p.add_argument('--run',action='store_true'); p.add_argument('--allow-download',action='store_true'); p.add_argument('--no-resume',action='store_true'); a=p.parse_args()
 if not a.run: p.error('Specify --run')
 if not a.allow_download: p.error('Review README and add --allow-download to retrieve LibriSpeech and run the model')
 run(resume=not a.no_resume)
if __name__=='__main__': main()
