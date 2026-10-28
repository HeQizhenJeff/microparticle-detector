"""Smoke test: detection precision / recall on a synthetic frame.

The synthetic generator draws spheres of known centres and radii, so we have a
perfect ground truth. A detection counts as a true positive when its centre is
within half a truth radius of a truth centre.

Thresholds are deliberately loose. They are a *regression guard* (does the chain
still run and still find most spheres?), not a performance claim. The published
precision / recall figures are the ones measured on annotated real frames and
are documented in the README.

Usage:
    python tests/check_synthetic.py --truth synth/truth.csv \
                                   --pred out/objects_classified.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path


def read_truth(path: Path) -> dict[str, list[tuple[float, float, float]]]:
    out: dict[str, list[tuple[float, float, float]]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["frame"], []).append(
                (float(row["cx"]), float(row["cy"]), float(row["r"]))
            )
    return out


def read_pred(path: Path) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        # objects_classified.csv carries the de-duplicated centre in cx2/cy2
        xk = "cx2" if "cx2" in cols else "cx"
        yk = "cy2" if "cy2" in cols else "cy"
        for row in reader:
            if row.get("cls", "kept") != "kept":
                continue
            out.setdefault(row["frame"], []).append((float(row[xk]), float(row[yk])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--min-precision", type=float, default=0.85)
    ap.add_argument("--min-recall", type=float, default=0.60)
    args = ap.parse_args()

    truth = read_truth(Path(args.truth))
    pred = read_pred(Path(args.pred))

    tp = fn = fp = 0
    for frame, spheres in truth.items():
        dets = pred.get(frame, [])
        used: set[int] = set()
        for x, y in dets:
            best = None
            for i, (tx, ty, tr) in enumerate(spheres):
                if i in used:
                    continue
                d = math.hypot(x - tx, y - ty)
                if d < 0.5 * tr and (best is None or d < best[0]):
                    best = (d, i)
            if best is None:
                fp += 1
            else:
                used.add(best[1])
                tp += 1
        fn += len(spheres) - len(used)

    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    print(f"truth={tp + fn}  detections={tp + fp}  TP={tp}  FP={fp}  FN={fn}")
    print(f"precision={precision:.1%}  recall={recall:.1%}")

    ok = precision >= args.min_precision and recall >= args.min_recall
    if not ok:
        print(
            f"FAIL: expected precision >= {args.min_precision:.0%} and "
            f"recall >= {args.min_recall:.0%}",
            file=sys.stderr,
        )
    else:
        print("OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
