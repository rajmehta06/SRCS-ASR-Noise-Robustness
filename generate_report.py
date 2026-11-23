"""Generate a results-based SRCS report from one project folder.

Run from the project directory, or pass --project-root when the project lives on
Google Drive (for example /content/drive/MyDrive/SRCS_Case_Study). The script
refuses to create a report if the real experiment CSVs or figures are missing.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


EXPECTED_COLUMNS = {
    "sample_id", "speaker_id", "noise_type", "condition", "snr_db",
    "reference", "prediction", "wer", "cer", "latency_seconds",
    "audio_seconds", "rtf",
}
FIGURE_FILES = {
    "wer": ("results/plots/corpus_wer_vs_snr.png", "Figure 2. Corpus word error rate by SNR and processing condition."),
    "cer": ("results/plots/corpus_cer_vs_snr.png", "Figure 3. Corpus character error rate by SNR and processing condition."),
    "latency": ("results/plots/latency.png", "Figure 4. Mean inference latency by processing condition."),
    "spectrogram": ("results/plots/spectrogram.png", "Figure 5. Clean, noisy, and noise-reduced spectrograms using a shared magnitude scale."),
}


def table_style_for(document):
    """Return an available table style, with the supplied template's Table1 fallback."""
    styles = [style for style in document.styles if style.type == WD_STYLE_TYPE.TABLE]
    preferred = ("Light Shading Accent 1", "Light Grid Accent 1", "Table Grid")
    for candidate in preferred:
        for style in styles:
            if style.name.casefold() == candidate.casefold() or style.style_id.casefold() == candidate.casefold().replace(" ", ""):
                return style
    for fallback_id in ("Table1", "TableNormal"):
        for style in styles:
            if style.style_id == fallback_id:
                return style
    return styles[0] if styles else None


def set_cell_text(cell, text: str, *, bold=False, color="000000", size=8.5, align=None):
    """Replace cell contents while keeping the cell and paragraph formatting."""
    paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    runs = paragraph.runs
    if runs:
        runs[0].text = str(text)
        for run in runs[1:]:
            run.text = ""
        run = runs[0]
    else:
        run = paragraph.add_run(str(text))
    run.bold = bold
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.line_spacing = 1.0
    paragraph.paragraph_format.space_after = Pt(2)


def set_cell_shading(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_borders(cell, color="C7D2DE", size="4"):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top=90, start=90, bottom=90, end=90):
    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn("w:" + edge))
        if node is None:
            node = OxmlElement("w:" + edge)
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def format_data_table(table, document, widths=None, *, header=True, font_size=8.5):
    """Apply an available style plus explicit, consistent table formatting."""
    style = table_style_for(document)
    if style is not None:
        table.style = style
    table.autofit = False
    if header and table.rows:
        tr_pr = table.rows[0]._tr.get_or_add_trPr()
        repeat = OxmlElement("w:tblHeader")
        repeat.set(qn("w:val"), "true")
        tr_pr.append(repeat)
    for row_index, row in enumerate(table.rows):
        for col_index, cell in enumerate(row.cells):
            if widths and col_index < len(widths):
                cell.width = Inches(widths[col_index])
            set_cell_borders(cell)
            set_cell_margins(cell)
            if header and row_index == 0:
                set_cell_shading(cell, "234A6F")
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.color.rgb = RGBColor(255, 255, 255)
                        run.font.name = "Times New Roman"
                        run.font.size = Pt(font_size)
            else:
                set_cell_shading(cell, "FFFFFF" if row_index % 2 else "F2F6FA")
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = "Times New Roman"
                        run.font.size = Pt(font_size)


def replace_template_text(document, replacements):
    """Replace tokens in runs rather than assigning paragraph.text (preserves formatting)."""
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            for old, new in replacements.items():
                if old in run.text:
                    run.text = run.text.replace(old, new)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        for old, new in replacements.items():
                            if old in run.text:
                                run.text = run.text.replace(old, new)


def fill_title_page(document):
    replacements = {
        "[TITLE OF YOUR CASE STUDY]": "Robustness of Automatic Speech Recognition in Noisy Environments",
        "[Scenario Name]": "Option A: Automotive / Smart Home",
        "[DD Month YYYY, e.g., 25 November 2026]": "24 November 2026",
        "[Paste Shareable GitHub / Google Colab URL Here]": "Shareable repository / Colab link pending",
    }
    replace_template_text(document, replacements)
    if document.tables:
        cover_table = document.tables[0]
        values = {
            "Name of Student": "Raj Mehta",
            "Roll Number": "23BTRCL021",
            "Section": "Not provided",
            "Academic Year": "2026 - 27",
        }
        for row in cover_table.rows[1:]:
            if len(row.cells) > 1:
                label = row.cells[0].text.strip()
                if label in values:
                    set_cell_text(row.cells[1], values[label], size=10)


def body_paragraph(document, text="", *, bold_lead=None):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.line_spacing = 1.15
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.keep_together = True
    if bold_lead and text.startswith(bold_lead):
        lead = paragraph.add_run(bold_lead)
        lead.bold = True
        paragraph.add_run(text[len(bold_lead):])
    else:
        paragraph.add_run(text)
    for run in paragraph.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0, 0, 0)
    return paragraph


def section_heading(document, title, *, page_break=False):
    paragraph = document.add_heading(title, level=1)
    paragraph.paragraph_format.keep_with_next = True
    if page_break:
        paragraph.paragraph_format.page_break_before = True
    for run in paragraph.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(14)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0, 0, 0)
    return paragraph


def add_caption(document, text):
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_together = True
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(9)
    run = paragraph.add_run(text)
    run.italic = True
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    return paragraph


def verify_inputs(project_root: Path):
    result_dir = project_root / "results"
    predictions_path = result_dir / "predictions.csv"
    metadata_path = result_dir / "metadata.json"
    summary_candidates = [result_dir / "tables/condition_summary.csv", result_dir / "condition_summary.csv"]
    summary_path = next((path for path in summary_candidates if path.exists()), summary_candidates[0])
    figure_paths = {key: project_root / relative for key, (relative, _) in FIGURE_FILES.items()}
    missing = [path for path in (predictions_path, metadata_path, summary_path, *figure_paths.values()) if not path.exists()]
    if missing:
        missing_list = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "Cannot generate a results-based report because these real experiment files are missing:\n"
            f"{missing_list}\nPass --project-root pointing to the mounted Google Drive project folder."
        )
    return predictions_path, metadata_path, summary_path, figure_paths


def load_results(predictions_path, metadata_path, summary_path):
    predictions = pd.read_csv(predictions_path)
    missing_columns = EXPECTED_COLUMNS - set(predictions.columns)
    if missing_columns:
        raise ValueError(f"predictions.csv is missing required columns: {sorted(missing_columns)}")
    if predictions.empty:
        raise ValueError("predictions.csv contains no experiment rows")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    summary = pd.read_csv(summary_path)
    required_summary = {
        "condition", "corpus_wer", "corpus_cer", "mean_latency_seconds", "mean_rtf", "samples"
    }
    if required_summary - set(summary.columns):
        raise ValueError(f"condition_summary.csv is missing columns: {sorted(required_summary - set(summary.columns))}")
    for metric in ("corpus_wer", "corpus_cer"):
        summary[metric] = pd.to_numeric(summary[metric], errors="raise")
    for metric in ("mean_latency_seconds", "mean_rtf", "samples"):
        summary[metric] = pd.to_numeric(summary[metric], errors="raise")
    if summary[["corpus_wer", "corpus_cer", "mean_latency_seconds", "mean_rtf", "samples"]].isna().any().any():
        raise ValueError("condition_summary.csv contains missing metric values")
    expected_conditions = {"clean"}
    for category in ("noise", "music", "speech"):
        for snr in (0, 10, 20):
            expected_conditions.add(f"{category}_{snr}dB")
            expected_conditions.add(f"{category}_reduced_{snr}dB")
    missing_conditions = expected_conditions - set(summary.condition.astype(str))
    if missing_conditions:
        raise ValueError(f"Condition summary is incomplete: {sorted(missing_conditions)}")
    recorded_samples = metadata.get("sample_count")
    if recorded_samples is not None and int(recorded_samples) != predictions.sample_id.nunique():
        raise ValueError("metadata sample_count does not match unique prediction sample IDs")
    return predictions, metadata, summary


def condition_row(summary, condition):
    found = summary[summary.condition.astype(str) == condition]
    return found.iloc[0] if not found.empty else None


def add_architecture_diagram(document):
    labels = [
        ("Audio", "LibriSpeech\n16 kHz mono"),
        ("Preprocessing", "Power-based SNR\n0 / 10 / 20 dB"),
        ("Features", "Whisper log-Mel\nfrontend"),
        ("ASR model", "tiny.en encoder–decoder\n(acoustic + language)"),
        ("Output", "Transcript\nWER / CER / latency"),
    ]
    table = document.add_table(rows=2, cols=5)
    format_data_table(table, document, [1.28] * 5, header=False, font_size=8)
    for col, (stage, detail) in enumerate(labels):
        set_cell_text(table.cell(0, col), stage, bold=True, color="234A6F", size=9, align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_text(table.cell(1, col), detail, size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_shading(table.cell(0, col), "DCE8F2")
        set_cell_shading(table.cell(1, col), "F6F8FA")
    add_caption(document, "Figure 1. Processing path used in this experiment.")


def build_report(project_root: Path, output_path: Path, *, export_pdf=False):
    predictions_path, metadata_path, summary_path, figures = verify_inputs(project_root)
    predictions, metadata, summary = load_results(predictions_path, metadata_path, summary_path)
    from src.pipeline import normalize_text
    from jiwer import wer, cer

    # Check corpus values in the saved summary against the raw, saved references and hypotheses.
    for _, row in summary.iterrows():
        group = predictions[predictions.condition.astype(str) == str(row.condition)]
        if group.empty:
            raise ValueError(f"Summary condition {row.condition!r} has no matching prediction rows")
        refs = [normalize_text(value) for value in group.reference.fillna("")]
        hyps = [normalize_text(value) for value in group.prediction.fillna("")]
        if abs(float(wer(refs, hyps)) - float(row.corpus_wer)) > 1e-6 or abs(float(cer(refs, hyps)) - float(row.corpus_cer)) > 1e-6:
            raise ValueError(f"Saved corpus WER/CER does not match predictions for {row.condition!r}")

    template_path = project_root / "reports/Report Title Page.docx"
    if not template_path.exists():
        raise FileNotFoundError(f"Official university title-page template is missing: {template_path}")
    document = Document(template_path)
    fill_title_page(document)
    document.add_page_break()

    # Preserve the supplied first-page layout, image relationships, and margins.
    title = document.add_paragraph(style="Title")
    title.paragraph_format.space_after = Pt(5)
    title_run = title.add_run("Robustness of Automatic Speech Recognition in Noisy Environments")
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(17)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0, 0, 0)
    body_paragraph(document, "Results report | Speech Recognition and Conversational Systems | Option A")
    body_paragraph(document,
        "DRAFT: complete the listening-based analysis in Section 5 and add the shareable repository/Colab URL "
        "on the title page before submission.")

    clean = condition_row(summary, "clean")
    if clean is None:
        raise ValueError("The result summary has no clean baseline condition")
    best = summary.sort_values("corpus_wer").iloc[0]
    worst = summary.sort_values("corpus_wer", ascending=False).iloc[0]
    sample_count = int(predictions.sample_id.nunique())
    speaker_count = int(metadata.get("speaker_count", predictions.speaker_id.nunique()))
    total_seconds = float(metadata.get("audio_seconds_total", predictions.drop_duplicates("sample_id").audio_seconds.sum()))
    model_name = str(metadata.get("model", "Whisper tiny.en"))
    device = str(metadata.get("device", "not recorded"))
    clean_wer = float(clean.corpus_wer)
    clean_cer = float(clean.corpus_cer)

    section_heading(document, "Section 1. Executive Summary")
    body_paragraph(document,
        f"This report measures the effect of real background noise on {model_name} using {sample_count} "
        f"seeded LibriSpeech dev-clean utterances from {speaker_count} distinct speakers. The experiment "
        f"compares the clean baseline with MUSAN noise, music, and speech mixtures at 0, 10, and 20 dB SNR, "
        "and with spectral noise reduction applied to each mixture. The recordings were evaluated with "
        "corpus-level WER and CER, inference latency, and real-time factor.")
    body_paragraph(document,
        f"The clean baseline measured WER {clean_wer:.4f} and CER {clean_cer:.4f}. Across all recorded "
        f"conditions, the lowest corpus WER was {float(best.corpus_wer):.4f} for {best.condition}; the highest "
        f"was {float(worst.corpus_wer):.4f} for {worst.condition}. These observations describe this evaluation "
        "subset and do not establish performance on other microphones, speakers, or noise sources."
    )

    section_heading(document, "Section 2. Problem Statement and Real-World Context", page_break=True)
    body_paragraph(document,
        "Voice interfaces in vehicles and smart homes operate in rooms and cabins where fans, road noise, "
        "music, and nearby speakers overlap with the target voice. Such interference can mask quiet consonants, "
        "change the balance between speech and background sound, and make the speech signal less like the "
        "clean read speech used in many evaluations. This case study tests that deployment concern with "
        "controlled mixtures rather than relying on a qualitative claim about robustness.")
    body_paragraph(document,
        "The task is inference-only: the pretrained English Whisper tiny.en model is not fine-tuned. LibriSpeech "
        "dev-clean provides aligned reference text and clean speech; MUSAN supplies the three background "
        "categories through Hugging Face Datasets [8]. The experiment uses 15 fixed-seed utterances from distinct "
        "speakers, resampled to 16 kHz mono with librosa [4]. It evaluates the dev-clean subset and does not create a separate training split. "
        "The clean recordings act as the within-sample baseline [1, 2].")
    body_paragraph(document,
        "The practical constraints are a limited sample size, a compact pretrained model, and finite inference "
        "time. Results therefore describe the selected subset and conditions only. A controlled SNR sweep helps "
        "separate the effect of mixture level from the type of background recording, while the noise-reduction "
        "comparison shows whether this particular preprocessing configuration changes recognition quality. "
        "The experiment does not claim that spectral reduction removes all environmental interference.")

    section_heading(document, "Section 3. System Architecture and Methodology", page_break=True)
    body_paragraph(document,
        "Figure 1 summarizes the pipeline. Each clean utterance is read with its reference transcript, converted "
        "to 16 kHz mono, paired with a real MUSAN clip, and mixed at the configured SNR. The original clean "
        "waveform, each noisy waveform, and each reduced waveform are sent to the same Whisper tiny.en model. "
        "Predictions and timing are checkpointed to CSV; evaluation and plots use those saved outputs.")
    add_architecture_diagram(document)
    body_paragraph(document,
        "For a target SNR s, the noise gain is calculated from signal powers: alpha = sqrt(Pspeech / "
        "(Pnoise * 10^(s/10))). The resulting mixture is peak-limited by scaling speech and noise together, "
        "which retains their power ratio. The achieved SNR is calculated from the scaled speech and noise "
        "components and recorded with the prediction. Noise reduction uses the noisereduce spectral-gating "
        "implementation with the project configuration (non-stationary mode and prop_decrease 0.8) [6].")
    body_paragraph(document,
        "Whisper uses an encoder-decoder Transformer and performs its own log-Mel frontend; at 16 kHz, its "
        "reference implementation uses a 400-sample FFT window (25 ms), 160-sample hop (10 ms), and 80 Mel "
        "filters. The project passes waveforms to the model rather than manually producing model features [3]. "
        "This design "
        "keeps the recognizer constant across conditions and makes noise condition the principal experimental "
        "change. The tiny.en checkpoint was selected for English inference and practical Colab runtime [5]. No "
        "additional language model or decoding configuration is introduced in the comparison.")
    body_paragraph(document,
        "Text normalization is applied consistently to references and predictions: lowercase text, remove ASCII "
        "punctuation, and collapse repeated whitespace. Corpus WER and CER are computed by aligning the full "
        "reference and hypothesis sets per condition, rather than averaging utterance-level rates. Latency is "
        "measured around transcription; CUDA synchronization is used when a CUDA device is active. RTF is "
        "latency divided by audio duration. These measures answer different questions: WER/CER describe text "
        "agreement, while latency and RTF describe processing cost.")

    section_heading(document, "Section 4. Experimental Setup and Quantitative Results", page_break=True)
    body_paragraph(document,
        f"The evaluation contains {sample_count} unique utterances from {speaker_count} speakers and "
        f"{total_seconds / 60:.2f} minutes of clean speech. Audio is sourced from LibriSpeech dev-clean; "
        "the noise, music, and speech backgrounds are from the pinned MUSAN sample manifest. The model ran "
        f"on {device}. Conditions in Table 1 use the saved result summary, which was checked against the raw "
        "prediction references and hypotheses before this report was assembled.")
    body_paragraph(document,
        "Table 1 reports corpus WER and CER, mean latency, mean RTF, and sample count for every condition. "
        "Figures 2 and 3 compare noisy and noise-reduced curves at each SNR, Figure 4 compares latency, and "
        "Figure 5 shows one clean/noisy/reduced example with a shared spectrogram magnitude scale. Values and "
        "plots are read from the supplied experiment outputs; this report does not regenerate or alter them.")
    caption = body_paragraph(document, "Table 1. Corpus-level recognition and runtime metrics by condition.")
    caption.paragraph_format.keep_with_next = True
    metric_columns = [
        ("condition", "Condition"), ("corpus_wer", "Corpus WER"), ("corpus_cer", "Corpus CER"),
        ("mean_latency_seconds", "Mean latency (s)"), ("mean_rtf", "Mean RTF"), ("samples", "Samples"),
    ]
    table = document.add_table(rows=1, cols=len(metric_columns))
    format_data_table(table, document, [1.72, 0.86, 0.86, 1.15, 0.85, 0.55], header=True, font_size=8)
    for cell, (_, label) in zip(table.rows[0].cells, metric_columns):
        set_cell_text(cell, label, bold=True, color="FFFFFF", size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_shading(cell, "234A6F")
    for _, row in summary.iterrows():
        values = []
        for key, _ in metric_columns:
            if key == "condition": values.append(str(row.condition))
            elif key == "corpus_wer": values.append(f"{float(row.corpus_wer):.4f}")
            elif key == "corpus_cer": values.append(f"{float(row.corpus_cer):.4f}")
            elif key == "mean_latency_seconds": values.append(f"{float(row[key]):.3f}")
            elif key == "mean_rtf": values.append(f"{float(row[key]):.3f}")
            else: values.append(str(int(row[key])))
        cells = table.add_row().cells
        for index, (cell, value) in enumerate(zip(cells, values)):
            align = WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.CENTER
            set_cell_text(cell, value, size=8, align=align)
    format_data_table(table, document, [1.72, 0.86, 0.86, 1.15, 0.85, 0.55], header=True, font_size=8)

    for key in ("wer", "cer", "latency", "spectrogram"):
        image_path = figures[key]
        if not image_path.exists():
            raise FileNotFoundError(f"Required experiment figure is missing: {image_path}")
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.add_run().add_picture(str(image_path), width=Inches(6.2))
        add_caption(document, FIGURE_FILES[key][1])

    section_heading(document, "Section 5. Qualitative Error Analysis", page_break=True)
    body_paragraph(document,
        "Table 2 lists actual sample/condition pairs with nonzero per-utterance WER, ordered by the recorded "
        "error rate. The reference and prediction are copied from predictions.csv. Text mismatch alone does not "
        "identify an acoustic cause, so the final column is intentionally reserved for listening-based analysis. "
        "No cause is inferred or supplied by this generator.")
    errors = predictions[pd.to_numeric(predictions.wer, errors="coerce").fillna(0) > 0]
    errors = errors.sort_values("wer", ascending=False).drop_duplicates(["sample_id", "condition"]).head(5)
    if errors.empty:
        body_paragraph(document, "No rows with nonzero per-utterance WER were present in the supplied prediction CSV.")
    else:
        body_paragraph(document, f"The table contains {len(errors)} genuine error rows available from the result file. Complete the acoustic-analysis column after replaying each corresponding clean/noisy/reduced recording.")
        caption = body_paragraph(document, "Table 2. Transcript comparisons for the highest-WER available error samples.")
        caption.paragraph_format.keep_with_next = True
        error_table = document.add_table(rows=1, cols=4)
        error_widths = [1.15, 2.0, 2.0, 1.35]
        format_data_table(error_table, document, error_widths, header=True, font_size=8)
        for cell, label in zip(error_table.rows[0].cells, ["Sample / condition", "Reference", "Prediction", "Manual acoustic analysis"]):
            set_cell_text(cell, label, bold=True, color="FFFFFF", size=8, align=WD_ALIGN_PARAGRAPH.CENTER)
            set_cell_shading(cell, "234A6F")
        for _, row in errors.iterrows():
            cells = error_table.add_row().cells
            values = [f"{row.sample_id}\n{row.condition}", str(row.reference), str(row.prediction), "Pending listening review"]
            for cell, value, width in zip(cells, values, error_widths):
                cell.width = Inches(width)
                set_cell_text(cell, value, size=8)
        format_data_table(error_table, document, error_widths, header=True, font_size=8)

    section_heading(document, "Section 6. Engineering Trade-offs and Conclusion", page_break=True)
    reduced_deltas = []
    for category in ("noise", "music", "speech"):
        for snr in (0, 10, 20):
            noisy = condition_row(summary, f"{category}_{snr}dB")
            reduced = condition_row(summary, f"{category}_reduced_{snr}dB")
            if noisy is not None and reduced is not None:
                reduced_deltas.append((category, snr, float(reduced.corpus_wer) - float(noisy.corpus_wer)))
    if reduced_deltas:
        best_delta = min(reduced_deltas, key=lambda item: item[2])
        worst_delta = max(reduced_deltas, key=lambda item: item[2])
        delta_parts = []
        if best_delta[2] < 0:
            delta_parts.append(f"The largest observed WER decrease was {abs(best_delta[2]):.4f} at {best_delta[0]}, {best_delta[1]} dB.")
        else:
            delta_parts.append("No paired reduced condition had lower WER than its unprocessed mixture.")
        if worst_delta[2] > 0:
            delta_parts.append(f"The largest observed WER increase was {worst_delta[2]:.4f} at {worst_delta[0]}, {worst_delta[1]} dB.")
        else:
            delta_parts.append("No paired reduced condition had higher WER than its unprocessed mixture.")
        delta_parts.append("A negative WER change means lower error after reduction.")
        delta_text = " ".join(delta_parts)
    else:
        delta_text = "The supplied summary does not contain paired noisy and reduced conditions for a direct WER comparison."
    body_paragraph(document, delta_text)
    body_paragraph(document,
        f"For this run, the best corpus WER condition was {best.condition} ({float(best.corpus_wer):.4f}); "
        f"the clean baseline was {clean_wer:.4f}. Figure 4 and Table 1 show the accompanying latency/RTF trade-off. "
        "These are measurements for one compact English model, the selected dev-clean utterances, and the "
        "recorded MUSAN excerpts. They should not be generalized beyond this setup.")
    body_paragraph(document,
        "Recommended next steps are to (1) complete listening-based analysis for the rows in Table 2, "
        "(2) repeat evaluation with a larger and more varied speech/noise sample, and (3) profile inference "
        "on the target deployment hardware before choosing a runtime configuration. These steps extend the "
        "evidence available here without presuming an error cause or a deployment outcome.")

    section_heading(document, "References and Appendix", page_break=True)
    references = [
        "[1] V. Panayotov, G. Chen, D. Povey, and S. Khudanpur, \"LibriSpeech: An ASR Corpus Based on Public Domain Audio Books,\" Proc. IEEE ICASSP, 2015, pp. 5206-5210, doi:10.1109/ICASSP.2015.7178964.",
        "[2] D. Snyder, G. Chen, and D. Povey, \"MUSAN: A Music, Speech, and Noise Corpus,\" arXiv:1510.08484, 2015.",
        "[3] A. Radford et al., \"Robust Speech Recognition via Large-Scale Weak Supervision,\" arXiv:2212.04356, 2022.",
        "[4] B. McFee et al., \"librosa: Audio and Music Signal Analysis in Python,\" Proc. 14th Python in Science Conf. (SciPy), 2015, doi:10.25080/Majora-7B98E3ED-003.",
        "[5] PyTorch documentation, https://docs.pytorch.org/docs/stable/.",
        "[6] noisereduce software, https://github.com/timsainb/noisereduce.",
        "[7] JiWER documentation, https://github.com/jitsi/jiwer.",
        "[8] Hugging Face Datasets documentation, https://huggingface.co/docs/datasets/.",
        "[9] NumPy, https://numpy.org/doc/; SciPy, https://docs.scipy.org/doc/scipy/; SoundFile, https://python-soundfile.readthedocs.io/; pandas, https://pandas.pydata.org/docs/; Matplotlib, https://matplotlib.org/stable/. Package versions are recorded in results/metadata.json.",
    ]
    for reference in references:
        body_paragraph(document, reference)
    body_paragraph(document,
        "Appendix A. Reproducibility details are in results/metadata.json; per-utterance references and "
        "predictions are in results/predictions.csv; condition-level metrics are in results/condition_summary.csv. "
        "The shareable code repository / Colab URL must be added to the title page before submission.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)
    print(f"DOCX report written: {output_path}")
    if export_pdf:
        converter = shutil.which("soffice") or shutil.which("libreoffice")
        if converter is None:
            print("PDF export unavailable: LibreOffice was not found. Open the DOCX in Word and use Save As > PDF.")
        else:
            result = subprocess.run(
                [converter, "--headless", "--convert-to", "pdf", "--outdir", str(output_path.parent), str(output_path)],
                capture_output=True, text=True,
            )
            pdf_path = output_path.with_suffix(".pdf")
            if result.returncode == 0 and pdf_path.exists():
                print(f"PDF report written: {pdf_path}")
            else:
                print(f"PDF export failed. DOCX is available. Details: {result.stderr or result.stdout}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(os.environ.get("SRCS_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
    parser.add_argument("--project-root", type=Path, default=default_root,
                        help="Project folder (use the mounted Drive path in Colab)")
    parser.add_argument("--output", type=Path, default=None, help="DOCX output path; defaults to reports/SRCS_Case_Study_DRAFT.docx")
    parser.add_argument("--pdf", action="store_true", help="Also export PDF when LibreOffice is installed")
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output else project_root / "reports/SRCS_Case_Study_DRAFT.docx"
    build_report(project_root, output, export_pdf=args.pdf)


if __name__ == "__main__":
    main()
