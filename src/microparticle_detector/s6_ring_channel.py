# -*- coding: utf-8 -*-
"""S6-R 暗环通道（ring channel，2026-10-16 落正本）

定位：**对象级补充检出**——在现有管线（DoG 种子 → B 门 → P0–P3）之外，
从「暗环像素」直接提圆，救回被粘连吞没 / 半漏的球。
设计哲学（用户 2026-10-15 拍板）：人不看亮芯，只看暗环；
且暗环思路对非圆球（哑铃、褶皱、MOF/COF 晶体）更通用。

机制（纯增量，只加不删）：
  1) 黑帽形态学（闭运算 − 原图）提「细暗线」，再要求像素比局部高斯背景暗
     → 黑帽天然滤掉大块暗区（团缝/污渍），只留环宽量级的细暗结构；
  2) 在掩码上跑 HoughCircles → 每段暗环弧各提一个候选圆；
  3) 与基线 kept 去重：dist < DEDUP_FRAC*(r_new+r_old) 视为已有，丢弃；
  4) 全部候选过 **B 门（s6_b_gate.evaluate）**——安全网不变，真暗环才放行。

战绩（2026-10-16）：
  - 138 格金标准回归（14_2h 45 + 13_2h 47 + small 46）：**真泄漏 0、坏格救回 9**
    （重判口径=覆盖被标注 fix 球，`_rejudge_leaks.py`），好格外救回 17 → 总救回 ≈26；
    DSC 2184 行重放一致（通道不改既有判定）。
  - DSC_2307 四帧：kept 基线之外新增 661 个过门圈；用户 105 漏检圈覆盖
    C 32/45、D 20/26、E 12/26、F 6/8（合计 67%）；同球双圈 <5%、零重复。
  - frame_00044 极端例：kept 仅 54 → 通道新增 497，目检几乎全为真球（生产管线在该帧严重漏检）。
⚠️ 已知边界：① 只救「暗环还在」的球——两球完全糊成一坨（8 字腰看不清）救不动（E 类残余 14 个）；
② 圈数会明显变多（含部分同一球的小圈），下游统计前须过 P2 去重 / 人工抽查；
③ 参数为 14_2h/13_2h/DSC 三批校准，跨批次曝光差异未验，改参先跑金标准回归。

用法：
  python s6_ring_channel.py --frames <帧目录> [--baseline <kept.csv>] [--out extras.csv]
      [--annot-dir <目录>] [--param2 26] [--min-dist 9] [--min-r 6] [--max-r 30]
      [--ridge-sd 0.6] [--kernel 9] [--dedup 0.7] [--limit N]
  baseline CSV 需含 frame 列；有 cls 列则只取 cls==kept；半径取 d_B/2（无则 d/2）；
  圆心优先 cx2/cy2（无则 x/y）。输出 extras.csv 列：frame,cx,cy,r。
"""
import argparse
import csv
import math
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

# accepted frame extensions (public build: no longer assumes frame_*.jpg naming)
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

HERE = Path(__file__).resolve().parent
import importlib.util as _ilu
_s = _ilu.spec_from_file_location("bg", str(HERE / "s6_b_gate.py"))
BG = _ilu.module_from_spec(_s)
_s.loader.exec_module(BG)

# ---- 默认参数（=原型 _proto_ring.py，三批视频校准值，勿随手改；改前跑 138 格回归）----
RIDGE_SD = 0.6      # 细暗线阈值 = ridge_sd * σ（σ=背景稳健尺度）
BG_SIG = 31         # 局部背景高斯 σ
KERNEL = 9          # 黑帽结构元直径（≈环宽量级）
MIN_R, MAX_R = 6, 30
HOUGH_P2 = 26
MIN_DIST = 9
DEDUP_FRAC = 0.7


def load_baseline(path):
    """baseline CSV → {frame: [(cx,cy,r), …]}"""
    base = {}
    if not path:
        return base
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if "cls" in row and row["cls"] != "kept":
                continue
            if "d_B" in row and not row["d_B"]:
                continue
            frame = row.get("frame")
            if not frame:
                continue
            cx = float(row["cx2"]) if row.get("cx2") else float(row["x"])
            cy = float(row["cy2"]) if row.get("cy2") else float(row["y"])
            if cx != cx or cy != cy:          # NaN 兜底
                cx, cy = float(row["x"]), float(row["y"])
            if row.get("d_B"):
                r = float(row["d_B"]) / 2
            elif row.get("d"):
                r = float(row["d"]) / 2
            else:
                continue
            base.setdefault(frame, []).append((cx, cy, r))
    return base


def ring_candidates(g, ridge_sd=RIDGE_SD, kernel=KERNEL, p2=HOUGH_P2,
                    min_dist=MIN_DIST, min_r=MIN_R, max_r=MAX_R):
    """灰度图 → 黑帽暗环 Hough 候选圆 [(cx,cy,r), …]"""
    gf = g.astype(np.float32)
    bgm = cv2.GaussianBlur(gf, (0, 0), BG_SIG)
    sd = float(np.median(np.abs(gf - bgm))) * 1.4826
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    blackhat = cv2.morphologyEx(g.astype(np.uint8), cv2.MORPH_CLOSE, k).astype(np.float32) - gf
    mask = ((blackhat > ridge_sd * sd) & (gf < bgm)).astype(np.uint8) * 255
    circ = cv2.HoughCircles(mask, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min_dist,
                            param1=60, param2=p2, minRadius=min_r, maxRadius=max_r)
    return [] if circ is None else [tuple(map(float, c)) for c in circ[0]]


def dedupe_vs(cands, base_list, dedup=DEDUP_FRAC):
    out = []
    for (cx, cy, r) in cands:
        if any(math.hypot(cx - bx, cy - by) < dedup * (r + br)
               for (bx, by, br) in base_list):
            continue
        out.append((cx, cy, r))
    return out


def run_frame(g, base_list, **params):
    """一帧：候选 → 去重 → B 门 → (过门圈, 拒因计数, 候选数)"""
    cands = ring_candidates(g, **{k: v for k, v in params.items()
                                  if k in ("ridge_sd", "kernel", "p2",
                                           "min_dist", "min_r", "max_r")})
    new = dedupe_vs(cands, base_list, dedup=params.get("dedup", DEDUP_FRAC))
    passed, rejected = [], Counter()
    for (cx, cy, r) in new:
        try:
            res = BG.evaluate(g, cx, cy, r)
        except Exception:
            res = dict(ok=False, reason="exc")
        if res.get("ok"):
            passed.append((res["cx2"], res["cy2"], res["R2"]))
        else:
            rejected[res.get("reason") or "?"] += 1
    return passed, rejected, len(cands), len(new)


def main():
    ap = argparse.ArgumentParser(description="S6-R 暗环通道（增量检出）")
    ap.add_argument("--frames", required=True, help="帧目录")
    ap.add_argument("--baseline", default=None, help="既有 kept CSV（去重用）")
    ap.add_argument("--out", default=None, help="输出 CSV（默认 <帧目录>/_ring_extras.csv）")
    ap.add_argument("--annot-dir", default=None, help="可选：叠加图输出目录")
    ap.add_argument("--param2", type=int, default=HOUGH_P2)
    ap.add_argument("--min-dist", type=int, default=MIN_DIST)
    ap.add_argument("--min-r", type=int, default=MIN_R)
    ap.add_argument("--max-r", type=int, default=MAX_R)
    ap.add_argument("--ridge-sd", type=float, default=RIDGE_SD)
    ap.add_argument("--kernel", type=int, default=KERNEL)
    ap.add_argument("--dedup", type=float, default=DEDUP_FRAC)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 帧（冒烟用）")
    a = ap.parse_args()

    frdir = Path(a.frames)
    frames = sorted(p.name for p in frdir.iterdir()
                    if p.suffix.lower() in IMG_EXT)
    if a.limit:
        frames = frames[:a.limit]
    if not frames:
        raise SystemExit(f"no image files in {frdir} (looked for {list(IMG_EXT)})")
    base = load_baseline(a.baseline)
    out_path = Path(a.out) if a.out else frdir / "_ring_extras.csv"
    params = dict(ridge_sd=a.ridge_sd, kernel=a.kernel, p2=a.param2,
                  min_dist=a.min_dist, min_r=a.min_r, max_r=a.max_r,
                  dedup=a.dedup)

    rows, tot = [], Counter()
    t_all = time.time()
    for fr in frames:
        t0 = time.time()
        g = BG.load_gray(frdir / fr).astype(np.float32)
        passed, rejected, n_cand, n_new = run_frame(g, base.get(fr, []), **params)
        dt = time.time() - t0
        rows += [(fr, cx, cy, r) for (cx, cy, r) in passed]
        tot["cand"] += n_cand
        tot["dedup"] += n_new
        tot["pass"] += len(passed)
        tot["base"] += len(base.get(fr, []))
        print(f"[{fr}] 基线{len(base.get(fr, []))} 候选{n_cand} → 去重后{n_new} → "
              f"B过 {len(passed)}  拒{dict(rejected)}  ({dt:.1f}s)", flush=True)
        if a.annot_dir:
            adir = Path(a.annot_dir)
            adir.mkdir(parents=True, exist_ok=True)
            canvas = cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            for (bx, by, br) in base.get(fr, []):
                cv2.circle(canvas, (int(bx), int(by)), int(br), (200, 200, 200), 1, cv2.LINE_AA)
            for (cx, cy, r) in passed:
                cv2.circle(canvas, (int(cx), int(cy)), int(r), (0, 255, 255), 2, cv2.LINE_AA)
            cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 26), (0, 0, 0), -1)
            cv2.putText(canvas, f"{fr} ring-new {len(passed)} (grey=baseline)",
                        (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
            cv2.imwrite(str(adir / f"_ring_{Path(fr).stem}.jpg"), canvas,
                        [cv2.IMWRITE_JPEG_QUALITY, 88])

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "cx", "cy", "r"])
        for r in rows:
            w.writerow([r[0], round(r[1], 2), round(r[2], 2), round(r[3], 2)])
    print(f"\n=== {len(frames)} 帧 | 基线 {tot['base']} | Hough 候选 {tot['cand']} | "
          f"去重后 {tot['dedup']} | B 过门新增 {tot['pass']} | "
          f"{time.time()-t_all:.1f}s ===")
    print(f"-> {out_path}")
    print("注：新增圈含同一球的小圈，下游统计前须过 P2 去重 / 抽查。")


if __name__ == "__main__":
    main()
