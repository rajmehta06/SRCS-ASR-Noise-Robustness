# SRCS Case Study — Option A: Robustness in Noisy Environments

Individual project by Raj Mehta (23BTRCL021), Speech Recognition and Conversational Systems, JAIN (Deemed-to-be University), Academic Year 2026–27. Assignment deadline: 24 November 2026.

## Project status

The implementation and Colab workflow are prepared. The full experiment has **not** been run. Results, charts, and report outputs will be generated only from actual model predictions. Do not submit the marked report draft as a final report.

## Run in Google Colab (recommended)

The notebook mounts Google Drive and writes data, checkpoints, predictions, charts, metadata, and report files directly into this project folder on Drive. It installs `requirements.txt`, runs lightweight tests, and then executes the existing project modules. Choose a GPU runtime for faster Whisper inference; CPU is detected and supported automatically.

1. In Google Drive, click **New → New folder** and name it `SRCS_Case_Study`.
2. Click **New → Folder upload** and select the existing `SRCS_Case_Study` project folder from your computer. Ensure that `README.md`, `config.py`, `src`, `scripts`, `requirements.txt`, and `notebooks` are in the uploaded folder (not nested inside a second copy of the folder).
3. Open `My Drive/SRCS_Case_Study/notebooks/SRCS_Noise_Robustness.ipynb` with Google Colaboratory. If needed, open Colab, choose **File → Open notebook → Google Drive**, and select the notebook.
4. In Colab, choose **Runtime → Change runtime type → T4 GPU** if available. The notebook also works on CPU, but transcription may take much longer.
5. Choose **Runtime → Run all**. Approve the Drive mount prompt and select the Google account that contains the project.
6. Wait for each cell to finish. The experiment cell downloads LibriSpeech and the small MUSAN sample set, then runs ASR. Keep the runtime connected until the experiment and analysis finish.
7. Find persistent outputs in `My Drive/SRCS_Case_Study/results/`. Rerun the experiment cell to resume from `predictions.csv` after interruption. To discard checkpoints and start over, delete `results/predictions.csv` in Drive before rerunning.

The notebook verifies the expected project path and stops with an actionable error if the folder was uploaded with an extra nesting level. Keep the project in the stated Drive location or update `PROJECT_DIR` in the first code cell.

## Data retrieval and licensing

### LibriSpeech

`src.data.ensure_librispeech()` downloads LibriSpeech dev-clean from OpenSLR into `data/LibriSpeech/` only if transcript files are not already present. The archive is about 337 MB compressed. The 15 test utterances are chosen from distinct speakers with fixed seed 23 and resampled to 16 kHz mono.

### MUSAN

The official OpenSLR MUSAN download is an 11 GB `musan.tar.gz` archive, which is unnecessarily large for this experiment. `src.data.musan_noise()` instead uses [Hugging Face Datasets streaming](https://huggingface.co/docs/datasets/main/en/stream) against the public `corypaik/musan` mirror, requesting 15 clips from each real `noise`, `music`, and `speech` configuration. The dataset is pinned to revision `76f9882cfa4475efe11508ac9aa32722f84ca5b7`. Streaming iterates without downloading the complete dataset. The mirror stores audio in large Parquet shards, however, so network bytes fetched can exceed the size of the 45 selected WAVs; this method avoids the full archive but cannot promise byte-for-byte retrieval of only those clips. Selected WAVs are cached in `data/musan_selected/`, so later runs use the Drive copies rather than stream them again. If the stream fails, the run stops with a clear error; it never substitutes synthetic noise. Since streaming is supported, the notebook does not automatically fall back to the 11 GB OpenSLR archive.

OpenSLR lists the corpus under CC BY 4.0. The mirror notes that source recordings have their own terms. The pipeline preserves the mirror's `licenses/` mapping files, writes `MUSAN_ATTRIBUTION.md`, and records each selected row's `source` and original `path` in `musan_manifest.csv`. Review those terms before redistributing clips or derived materials. Dataset links: [OpenSLR MUSAN SLR17](https://openslr.org/17/) and [Hugging Face MUSAN dataset card](https://huggingface.co/datasets/corypaik/musan).

## Local setup and use

Python 3.10+ is recommended. Install dependencies with:

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

Run the complete pipeline after reviewing the data sources and available compute:

```bash
python -m src.pipeline --run --allow-download
```

The command downloads missing LibriSpeech and MUSAN samples, loads Whisper tiny.en once, auto-detects CUDA, and checkpoints every completed transcription. Existing output rows are resumed by sample ID and condition. `python -m src.pipeline --run --allow-download --no-resume` starts with an empty in-memory run and overwrites the prediction checkpoint as it proceeds.

Generate figures, tables, and a report draft after predictions exist:

```bash
python scripts/analyze_results.py
python scripts/generate_report.py
```

## Outputs

- `results/predictions.csv`: every reference and hypothesis, noise category, condition, achieved SNR, per-utterance WER/CER, latency, audio duration, and real-time factor.
- `results/condition_summary.csv` and `results/tables/condition_summary.csv`: corpus-level WER/CER and mean latency/RTF by condition.
- `results/metadata.json`: model, selected speakers, sample rate, versions, seed, and evaluation configuration.
- `results/plots/`: WER vs SNR, CER vs SNR, latency, and a clean/noisy/reduced spectrogram with shared color scale.
- `data/LibriSpeech/`, `data/musan_selected/`, and `data/derived/`: data and one spectrogram example, persisted on Drive in Colab.
- `reports/SRCS_Case_Study_DRAFT.docx` before results, or `reports/SRCS_Case_Study.docx` after results. The final report still needs manual listening-based analysis of 3–5 actual errors and verification of the 6–10 page requirement before PDF export.

## Evaluation details

The experiment uses clean speech plus noise/music/interfering speech mixed at 0, 10, and 20 dB SNR. Every mixture also receives spectral reduction with `noisereduce`. SNR uses the clean and scaled-noise component powers, preserving the requested ratio while scaling the combined waveform below clipping. Whisper uses 16 kHz mono input. Text normalization lowercases, removes ASCII punctuation, and collapses whitespace. The project records per-utterance WER/CER and aggregate corpus WER/CER, plus synchronized inference latency on CUDA and real-time factor.

## Submission checklist

- [ ] Complete the Colab experiment and confirm 15 distinct speakers and all conditions.
- [ ] Review achieved SNR, CSV schema, metadata, and generated figures.
- [ ] Listen to 3–5 real transcription errors and write evidence-based acoustic analysis.
- [ ] Complete the report, number/reference figures and tables, and verify 6–10 main pages excluding title, references, and appendices.
- [ ] Export `23BTRCL021_Raj_Mehta_CaseStudy.pdf` and add a shareable code link.
- [ ] Verify PDF, code-link permissions, and hardcopy requirements.
