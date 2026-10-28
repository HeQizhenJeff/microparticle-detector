# microparticle-detector

<!-- TODO before publishing: replace YOURNAME with your GitHub username -->
[![CI](https://github.com/YOURNAME/microparticle-detector/actions/workflows/ci.yml/badge.svg)](https://github.com/YOURNAME/microparticle-detector/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

Circle detection and sizing for **dense, label-free brightfield microscopy of colloidal
microspheres** — no training, no GPU, every detection geometrically auditable.

```
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out
```

---

## Why another particle counter

Deep-learning segmenters (Cellpose, StarDist, YOLO-seg) now count polymer particles very
well — **provided you fine-tune them on your own images and have a GPU**. This package
targets the opposite corner:

| | Deep-learning route | This package |
|---|---|---|
| Training data needed | ~20–500 annotated images | **none** |
| Hardware | GPU recommended | **CPU only** (numpy + OpenCV) |
| Reproducibility | stochastic; weights required | **deterministic**, no weights |
| Failure diagnosis | "the network decided" | every circle passes an explicit geometric gate |
| Speed | ~31 FPS on an RTX 5090 | **~0.03 FPS** on a 4-core laptop |

That last row is the honest trade-off: this is a **slow but transparent** baseline, not a
replacement for a trained network. It is useful when you need a number today, when you
have no labelled data, or when you need to know *why* a circle was rejected.

---

## Installation

```bash
git clone <this-repo>
cd microparticle-detector
pip install -e .
# or just: pip install numpy opencv-python scipy pillow
```

Python >= 3.9. Dependencies: `numpy`, `opencv-python`, `scipy`, `pillow`.

---

## Quick start

```bash
# no data yet? generate a synthetic frame with known ground truth
python examples/make_synthetic.py --out ./synth --n 150 --seed 3

# full chain on a folder of frames
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out

# smoke test on one frame, with annotated overlays
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out \
    --limit 1 --annotate

# merge in circles from your own detector as a baseline
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out \
    --baseline kept.csv --workers 4

# 5–8 um spheres? pass your own calibration for the scale bar
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out \
    --annotate --um-per-px 0.0762 --bar-um 10
```

Input: a directory of `*.jpg / *.png / *.tif` frames, one frame per file.
`--baseline` is optional and expects `frame,cx,cy,r`.

### Outputs

| file | content |
|---|---|
| `circles.csv` | the answer: `frame,cx,cy,r,src` (de-duplicated) |
| `objects.csv` | every circle plus its B-gate measurements (`d_M,d_B,ok,rn2,cx2,cy2,n`) |
| `objects_classified.csv` | same plus `cls` = `kept / giant / grow / dup / resid / breject` |
| `ring.csv`, `extras.csv` | intermediate candidates from the two channels |
| `summary.json` | counts, parameters, per-stage timings |
| `annot/` | optional annotated PNGs with a scale bar |

`cls == "kept"` is the set that should enter a particle-size table. `breject` means the
candidate failed the ring-consistency gate; `giant` is a clump larger than one sphere;
`resid` is a poor circle fit; `dup` is a second measurement of the same sphere.

---

## How it works

Two independent candidate generators feed one shared verifier.

**1. Dark-ring channel (`s6_ring_channel`).** Out-of-focus and low-contrast spheres are
often visible *only* as a dark rim. A black-hat morphology isolates thin dark structures,
Hough turns each arc into a candidate circle, and everything must still survive the
verifier below. This channel is what rescues spheres that are half-buried in a clump.

**2. Rescue channel (`s6_clump_rescue`).** Five complementary seeds — sweep for dense
regions, bright-core seeds, a CLEAN iterative pass, a DAOPHOT-style layer, and an
optional doublet split — each proposing circles that the previous stage missed.

**3. Verifier (the "B gate", `s6_b_gate`).** For every candidate the gate samples the
image along 16 radial directions, finds the dark trough in each direction, rejects
directions without a trough, then fits a circle to the surviving trough points. A
candidate passes only if it has enough troughs, they span a long enough arc, the fit
residual is small, and the circle does not leave the frame. This is where most false
positives die, and every rejection carries a numeric reason.

**4. Series of size gates (`s6_size_gates`).** P0 removes clumps larger than one sphere,
P1 catches circles that grew onto a neighbouring sphere, P2 merges duplicate
measurements of the same sphere, P3 removes high-residual fits.

Merge rule: candidates are concatenated in the order `baseline → ring → rescue` and
de-duplicated when `centre distance < 0.7 * (r1 + r2)`, so higher-confidence sources win.

A note on the source: code comments are in Chinese (the project's working language); this
README and the docstrings of the entry point document the algorithm in English.

---

## Performance (and what those numbers mean)

Measured on **22 frames, 1920×1080, 7,038 annotated circles** of polystyrene and TPM
microspheres, 3.5–4 um nominal:

| metric | value |
|---|---|
| precision (of emitted circles) | **98.66 %** |
| recall (of annotated circles) | **98.21 %** |
| F1 | **98.44 %** |
| counting error, per frame | **MAE 5.1 particles** (median relative error **0.95 %**) |
| particles per frame | 151 – 685 (median 288) |
| runtime, 1 process | ~62 s/frame on a 4-core i7-8565U |
| runtime, `--workers 4` | ~32 s/frame (measured speed-up **1.94x**, memory-bound) |

**Read these numbers with four caveats, all of which we consider disqualifying for a
headline claim:**

1. **In-sample.** Every threshold in this code was tuned on these same 22 frames. This is
   a training-set number, not a held-out benchmark.
2. **Single annotator.** One person drew all reference circles; no inter-annotator
   agreement was computed.
3. **Recall is an upper bound.** Edge spheres were only partly annotated (the annotator
   stopped marking them), so the denominator is too small and true recall is lower.
4. **One instrument, one magnification, one lab.** Not validated across cameras,
   objectives or exposure settings.

The numbers are published here because hiding them would be worse. Treat them as "this
works on data like ours", not as a general accuracy guarantee.

### Sanity check on synthetic data

`examples/make_synthetic.py` draws spheres with a bright interior and a dark rim, adds
defocus blur and noise, and records the true centres. On 150 spheres (r = 9–14 px, packed
so that neighbours nearly touch):

| metric | value |
|---|---|
| precision | 99.2 % (132/133) |
| recall | **88.0 %** (132/150) |
| runtime | 1.5 min on one core, 1024×1024 |

Recall drops in this test because the synthetic spheres are packed close enough to
corrupt each other's rims — the same mechanism as failure mode 4. It is a useful reminder
that **88 % here and 98 % on our own data measure different scenes**, and neither is a
universal score. Run it on your own images before trusting any number on this page.

---

## Failure modes

These are the four ways this detector fails. They are documented because we could not fix
them, and because they tell you what to check first.

**1. Neck saddle.** A small circle (r ≈ 12 px) lands on the bright saddle between two
large spheres (r ≈ 55 px). The two neighbouring rims happen to form a closed dark ring
around it, so the verifier passes it. The circle is geometrically self-consistent and
physically wrong. No threshold tested separated these from real small spheres.

**2. Four-sphere void.** A circle is drawn in the empty gap of a 2×2 sphere arrangement.
The four rims together make a closed contour, giving a low residual and a long arc.

**3. Dark-core lobes.** A large sphere with a dark centre and a bright rim: the rim is cut
into 3–4 arcs by internal texture. Any rule that counts bright blobs inside a circle
("one circle should contain one object") will wrongly delete these. This is why the
bright-blob gate is opt-in for the rescue sources only and is **not** applied to the
baseline layer.

**4. Fully merged clumps.** Two spheres blurred into a single dumbbell with no visible
waist cannot be recovered by any ring-based method — the ring is physically gone.

Practical advice: the cheapest quality signal is **frame-level**. One badly defocused
frame in our set emitted 153 circles where neighbours emitted ~290, and supplied 4 of the
16 residual errors. Flag such frames and re-image them instead of tuning thresholds.

---

## Known limitations

- **Throughput.** ~0.03 FPS per core. For thousands of frames this is the wrong tool.
- **Per-batch calibration.** The radius range and the contrast thresholds assume a
  particular imaging setup. Changing exposure, objective or sphere size requires re-tuning
  against a small labelled set.
- **3D clumps.** Spheres stacked out of the focal plane are under-counted.
- **No size-distribution model.** The package reports circle diameters; converting them to
  a volume-weighted distribution is left to the user.
- **Chinese comments.** The code is documented in Chinese. Contributions translating the
  docstrings are welcome.

---

## Citation

If you use this code, cite the repository (DOI to be added on first release):

```
He Q., microparticle-detector: dark-ring circle detection for brightfield
microscopy of colloidal microspheres, v1.0.0, 2026.
```

## License

MIT. See `LICENSE`.

## Data availability

The annotated benchmark (22 frames + circle-level annotations) is **not** included in this
repository. Release is pending institutional approval; the images are laboratory data and
a related manuscript is in preparation. The code runs on any folder of frames without it.
