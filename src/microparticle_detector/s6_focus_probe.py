#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""s6_focus_probe — 逐对象对焦指标特征提取器（s6_frame_gate 的数据前端，2026-10-09 集成）

两个身份：
  ① s6_frame_gate.py 的数据前端——提取逐对象特征（d / dp / fwhm / slope / lv ...）供闸门判读；
  ② 对焦指标研究探针——优化轮次用于比较候选指标（原用途保留）。

背景（2026-10-05 用户反馈 ovl_zoom_14_2h.jpg）：
  0916 样品三档抽样图里
    * 50–60px 档（≈4µm）圈得对 —— 对焦球，暗环清晰
    * 32–40px 档（≈2.6–2.9µm）圈错 —— 离焦球，剖面量到内层结构 → 偏小
    * 14–20px 档（≈1.1–1.5µm）圈错 —— 球内尘点/微小离焦粒
  现行逐球离焦门（lv ≥ 0.5×帧内候选 LapVar 中位）拦不住，需要更强的指标。

候选指标（全部从「本实例径向剖面 + 掩码内灰度」免费获得）：
  fwhm   暗环半高全宽（px）      —— 离焦 → 暗环变宽变糊（最物理直接）
  slope  dp / fwhm（灰阶/px）    —— 边缘陡度，归一化对比度
  dp     暗度峰值（灰阶）        —— 对比度本身
  lv     掩码内 Laplacian 方差   —— 现行指标
  lvc    lv / contrast²          —— 对比度归一后的纹理/锐度
  hfr    掩码内 DoG(σ=3) std / 灰度 std —— 高频能量占比（离焦 → 低）

用法: python s6_focus_probe.py <frame_dir>... [--out feats.csv] [--limit N]
"""
import argparse
import csv
import importlib.util
from pathlib import Path

import numpy as np
import cv2
import scipy.ndimage as ndi

TRIAGE = str(Path(__file__).resolve().parent / "s6_triage.py")   # 相对本文件定位，防技能目录搬迁
spec = importlib.util.spec_from_file_location("t", TRIAGE)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def profile(patch, mask, cy, cx, rmax):
    H, W = patch.shape
    ys, xs = np.mgrid[0:H, 0:W]
    r = np.sqrt((ys - cy) ** 2 + (xs - cx) ** 2).astype(int)
    sel = mask & (r <= rmax)
    if sel.sum() < 20:
        return None
    cnt = np.bincount(r[sel], minlength=rmax + 1)
    s = np.bincount(r[sel], weights=patch[sel].astype(np.float64), minlength=rmax + 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        prof = np.where(cnt > 0, s / np.maximum(cnt, 1), np.nan)
    return prof


def dark_metrics(prof, bg):
    """→ (dp, rp, fwhm, slope)；失败返回全 nan。"""
    if prof is None:
        return (np.nan,) * 4
    valid = np.isfinite(prof)
    if valid.sum() < 6:
        return (np.nan,) * 4
    dark = np.where(valid, bg - prof, -np.nan)
    seg = dark.copy()
    seg[:1] = -np.nan
    if not np.any(np.isfinite(seg)):
        return (np.nan,) * 4
    rp = int(np.nanargmax(seg))
    dp = float(seg[rp])
    if not np.isfinite(dp) or dp <= 2.0:
        return np.nan, float(rp), np.nan, np.nan
    half = 0.5 * dp
    # 以 rp 为中心向两侧扩到半高（不足则到有效边界）
    lo = rp
    while lo - 1 >= 0 and np.isfinite(dark[lo - 1]) and dark[lo - 1] >= half:
        lo -= 1
    hi = rp
    while hi + 1 < len(dark) and np.isfinite(dark[hi + 1]) and dark[hi + 1] >= half:
        hi += 1
    fwhm = float(hi - lo + 1)
    slope = dp / fwhm if fwhm > 0 else np.nan
    return dp, float(rp), fwhm, slope


def run(dirs, out_csv, limit=None, k=0.0762):
    rows = []
    for d in dirs:
        dp_ = Path(d)
        frames = sorted([*dp_.glob("*.jpg"), *dp_.glob("*.png")],
                        key=t.natural_key)
        if limit:
            frames = frames[:limit]
        for fp in frames:
            g = t.load_gray(fp)
            m, hp, sd = t.structure_mask(g)
            if m is None:
                continue
            lab, n, how = t.split_instances(m)
            if n == 0:
                continue
            mb = m.astype(bool)
            bg = float(np.percentile(g[~mb], 90)) if (~mb).any() else float(np.percentile(g, 90))
            lapmap = cv2.Laplacian(g, cv2.CV_64F)
            gray_f = g.astype(np.float32)
            hp_small = cv2.GaussianBlur(gray_f, (0, 0), 1.0) - cv2.GaussianBlur(gray_f, (0, 0), 3.0)
            slices = ndi.find_objects(lab)
            for i, sl in enumerate(slices, start=1):
                if sl is None:
                    continue
                sub = lab[sl] == i
                a = int(sub.sum())
                if a < t.MIN_AREA_PX:
                    continue
                cnts, _ = cv2.findContours((sub * 255).astype(np.uint8),
                                           cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not cnts:
                    continue
                c = max(cnts, key=cv2.contourArea)
                per = cv2.arcLength(c, True)
                circ = 4 * np.pi * a / (per * per) if per > 0 else 0.0
                cy, cx = ndi.center_of_mass(sub)
                rmax = int(max(sub.shape) * 0.9) + 4
                prof = profile(g[sl], sub, cy, cx, rmax)
                dpk, rp, fwhm, slope = dark_metrics(prof, bg)
                d_edge, kind, dp_edge, sl_edge = t.edge_diameter(g[sl], sub, cy, cx, bg)
                if not np.isfinite(d_edge):
                    dp_edge = np.nan          # eqd 兜底对象无 dp（与脚本一致）
                vals = g[sl][sub].astype(np.float64)
                contrast = float(vals.max() - vals.min())
                lv = float(lapmap[sl][sub].var())
                lvc = lv / (contrast ** 2) if contrast > 1 else np.nan
                hfr = float(hp_small[sl][sub].std() / max(gray_f[sl][sub].std(), 1e-6))
                nc = t.n_cores(sub)
                rows.append(dict(
                    seg=dp_.name, frame=fp.name, idx=i,
                    d=round(float(d_edge), 2) if np.isfinite(d_edge) else None,
                    kind=kind, circ=round(float(min(circ, 1.0)), 3), area=a,
                    x=int((sl[1].start + sl[1].stop) // 2),
                    y=int((sl[0].start + sl[0].stop) // 2),
                    dp=round(dp_edge, 2) if np.isfinite(dp_edge) else None,
                    dp_raw=round(dpk, 2) if np.isfinite(dpk) else None,
                    rp=round(rp, 1),                     fwhm=round(fwhm, 2) if np.isfinite(fwhm) else None,
                    slope=round(sl_edge, 3) if np.isfinite(sl_edge) else None,
                    lv=round(lv, 1), lvc=round(lvc, 4) if np.isfinite(lvc) else None,
                    hfr=round(hfr, 4), contrast=contrast, nc=nc,
                    d_um=round(float(d_edge) * k, 3) if np.isfinite(d_edge) else None))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[s6_focus_probe] {len(rows)} objects → {out_csv}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", default="feats.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--um-per-px", type=float, default=0.0762)
    a = ap.parse_args()
    run(a.dirs, a.out, limit=a.limit, k=a.um_per_px)
