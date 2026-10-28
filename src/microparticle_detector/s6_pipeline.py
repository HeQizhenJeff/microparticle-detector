#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""s6_pipeline — one-command end-to-end microparticle detection.

Runs the full detection chain over a directory of microscopy frames:

    ring_channel -> clump_rescue -> merge/dedup -> B-gate -> P0..P3 gates -> [annotation]

Design notes
------------
* Every stage is an independent script in this package and can still be run
  alone; this file only sequences them and shares the intermediate files.
* Stage order matters. Candidates are concatenated as
  ``kept (optional) -> ring -> rescue`` and de-duplicated with
  ``dist < 0.7 * (r1 + r2)``, which is the same rule used to build the
  reference outputs. First one wins, so earlier (higher-confidence) sources
  survive.
* ``frame_gate`` is a quality-control step (does this frame deserve to be
  counted at all); it does not change the detections, so it is opt-in.

Usage
-----
    python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out

    # with a pre-existing baseline (e.g. from another detector)
    python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out \
        --baseline kept.csv --workers 4 --annotate

frames/          *.jpg / *.png / *.tif
kept.csv         optional, columns: frame,cx,cy,r

Outputs in --out:
    ring.csv                 dark-ring channel candidates
    extras.csv               five-source rescue candidates
    circles.csv              merged, de-duplicated detections (the answer)
    objects.csv              per-circle B-gate measurements
    objects_classified.csv   objects.csv + cls column (kept/giant/grow/dup/resid/breject)
    summary.json             counts, parameters, timings
    annot/                   optional annotated overlays (jpg)
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

DEDUP_FRAC = 0.7          # same rule as the reference pipeline


# ---------------------------------------------------------------- utilities
def load_module(name: str):
    """Load a sibling script as a module (they are not a real package)."""
    spec = importlib.util.spec_from_file_location(name, str(HERE / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_circles(path: Path):
    """Read a CSV with any of the accepted column spellings."""
    out = []
    if path is None or not Path(path).exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            x = r.get("cx", r.get("x"))
            y = r.get("cy", r.get("y"))
            rr = r.get("r", r.get("radius"))
            if x is None or y is None or rr is None:
                continue
            try:
                out.append(dict(frame=r.get("frame", ""), x=float(x), y=float(y),
                                r=float(rr), src=r.get("src", "")))
            except ValueError:
                continue
    return out


def dedup(circles, frac=DEDUP_FRAC):
    """Greedy centre-distance de-duplication; earlier entries win."""
    out = []
    for c in circles:
        if not any(math.hypot(c["x"] - q["x"], c["y"] - q["y"])
                   < frac * (c["r"] + q["r"]) for q in out):
            out.append(c)
    return out


def run(cmd, label):
    t0 = time.time()
    print(f"\n[{label}] {' '.join(str(c) for c in cmd[1:])}", flush=True)
    code = subprocess.call(cmd)
    if code != 0:
        raise SystemExit(f"{label} failed with exit code {code}")
    dt = time.time() - t0
    print(f"[{label}] done in {dt:.1f}s", flush=True)
    return dt


# --------------------------------------------------- stage 5: B-gate in batch
def _process_frame(job):
    """Run the B gate over every circle of one frame. Module-level so that
    multiprocessing (spawn) can pickle it."""
    frame_path, frame_name, seg, circles = job
    import numpy as np
    from PIL import Image

    bg = load_module("s6_b_gate")
    g = np.asarray(Image.open(frame_path).convert("L"), dtype=np.float32)
    rows = []
    for c in circles:
        res = bg.evaluate(g, c["x"], c["y"], c["r"])
        d_b = 2.0 * res["R2"] if res.get("R2") is not None else float("nan")
        rows.append(dict(seg=seg, frame=frame_name,
                         x=round(c["x"], 1), y=round(c["y"], 1),
                         d_M=round(2.0 * c["r"], 1), d_B=round(d_b, 1),
                         ok=res["ok"], rn2=res.get("rn2"),
                         cx2=res.get("cx2"), cy2=res.get("cy2"),
                         n=res.get("n"), src=c.get("src", "")))
    return rows


def write_objects(rows, path):
    cols = ["seg", "frame", "x", "y", "d_M", "d_B", "ok", "rn2", "cx2", "cy2", "n", "src"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_classified(rows, path):
    cols = ["seg", "frame", "x", "y", "d_M", "d_B", "ok", "rn2", "cx2", "cy2", "cls", "src"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="End-to-end microparticle detection over a folder of frames.")
    ap.add_argument("--frames", required=True, help="directory of frames")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--baseline", default=None,
                    help="optional baseline circles CSV (frame,cx,cy,r) to merge in")
    ap.add_argument("--seg", default=None, help="segment label (default: frame dir name)")
    ap.add_argument("--workers", type=int, default=1,
                    help="processes for the B-gate stage (memory-bound; 4 is typical)")
    ap.add_argument("--limit", type=int, help="only the first N frames (smoke test)")
    ap.add_argument("--gate", action="store_true",
                    help="also run the frame-level focus gate (QC only)")
    ap.add_argument("--annotate", action="store_true", help="write annotated overlays to out/annot (jpg)")
    ap.add_argument("--no-reject", action="store_true",
                    help="with --annotate: do not draw the thin cyan outlines of "
                         "candidates rejected by the B gate (they can be hundreds "
                         "per frame and make the overlay hard to read)")
    ap.add_argument("--um-per-px", type=float, default=0.0762,
                    help="spatial calibration for the annotated scale bar")
    ap.add_argument("--bar-um", type=float, default=10.0, help="scale bar length in um")
    ap.add_argument("--skip-ring", action="store_true", help="skip the dark-ring channel")
    ap.add_argument("--skip-rescue", action="store_true", help="skip the rescue channel")
    ap.add_argument("--prom-min", type=float, default=None,
                    help="override the B-gate prominence floor PROM_MIN (default 12). "
                         "This is the first parameter to re-calibrate when moving to a "
                         "different imaging modality: phase-contrast dark rings in our "
                         "data give ~80 grey levels of prominence, whereas absorbing "
                         "solid spheres give only 12-30 and are mostly rejected")
    a = ap.parse_args()

    t_start = time.time()
    frdir = Path(a.frames).resolve()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    seg = a.seg or frdir.name

    frames = sorted(p for p in frdir.iterdir() if p.suffix.lower() in IMG_EXT)
    if a.limit:
        frames = frames[:a.limit]
    if not frames:
        raise SystemExit(f"no frames found in {frdir} (looked for {sorted(IMG_EXT)})")
    print(f"s6_pipeline: {len(frames)} frames | seg={seg} | out={out}", flush=True)

    timings = {}
    py = sys.executable
    pkg_dir = str(HERE)

    # ---- stage 0 (optional): frame-level focus gate -----------------------
    if a.gate:
        timings["frame_gate"] = run(
            [py, f"{pkg_dir}/s6_frame_gate.py", str(frdir), "--out", str(out / "gate")],
            "0/6 frame gate")

    # ---- stage 1: dark-ring channel --------------------------------------
    ring_csv = out / "ring.csv"
    if a.skip_ring:
        ring_csv.write_text("frame,cx,cy,r\n", encoding="utf-8")
        timings["ring_channel"] = 0.0
    else:
        cmd = [py, f"{pkg_dir}/s6_ring_channel.py", "--frames", str(frdir),
               "--out", str(ring_csv)]
        if a.limit:
            cmd += ["--limit", str(a.limit)]
        timings["ring_channel"] = run(cmd, "1/6 ring channel")

    # ---- stage 2: five-source rescue -------------------------------------
    extras_csv = out / "extras.csv"
    if a.skip_rescue:
        extras_csv.write_text("frame,cx,cy,r\n", encoding="utf-8")
        timings["clump_rescue"] = 0.0
    else:
        # The rescue channel de-duplicates against what is already known.
        base_for_rescue = out / "_baseline_for_rescue.csv"
        merged_pre = dedup(read_circles(Path(a.baseline) if a.baseline else None)
                           + read_circles(ring_csv))
        with open(base_for_rescue, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frame", "cx", "cy", "r"])
            for c in merged_pre:
                w.writerow([c["frame"], f"{c['x']:.1f}", f"{c['y']:.1f}", f"{c['r']:.1f}"])
        cmd = [py, f"{pkg_dir}/s6_clump_rescue.py", "--frames", str(frdir),
               "--baseline", str(base_for_rescue), "--out", str(extras_csv)]
        if a.workers > 1:
            cmd += ["--workers", str(a.workers)]
        if a.prom_min is not None:
            cmd += ["--prom-min", str(a.prom_min)]
        if a.limit:
            cmd += ["--limit", str(a.limit)]
        timings["clump_rescue"] = run(cmd, "2/6 rescue channel")

    # ---- stage 3: merge + de-duplicate -----------------------------------
    t0 = time.time()
    kept = read_circles(Path(a.baseline) if a.baseline else None)
    ring = read_circles(ring_csv)
    extras = read_circles(extras_csv)
    for c in ring:
        c["src"] = c["src"] or "ring"
    for c in extras:
        c["src"] = c["src"] or "rescue"

    # de-duplication is per frame
    by_frame = {}
    for c in kept + ring + extras:
        by_frame.setdefault(c["frame"], []).append(c)
    circles = []
    for name in sorted(by_frame):
        circles.extend(dedup(by_frame[name]))

    # regroup after de-duplication: the B gate must see each circle exactly once
    circles_by_frame = {}
    for c in circles:
        circles_by_frame.setdefault(c["frame"], []).append(c)

    circles_csv = out / "circles.csv"
    with open(circles_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "cx", "cy", "r", "src"])
        for c in circles:
            w.writerow([c["frame"], f"{c['x']:.1f}", f"{c['y']:.1f}", f"{c['r']:.1f}", c["src"]])
    timings["merge"] = time.time() - t0
    print(f"\n[3/6 merge] {len(kept)} baseline + {len(ring)} ring + {len(extras)} rescue "
          f"-> {len(circles)} circles", flush=True)

    # ---- stage 4: B gate over every circle --------------------------------
    name_of = {f.name: f for f in frames}
    stem_of = {f.stem: f for f in frames}
    jobs = []
    for name in sorted(circles_by_frame):
        path = name_of.get(name) or stem_of.get(Path(name).stem)
        if path is None:                      # frame not in this directory
            continue
        jobs.append((str(path), path.name, seg,
                     [dict(x=c["x"], y=c["y"], r=c["r"], src=c["src"])
                      for c in circles_by_frame[name]]))

    t0 = time.time()
    print(f"\n[4/6 B-gate] {sum(len(j[3]) for j in jobs)} circles over {len(jobs)} frames "
          f"(workers={a.workers})", flush=True)
    if a.workers > 1:
        from multiprocessing import Pool
        with Pool(a.workers) as pool:
            chunks = pool.map(_process_frame, jobs)
    else:
        chunks = [_process_frame(j) for j in jobs]
    objects = [r for ch in chunks for r in ch]
    objects_csv = out / "objects.csv"
    write_objects(objects, objects_csv)
    timings["b_gate"] = time.time() - t0

    # ---- stage 5: P0..P3 gates -------------------------------------------
    t0 = time.time()
    gates = load_module("s6_size_gates")
    gated = gates.apply_gates(objects, has_fit=True)
    classified_csv = out / "objects_classified.csv"
    write_classified(gated, classified_csv)
    counts = {}
    for r in gated:
        counts[r["cls"]] = counts.get(r["cls"], 0) + 1
    timings["gates"] = time.time() - t0
    print(f"\n[5/6 gates] " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())),
          flush=True)

    # ---- stage 6 (optional): annotated images ----------------------------
    if a.annotate:
        t0 = time.time()
        annot_dir = out / "annot"
        annot_dir.mkdir(exist_ok=True)
        frames_with_kept = sorted({r["frame"] for r in gated})
        for name in frames_with_kept:
            cmd = [py, f"{pkg_dir}/s6_size_annot.py", "--csv", str(classified_csv),
                   "--seg", seg, "--frame", name, "--framedir", str(frdir),
                   "--out", str(annot_dir), "--um-per-px", str(a.um_per_px),
                   "--bar-um", str(a.bar_um)]
            if a.no_reject:
                cmd.append("--no-reject")
            run(cmd, f"6/6 annot {name}")
        timings["annotate"] = time.time() - t0

    # ---- summary ----------------------------------------------------------
    total = time.time() - t_start
    summary = dict(
        frames=len(frames), seg=seg,
        circles=len(circles),
        by_source={s: sum(1 for c in circles if c["src"] == s)
                   for s in sorted({c["src"] for c in circles})},
        classes=counts,
        kept=counts.get("kept", 0),
        parameters=dict(dedup_frac=DEDUP_FRAC, um_per_px=a.um_per_px,
                        bar_um=a.bar_um, workers=a.workers,
                        skip_ring=a.skip_ring, skip_rescue=a.skip_rescue),
        timings={k: round(v, 1) for k, v in timings.items()},
        wall_seconds=round(total, 1),
        seconds_per_frame=round(total / len(frames), 2),
    )
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== summary ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nDone in {total:.1f}s ({total / len(frames):.1f}s/frame).")


if __name__ == "__main__":
    main()
