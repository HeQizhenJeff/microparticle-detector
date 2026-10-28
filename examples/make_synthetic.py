#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate a synthetic brightfield-like frame so you can test the pipeline
without any real microscopy data.

The model is crude but captures what the detector actually keys on:
a bright disc, a darker rim, mild defocus blur, and sensor noise.

    python examples/make_synthetic.py --out examples/synthetic --n 180 --seed 7
    python -m microparticle_detector.s6_pipeline --frames examples/synthetic --out /tmp/out

A ``truth.csv`` with the true centres and radii is written next to the image,
so you can compute your own precision/recall after running the detector.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--n", type=int, default=180, help="number of spheres")
    ap.add_argument("--size", type=int, default=1024, help="image side in pixels")
    ap.add_argument("--r-min", type=float, default=9.0)
    ap.add_argument("--r-max", type=float, default=14.0)
    ap.add_argument("--sigma", type=float, default=1.8, help="defocus blur (px)")
    ap.add_argument("--noise", type=float, default=5.0, help="gaussian noise sd")
    ap.add_argument("--name", default="synth_00000.jpg")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    S = a.size
    img = np.full((S, S), 105.0, np.float32)      # background grey
    yy, xx = np.mgrid[0:S, 0:S]

    placed = []
    tries = 0
    while len(placed) < a.n and tries < a.n * 200:
        tries += 1
        r = rng.uniform(a.r_min, a.r_max)
        x = rng.uniform(r + 2, S - r - 2)
        y = rng.uniform(r + 2, S - r - 2)
        # spheres may touch but not substantially overlap
        if any(np.hypot(x - px, y - py) < 1.6 * max(r, pr) for px, py, pr in placed):
            continue
        placed.append((x, y, r))

        d = np.hypot(xx - x, yy - y)
        disc = d <= r
        rim = (d > r * 0.82) & (d <= r * 1.06)
        # bright interior, dark rim: the signature the ring channel looks for
        img[disc] = np.maximum(img[disc], 165.0)
        img[rim] = np.minimum(img[rim], 62.0)

    # defocus + noise
    from scipy.ndimage import gaussian_filter
    img = gaussian_filter(img, a.sigma)
    img = img + rng.normal(0, a.noise, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)

    Image.fromarray(img).save(out / a.name, quality=95)

    truth = out / "truth.csv"
    with open(truth, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "cx", "cy", "r"])
        for x, y, r in placed:
            w.writerow([a.name, f"{x:.1f}", f"{y:.1f}", f"{r:.1f}"])

    print(json.dumps(dict(image=str(out / a.name), spheres=len(placed),
                          truth=str(truth), size=S), indent=2))


if __name__ == "__main__":
    main()
