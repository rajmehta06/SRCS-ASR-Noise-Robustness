import numpy as np,pandas as pd
from src.pipeline import power_snr_mix,normalize_text,COLS
def test_snr():
 x=np.sin(np.linspace(0,50,16000)).astype('float32')*.1; n=np.cos(np.linspace(0,30,16000)).astype('float32'); y,actual=power_snr_mix(x,n,10); assert abs(actual-10)<.1; assert np.max(np.abs(y))<=.999
def test_normalization(): assert normalize_text("Hello, WORLD!  ")=="hello world"
def test_schema(): assert COLS==['sample_id','speaker_id','noise_type','condition','snr_db','reference','prediction','wer','cer','latency_seconds','audio_seconds','rtf']; assert list(pd.DataFrame(columns=COLS).columns)==COLS
def test_noise_reduction_smoke():
 import noisereduce as nr
 x=np.random.default_rng(1).normal(0,.02,8000).astype('float32'); y=nr.reduce_noise(y=x,sr=16000); assert y.shape==x.shape and np.isfinite(y).all()
