# DRAFT ? EXPERIMENT NOT RUN

**Robustness of Automatic Speech Recognition in Noisy Environments ? Option A**

Raj Mehta ? 23BTRCL021 ? Academic Year 2026?27  
Speech Recognition and Conversational Systems ? JAIN (Deemed-to-be University)  
Submitted to Prof. Shobha H R ? Deadline: 24 November 2026

> This is a report outline only. The experiment has not been run. It contains no measured results, fabricated predictions, or acoustic diagnoses.

## 1. Executive Summary

Pending experiment. Planned comparison: Whisper tiny.en on clean LibriSpeech dev-clean utterances, with MUSAN noise, music, and interfering speech at 0, 10, and 20 dB SNR, before and after spectral noise reduction. Quantitative findings and conclusions will be added from generated CSVs.

## 2. Problem Statement & Real-World Context

Automotive and smart-home microphones capture background sounds that can mask speech cues. This project measures ASR robustness under controlled acoustic mixtures.

## 3. System Architecture & Methodology

Planned flow: 16 kHz mono waveform ? power-based SNR mixing ? Whisper tiny.en transcription ? noisereduce processing and transcription ? normalized WER/CER evaluation. Whisper performs its own internal log-Mel feature processing. The evaluation selects 15 utterances from distinct LibriSpeech dev-clean speakers using seed 23.

## 4. Experimental Setup & Quantitative Results

Pending. The pipeline will record per-utterance predictions, references, WER/CER, latency and real-time factor, and calculate corpus-level WER/CER. Tables, comparative plots, and a shared-scale spectrogram will be generated after a measured run.

## 5. Qualitative Error Analysis

Pending. Select 3?5 actual errors from the result CSV, replay the audio, compare reference/prediction, and record manual acoustic observations. Do not assign causes from text mismatch alone.

## 6. Engineering Trade-offs & Conclusion

Pending measured accuracy and latency. Discuss reduction artifacts, inference speed, and practical deployment only after reviewing experiment outputs.

## References & Appendix

Add complete dataset, model, and library citations plus the shareable repository/Colab link after experiment setup.
