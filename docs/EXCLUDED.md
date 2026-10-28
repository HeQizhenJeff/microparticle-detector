# What is deliberately excluded from this repository

The source project is a working laboratory pipeline, not a public package. Files were
**isolated, not deleted** — the original directory is untouched and still used daily.
This note records what was left out and why, so the decision can be re-checked later.

## Excluded: contains credentials or unrelated functionality

| file | reason |
|---|---|
| `s1_mimo_audio.py` | reads `MIMO_API_KEY` from the environment or `keys.json`; this is the speech-to-text half of the workflow and has nothing to do with particle detection |
| `s1_rename.py`, `s1_transcribe*.py`, `s1b_ai_audio.py`, `s2s3_batch.py`, `s_check_keys.py` | the ASR / transcript pipeline; separate product, separate dependencies (FunASR, ModelScope), and out of scope |

## Excluded: duplicates and dead code

| file | reason |
|---|---|
| `s6_frame_gate_v02_backup.py` | superseded backup copy |
| `s1_transcribe_dual_冲突文件_何其臻_20260923162907.py` | sync-conflict artefact |
| `__pycache__/` | build cache |

## Excluded: needs proprietary inputs

| file | reason |
|---|---|
| `s6_ring_width.py` | singles out one circle for interactive rim-width analysis; usable, but it expects a local frame layout and a circle list that only exists inside our workspace |
| `s6_triage.py`, `s6_size_measure.py` | the older DoG + watershed branch. It enforces the size calibration against two external particle-size standards; without those reference files it cannot run, and shipping a detector that silently skips its own calibration would be misleading |

`gold_regression()` inside `s6_b_gate.py` is kept but needs external annotation files; it
is an internal regression harness, not part of the public path. It reads its frame
directory from the `MPD_GOLD_FRAMES` environment variable.

## Excluded: data

No laboratory microscopy frames are included. Reasons:

1. The images are institutional data; release requires the PI's approval.
2. A manuscript describing the microspheres is in preparation, so image release is
   deferred until the IP position is clear.

`examples/make_synthetic.py` produces a synthetic frame instead, so the pipeline can be
installed and verified without any real data.

## Deliberately kept

The Chinese code comments were kept as-is. Translating several thousand lines introduces
transcription errors into numeric thresholds for no functional gain; the README documents
the algorithm in English and the entry point has English docstrings.
