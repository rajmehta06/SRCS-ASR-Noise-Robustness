from pathlib import Path
SEED=23
SAMPLE_COUNT=15
SAMPLE_RATE=16000
SNR_DB=(0,10,20)
NOISE_CATEGORIES=("noise","music","speech")
MODEL_NAME="tiny.en"
MUSAN_DATASET_ID="corypaik/musan"
MUSAN_REVISION="76f9882cfa4475efe11508ac9aa32722f84ca5b7"
MUSAN_STREAM_BUFFER=15
DATA_ROOT=Path("data")
RESULTS_ROOT=Path("results")
