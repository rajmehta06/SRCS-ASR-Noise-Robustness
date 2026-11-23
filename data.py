"""Persistent LibriSpeech setup and small, real MUSAN streaming downloads."""
from __future__ import annotations

import csv
import gzip
import os
import re
import random
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

LIBRISPEECH_URL = "https://www.openslr.org/resources/12/dev-clean.tar.gz"
MUSAN_DATASET_ID = "corypaik/musan"
MUSAN_LICENSE_URL = "https://huggingface.co/datasets/corypaik/musan"
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_RETRIES = 4
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
LIBRISPEECH_DEV_CLEAN_MIN_TRANSCRIPTS = 40
LIBRISPEECH_DEV_CLEAN_MIN_AUDIO_FILES = 2703


class _ResumeRejected(Exception):
    """Server did not confirm the exact requested byte range."""


def _archive_is_valid(archive: Path) -> bool:
    """Check gzip CRC through EOF and confirm this is the expected LibriSpeech tar."""
    try:
        # Reading gzip through EOF validates its CRC and uncompressed-size trailer.
        with gzip.open(archive, "rb") as stream:
            while stream.read(DOWNLOAD_CHUNK_BYTES):
                pass
        with tarfile.open(archive, "r:gz") as tf:
            names = tf.getnames()
        prefix = "LibriSpeech/dev-clean/"
        transcripts = [name for name in names if name.startswith(prefix) and name.endswith(".trans.txt")]
        audio_files = [name for name in names if name.startswith(prefix) and name.endswith(".flac")]
        speakers = {name[len(prefix):].split("/", 1)[0] for name in transcripts}
        return (
            len(transcripts) >= LIBRISPEECH_DEV_CLEAN_MIN_TRANSCRIPTS
            and len(audio_files) >= LIBRISPEECH_DEV_CLEAN_MIN_AUDIO_FILES
            and len(speakers) >= LIBRISPEECH_DEV_CLEAN_MIN_TRANSCRIPTS
        )
    except (OSError, EOFError, gzip.BadGzipFile, tarfile.TarError, zlib.error):
        return False


def _content_length(response) -> int | None:
    value = response.headers.get("Content-Length")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _copy_response(response, destination, *, initial_bytes=0, total_bytes=None, mode="wb") -> int:
    copied = initial_bytes
    last_report = time.monotonic()
    with open(destination, mode) as output:
        while True:
            block = response.read(DOWNLOAD_CHUNK_BYTES)
            if not block:
                break
            output.write(block)
            copied += len(block)
            if time.monotonic() - last_report >= 1.0:
                if total_bytes:
                    pct = min(100.0, copied * 100.0 / total_bytes)
                    print(f"\rLibriSpeech download: {copied / 1024**2:.1f}/{total_bytes / 1024**2:.1f} MiB ({pct:.1f}%)", end="", flush=True)
                else:
                    print(f"\rLibriSpeech download: {copied / 1024**2:.1f} MiB", end="", flush=True)
                last_report = time.monotonic()
    print(f"\rLibriSpeech download: {copied / 1024**2:.1f} MiB" + (" (100%)" if total_bytes and copied == total_bytes else ""))
    return copied


def _resume_once(url: str, archive: Path) -> bool:
    """Append only after a 206 and exact Content-Range start/length validation."""
    offset = archive.stat().st_size
    request = urllib.request.Request(
        url,
        headers={"Range": f"bytes={offset}-", "Accept-Encoding": "identity"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise _ResumeRejected(f"server did not accept Range (HTTP {exc.code})") from exc
    with response:
        status = getattr(response, "status", response.getcode())
        content_range = response.headers.get("Content-Range", "")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range.strip())
        if status != 206 or not match:
            raise _ResumeRejected(f"server returned HTTP {status} without a valid Content-Range")
        start, end, total = map(int, match.groups())
        range_length = end - start + 1
        advertised_length = _content_length(response)
        if start != offset or end < start or end >= total or (advertised_length is not None and advertised_length != range_length):
            raise _ResumeRejected(f"invalid Content-Range {content_range!r} for offset {offset}")
        print(f"Resuming LibriSpeech at byte {offset:,} of {total:,}")
        received = _copy_response(response, archive, initial_bytes=offset, total_bytes=total, mode="ab")
        if received - offset != range_length:
            raise ConnectionError(
                f"range body contained {received - offset:,} bytes; Content-Range advertised {range_length:,}"
            )
        if received != total:
            raise ConnectionError(f"range ended at byte {received:,} of {total:,}; retrying from current size")
    return True


def _download_fresh_verified(url: str, root: Path) -> Path:
    """Download to a unique temporary file, verify it, and return its path."""
    last_error = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        fd, temp_name = tempfile.mkstemp(prefix="dev-clean.", suffix=".download.tmp", dir=root)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", response.getcode())
                if status != 200:
                    raise OSError(f"fresh download expected HTTP 200, received {status}")
                content_length = _content_length(response)
                print(f"Downloading LibriSpeech dev-clean (attempt {attempt}/{DOWNLOAD_RETRIES})")
                received = _copy_response(response, temp_path, total_bytes=content_length)
            if content_length is not None and received != content_length:
                raise ConnectionError(f"download ended at {received:,} bytes; expected {content_length:,}")
            print("Verifying gzip/tar integrity...")
            if not _archive_is_valid(temp_path):
                raise OSError("download is not a complete, valid LibriSpeech dev-clean archive")
            return temp_path
        except KeyboardInterrupt:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt < DOWNLOAD_RETRIES:
                delay = min(2 ** (attempt - 1), 8)
                print(f"Download attempt failed: {exc}. Retrying in {delay}s.")
                time.sleep(delay)
    raise RuntimeError(f"Could not download a verified LibriSpeech archive after {DOWNLOAD_RETRIES} attempts: {last_error}") from last_error


def ensure_librispeech(root: Path) -> Path:
    """Download and extract LibriSpeech dev-clean if it is not already present."""
    root = Path(root)
    folder = root / "LibriSpeech"
    if any(folder.rglob("*.trans.txt")):
        return folder
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "dev-clean.tar.gz"
    if archive.exists() and _archive_is_valid(archive):
        print("Found an already complete, verified LibriSpeech archive.")
    else:
        replaced_archive = False
        if archive.exists() and archive.stat().st_size:
            print(f"Found incomplete archive ({archive.stat().st_size / 1024**2:.1f} MiB); attempting safe HTTP Range resume.")
            for attempt in range(1, DOWNLOAD_RETRIES + 1):
                try:
                    if _resume_once(LIBRISPEECH_URL, archive):
                        print("Verifying resumed gzip/tar integrity...")
                        if _archive_is_valid(archive):
                            replaced_archive = True
                            break
                        print("Resumed file failed integrity verification; preserving it while trying a fresh temporary download.")
                        break
                except _ResumeRejected as exc:
                    print(f"Range resume unavailable or invalid: {exc}. Will restart into a temporary file.")
                    break
                except Exception as exc:
                    if attempt == DOWNLOAD_RETRIES:
                        print(f"Range resume failed after {DOWNLOAD_RETRIES} attempts: {exc}. Will restart into a temporary file.")
                        break
                    delay = min(2 ** (attempt - 1), 8)
                    print(f"Range transfer interrupted: {exc}. Retrying from the current file size in {delay}s.")
                    time.sleep(delay)
        if not replaced_archive:
            # A fresh, verified temp archive is atomically substituted only after full validation.
            temp_path = _download_fresh_verified(LIBRISPEECH_URL, root)
            os.replace(temp_path, archive)
    print("Extracting LibriSpeech dev-clean")
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(root, filter="data")
    archive.unlink(missing_ok=True)
    if not any(folder.rglob("*.trans.txt")):
        raise RuntimeError("LibriSpeech download completed but transcripts were not found")
    return folder


def _save_license_material(destination: Path) -> None:
    """Persist the mirror's per-source licensing files and attribution note."""
    from huggingface_hub import snapshot_download
    from config import MUSAN_REVISION

    license_root = destination / "license_sources"
    license_root.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id=MUSAN_DATASET_ID,
            repo_type="dataset",
            revision=MUSAN_REVISION,
            allow_patterns=["licenses/**"],
            local_dir=license_root,
        )
    except Exception as exc:
        raise RuntimeError(
            "Could not retrieve the MUSAN per-source license mappings. "
            "The audio was not substituted; check the Hugging Face connection and rerun."
        ) from exc
    (destination / "MUSAN_ATTRIBUTION.md").write_text(
        "MUSAN is distributed by OpenSLR (SLR17) under CC BY 4.0 at the corpus level. "
        "The Hugging Face mirror documents that source recordings may have distinct "
        "terms. Review the preserved license_sources/licenses files and the `source` "
        "and `path` columns in musan_manifest.csv for every selected recording. "
        "Dataset card and access: " + MUSAN_LICENSE_URL + "\n\n"
        "Citation: David Snyder, Guoguo Chen, and Daniel Povey, "
        "'MUSAN: A Music, Speech, and Noise Corpus,' arXiv:1510.08484 (2015).\n",
        encoding="utf-8",
    )


def musan_noise(
    root: Path,
    sample_ids: list[str],
    sample_durations: dict[str, float] | None = None,
) -> dict[str, dict[str, object]]:
    """Stream only a reproducible small set of genuine MUSAN audio examples.

    One recording per LibriSpeech utterance ID is cached for each MUSAN class.
    Hugging Face Datasets streaming avoids downloading the OpenSLR 11 GB tarball.
    Audio is saved to Drive-backed project data so later runs reuse it.
    """
    import librosa
    import numpy as np
    import soundfile as sf
    from datasets import load_dataset
    from config import MUSAN_REVISION, MUSAN_STREAM_BUFFER, SAMPLE_RATE, SEED

    sample_ids = list(sample_ids)
    sample_durations = sample_durations or {}
    base = Path(root) / "musan_selected"
    base.mkdir(parents=True, exist_ok=True)
    manifest_path = base / "musan_manifest.csv"
    manifest = []
    output: dict[str, dict[str, object]] = {}

    # Cache source licensing files even when audio is already cached.
    if not (base / "MUSAN_ATTRIBUTION.md").exists():
        _save_license_material(base)

    for category_index, category in enumerate(("noise", "music", "speech")):
        category_dir = base / category
        category_dir.mkdir(parents=True, exist_ok=True)
        output[category] = {}
        cached_rows = {}
        if manifest_path.exists():
            with manifest_path.open(newline="", encoding="utf-8") as stream:
                cached_rows = {
                    (row["category"], row["sample_id"]): row
                    for row in csv.DictReader(stream)
                }

        missing = [sid for sid in sample_ids if not (category_dir / f"{sid}.wav").exists()]
        needs_manifest = any((category, sid) not in cached_rows for sid in sample_ids)
        if missing or needs_manifest:
            print(f"Streaming a small reproducible set of real MUSAN {category} clips")
            try:
                stream = load_dataset(
                    MUSAN_DATASET_ID,
                    category,
                    split="train",
                    streaming=True,
                    revision=MUSAN_REVISION,
                ).shuffle(
                    seed=SEED + category_index,
                    buffer_size=max(MUSAN_STREAM_BUFFER, len(missing)),
                )
                # Always read the same prefix and pair it with the same seeded utterance
                # IDs. This keeps partial reruns deterministic after interruptions.
                selected = list(stream.take(len(sample_ids)))
            except Exception as exc:
                raise RuntimeError(
                    f"Could not stream MUSAN {category!r} from {MUSAN_DATASET_ID}. "
                    "No synthetic substitute was generated. Check the dataset/network "
                    "and rerun this cell; downloaded files already on Drive are retained."
                ) from exc
            if len(selected) < len(sample_ids):
                raise RuntimeError(
                    f"MUSAN stream returned only {len(selected)} {category} clips; "
                    f"need {len(sample_ids)}. No substitutes were used."
                )
            for sid, row in zip(sample_ids, selected):
                audio = row["audio"]
                waveform = np.asarray(audio["array"], dtype=np.float32)
                sample_rate = int(audio["sampling_rate"])
                if waveform.ndim == 2:
                    waveform = waveform.mean(axis=0 if waveform.shape[0] < waveform.shape[1] else 1)
                if sample_rate != SAMPLE_RATE:
                    waveform = librosa.resample(
                        waveform, orig_sr=sample_rate, target_sr=SAMPLE_RATE
                    )
                if waveform.ndim != 1 or not waveform.size or not np.isfinite(waveform).all():
                    raise RuntimeError(f"Invalid audio returned for MUSAN item {row.get('path')}")
                source_duration = len(waveform) / SAMPLE_RATE
                target_samples = int(sample_durations.get(sid, source_duration) * SAMPLE_RATE)
                offset_samples = 0
                if 0 < target_samples < len(waveform):
                    stable_seed = SEED + category_index + sum(ord(char) for char in sid)
                    offset_samples = random.Random(stable_seed).randint(0, len(waveform) - target_samples)
                    waveform = waveform[offset_samples:offset_samples + target_samples]
                target = category_dir / f"{sid}.wav"
                if not target.exists():
                    sf.write(target, waveform, SAMPLE_RATE, subtype="PCM_16")
                details = {
                    "category": category,
                    "sample_id": sid,
                    "dataset": MUSAN_DATASET_ID,
                    "revision": MUSAN_REVISION,
                    "source": str(row.get("source", "")),
                    "original_path": str(row.get("path", "")),
                    "sample_rate_hz": SAMPLE_RATE,
                    "source_duration_seconds": source_duration,
                    "crop_offset_seconds": offset_samples / SAMPLE_RATE,
                    "duration_seconds": len(waveform) / SAMPLE_RATE,
                }
                cached_rows[(category, sid)] = details

        for sid in sample_ids:
            wav_path = category_dir / f"{sid}.wav"
            if not wav_path.exists():
                raise FileNotFoundError(f"MUSAN clip missing after streaming: {wav_path}")
            waveform, sample_rate = sf.read(wav_path, dtype="float32")
            if waveform.ndim == 2:
                waveform = waveform.mean(axis=1)
            if sample_rate != SAMPLE_RATE:
                waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=SAMPLE_RATE)
            target_samples = int(sample_durations.get(sid, len(waveform) / SAMPLE_RATE) * SAMPLE_RATE)
            if 0 < target_samples < len(waveform):
                stable_seed = SEED + category_index + sum(ord(char) for char in sid)
                offset = random.Random(stable_seed).randint(0, len(waveform) - target_samples)
                waveform = waveform[offset:offset + target_samples]
            output[category][sid] = waveform
            if (category, sid) in cached_rows:
                manifest.append(cached_rows[(category, sid)])

    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["category", "sample_id", "dataset", "revision", "source", "original_path", "sample_rate_hz", "source_duration_seconds", "crop_offset_seconds", "duration_seconds"],
        )
        writer.writeheader()
        writer.writerows(manifest)
    return output

