#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
s6_b_gate.py — B 门：单球性闸门（B single-sphere gate），v1.3

来源：261003_triage 扇区剖面原型 v1–v7（2026-10-09~10-12），用户拍板「严档」。
哲学与 s6_frame_gate 一致：宁缺毋滥（漏过权重 > 误伤）。

机制：
  1) 扇区径向剖面 — 以圈心为原点，360° 分 N_SEC 个扇区，每个扇区沿半径
     测一条一维亮度剖面（bin 宽 BIN_W px）。谷 = 原始灰度局部极小，且
     凸起度 ≥ PROM_MIN（谷比两侧 0.4R 内的峰各暗至少该值）；亚像素谷
     半径 = 抛物线插值。⚠️ 不用 I/baseline 归一化找谷——线性基线斜坡
     会让碎屑亮点也生出「假谷」且天然共圆，判据反向失效（v8 教训）。
  2) 谷点代数圆拟合（Kasa + 鲁棒剔离群）— 谷点拟合一个圆，rms 残差归一化
     rn=rms/R。残差小 = 谷点共圆 = 单个孤立球；残差大 = 谷点来自不同对象。
  3) 二轮迭代精化 — 用一轮拟合圆心/半径重采样再拟合（移心后剖面更准）。
  4) 圆出画检查 — 拟合圆超出图像边界 = 对象贴边被截断，独立硬判据。
  5) 覆盖率 n ≥ MIN_N — 16 扇区里合格谷太少 = 只有局部看得到暗环
     （碎片 / 大半截出画 / 团块缝隙），不是完整球。

严档判据（用户 2026-10-12 拍板「用严档，宁缺毋滥」；45 格金标准回归）：
    PASS  ⇔  rn2 ≤ 0.10  ∧  n ≥ 9  ∧  拟合圆不出画  ∧  拟合成功
    ⇒ 漏 1/13（EDGE+PHANTOM+CLUSTER 应挡集合）、丢 1/24（可用球）
    对比原型 v7（漏1/丢7）：同漏率下少丢 6 个好球。
    唯一漏网 29-5（亮点紧贴大球，谷圆自身确实自洽）；
    唯一误伤 44-12（真球被画边截断，按宁缺毋滥设计性挡掉）。
    参数敏感性：PROM_MIN 12→25 区间漏 1–2、丢 1–3；rn 阈值 0.07–0.10 平台。

v1.2 变更（2026-10-14，连续度第二判据，DSC_2307 用户 105 圈归因驱动）：
  背景：用户 105 个漏检圈归因 C 类 45 个 = 种子在、圆拟合了，但 n 中位 8
  （差 1 个扇区）被 low_coverage 拒。诊断发现判别真球的关键不止「谷够不够多」
  （n），还有「谷是不是连成一段完整圆弧」——16 扇区金标准分布实测：
    USABLE 连续弧中位 315°、PHANTOM 112.5°、CLUSTER 135°（max_gap 反而无区分力）。
  新增 OR 支线（只扩不删，严档原样保留）：
    PASS ⇔ 严档四条  ∨  ( n ≥ RUN_MIN_N=7  ∧  最长连续弧 ≥ RUN_MIN_DEG=112.5°
                          ∧ rn2 ≤ 0.10 ∧ 不出画 ∧ 拟合成功 )
  战绩（两套金标准 + 全量重放，回归脚本 261003_triage/_gold13_or.py、
        261013_dsc2307/_sweep_bgate.py）：
    · 14_2h 45 格：漏 1/13（仍仅 29-5）、丢 1/24（仍仅 44-12）——零变化；
    · 13_2h 47 格：好球 B PASS 22 → 24，坏格新放行 0；全量 4587 行重放
      一致性 100%（现行支线逐格复现）、新放行 87；
    · DSC_2307 4 帧：用户 C 类救回 8/45（原 2）、新放行 63、误杀原 kept 0；
      新放行抽 12 目检 11–12 为真球。
  开关：RUN_MIN_DEG = 0 可整体关闭本支线（回退 v1.1 行为）。
  ⚠ 方向数实验（同期）：N_SEC 16→32/64 计时 27→52→101 ms/实例（线性），
    但金标准漏不变、丢 1→2（35-1 被误杀）——更细扇区不增益，不采用。

v1.3 变更（2026-10-21，纯性能、行为零变化）：
  背景：cProfile 实测 B 门 sector_profile 占 v5 单帧总时长 94%
  （26546 次调用 × 16 扇区 × 每半径现场 linspace，一帧 ~500 万次小数组
  运算，315 s/帧违背「又快又准」初衷）。
  改法：sector_profile 向量化——一次 (n_sec, n_r, m) 张量采样替代逐
  (扇区,半径) 小数组；找谷只在向量化候选掩码上跑。判据/标定/入口签名
  全部不动。
  验证（261013_dsc2307/_verify_fast.py，4 开发帧 9620 实例）：
  sector_profile 与 v1.2 逐位全等 9620/9620，evaluate 全字段全等
  2405/2405，18.5 → 1.1 ms/实例（16.1×）。
  保真三要点写在 sector_profile docstring（linspace 算术序复刻 /
  float32 域均值 / 逐扇区 ulp step）。回归口令不变：
  python s6_b_gate.py --gold <triage_dir>。

依赖：仅 numpy + PIL（与 s6_triage 同源灰度约定 load_gray）。
用法：
  python s6_b_gate.py --gold <triage_dir>            # 45 格金标准回归
  python s6_b_gate.py --frame f.jpg --cx X --cy Y --r R   # 单格判读
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------- 扇区剖面参数（v1–v7 定型，勿随手改） ----------------
N_SEC = 16                 # 扇区数 → 最大谷点数 16
R_LO, R_HI = 0.40, 1.65    # 采样半径范围（×R）
BIN_W = 1.0                # 半径 bin 宽 px（v1 用 0.5 被 MIN_PX 误杀 → 改 1.0）
MIN_PX = 3                 # 每 (扇区,bin) 最少像素数（v1 用 6 → 改 3）
BASE_IN = (0.45, 0.65)     # 内基线段（×R）— 仅用于记录/诊断
BASE_OUT = (1.35, 1.60)    # 外基线段（×R）— 仅用于记录/诊断
PROM_MIN = 12.0            # 谷「凸起度」下限（灰度）：谷比两侧峰各暗至少此值
PEAK_WIN = 0.40            # 凸起度峰搜索窗（×R）
D_MIN = PROM_MIN           # 兼容旧名（v1–v7 曾作归一化剖面深度下限）
DELTA_MAX = 0.10           # 严档归一化残差上限 rn2 ≤ DELTA_MAX
MIN_SEED = 4               # 拟合最少谷点数（不足 → 拟合失败直接拒）
MIN_N = 9                  # 严档覆盖率下限：16 扇区中合格谷 ≥9（半数以上方向
                           # 都看得见暗环才算球；碎片/贴边对象覆盖不足）

# ---------------- v1.2 连续度第二判据（OR 支线，只扩不删） ----------------
# 依据（2026-10-14，DSC_2307 用户 105 圈归因 + 两套金标准分布）：真球的合格谷
# 连成整圈（USABLE 连续弧中位 315°），碎片/团簇的谷东一个西一个
# （PHANTOM 112.5° / CLUSTER 135°）——「连续弧长」是 n 之外的独立判别轴。
RUN_MIN_N = 7              # 支线谷数下限（严档 9 放宽 2）
RUN_MIN_DEG = 112.5        # 最长连续扇区弧下限（16 扇区 = 5 个相邻扇区）；0 = 关闭支线

# ---------------- 圈位标定（2026-10-12，23 个用户修正圈 LOO 验证） ----------------
# 有符号偏差：B 拟合圈相对用户手调圈半径系统性偏小（中位 −1.10px）、
# 圆心偏左上（dx −0.70 / dy −1.50px）。机制：谷 = 暗环最暗处，用户圈画在
# 可见边缘，两者定义差一个近似常量。留一交叉验证（23 格逐个留出）：
#   |Δr| 中位 1.10 → 0.65px；|Δ心| 中位 1.99 → 1.53px — 非全样本拟合假象。
# 对照：机器原圈 |Δr| 中位 6.4px。
# ⚠️ 标定源 = 14_2h 单视频 23 格（用户圈半径整数化 ±0.5px + 拖动精度，
#    本底 ~0.5–1px）；跨视频未验 — 若干预期外先归零这三个常量再排查。
CAL_DR = 1.1               # 半径校正（px，加到拟合半径）
CAL_DX = 0.7                # 圆心校正 x（px，加）
CAL_DY = 1.5                # 圆心校正 y（px，加）


def load_gray(p) -> np.ndarray:
    """与 s6_triage.load_gray 完全一致的灰度口径（PIL L 通道，uint8）。"""
    return np.array(Image.open(p).convert("L"))


def sector_profile(g: np.ndarray, cx: float, cy: float, R: float, prom_min=None):
    """16 扇区径向剖面，谷 = 原始灰度的局部极小 + 凸起度门控。【v1.3 向量化】

    返回 [(depth, r_valley, theta), ...]：每个扇区至多一条谷。
    depth = 凸起度 = min(左峰, 右峰) − 谷值（灰度，越大环越清晰）。

    为什么不用 I/baseline 归一化后找谷（v8 教训）：
    归一化基线是「内中位→外中位」的线性斜坡，斜坡本身会让任何单调
    衰减剖面（碎屑亮点）在固定比例半径处产生相对凹陷——假谷天然共圆，
    碎屑的 rn 反而比真球还低，判据完全失效（4 个 PHANTOM rn 全 <0.05）。
    改为在原始灰度上找局部极小并要求凸起度 ≥ PROM_MIN：真球暗环两侧
    都亮（凸起大），碎屑单调衰减生不出合格谷 → 该扇区无谷 → n↓ → 拒。

    v1.3（2026-10-21 性能刀，profile 实测占 v5 总时长 94%）：v1.2 每
    (扇区,半径) 现场建 linspace + 逐点采样 ≈ 一帧 500 万次小数组运算；
    现批成一次 (n_sec, n_r, m) 张量采样，找谷只在候选点上跑。
    与 v1.2 逐位一致的三条保证（261013_dsc2307/_verify_fast.py，9620 实例
    sector_profile + 2405 实例 evaluate 全等，16.1× 加速）：
      1) tt 复刻 np.linspace 算术序：y = start + (arange*step)，末点强制
         = stop；step 用 (th+half)−(th−half) 逐扇区现算（ulp 级 ≠ 2*half）；
      2) 均值仍在 float32 域除：像素 0–255 整数、每行 ≤ ~25 点，float32
         求和恒精确、与求和顺序无关；除法须显式 cast float32（numpy2 下
         float32/int64 自动升 float64，结果就不同了）；
      3) 候选谷/凸起度窗/抛物线插值逐式照抄 v1.2，只把「扫全行找候选」
         换成向量化掩码（比较语义完全一致，含 NaN 传播）。
    ⚠ 前提：g 为整数值灰度（本 skill 全链路 load_gray→float32 均满足）；
      浮点连续值图像不保证逐位一致。
    """
    g = np.asarray(g)
    if g.dtype != np.float32:
        g = g.astype(np.float32)
    H, W = g.shape
    rs = np.arange(R_LO * R, R_HI * R + 1e-9, BIN_W)
    K = max(2, int(PEAK_WIN * R / BIN_W))          # 峰搜索窗（bin 数）
    half = np.pi / N_SEC                            # 扇区半宽 11.25°
    n_r = int(rs.shape[0])
    # 每半径采样点数（int() 截断语义与原版一致）
    n_s = np.maximum(3, (2.0 * half * rs / BIN_W).astype(int) + 1)
    m = int(n_s.max())
    # tt[k, i, j] = start_k + (j * step_i)，仅 j < n_s[i] 有效；末点强制 = stop_k
    ths = (np.arange(N_SEC) + 0.5) * 2.0 * np.pi / N_SEC
    start = ths - half
    stop = ths + half
    step = (stop - start)[:, None] / (n_s - 1)[None, :]           # (n_sec, n_r) 逐扇区 ulp 保真
    j_step = np.arange(m, dtype=float)[None, None, :] * step[:, :, None]   # (n_sec, n_r, m)
    tt = start[:, None, None] + j_step                            # (n_sec, n_r, m)
    tt[:, np.arange(n_r), n_s - 1] = stop[:, None]
    xs = cx + rs[None, :, None] * np.cos(tt)
    ys = cy + rs[None, :, None] * np.sin(tt)
    xi = np.round(xs).astype(int)
    yi = np.round(ys).astype(int)
    ok = ((np.arange(m)[None, :] < n_s[:, None])[None, :, :]
          & (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H))
    pix = g[np.clip(yi, 0, H - 1), np.clip(xi, 0, W - 1)]
    ssum = np.where(ok, pix, np.float32(0.0)).sum(axis=2)          # float32，整数和恒精确
    n_ok = ok.sum(axis=2)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_f = ssum / n_ok.astype(np.float32)                    # float32 除法（同 np.mean）
    vals = np.where(n_ok >= MIN_PX, mean_f, np.float32(np.nan)).astype(float)
    out = []
    for k in range(N_SEC):
        v = vals[k]
        if np.all(np.isnan(v)):
            continue
        # 候选谷：局部极小（NaN 传播使含 NaN 邻居的点自然落选，同 v1.2 语义）
        b_all = v[1:-1]
        cand = np.isfinite(b_all) & (v[:-2] >= b_all) & (v[2:] >= b_all)
        best = None
        for i in (np.nonzero(cand)[0] + 1):
            b = v[i]
            left = v[max(0, i - K):i]
            right = v[i + 1:min(n_r, i + 1 + K)]
            left = left[np.isfinite(left)]
            right = right[np.isfinite(right)]
            if len(left) == 0 or len(right) == 0:
                continue
            prom = min(float(left.max()) - b, float(right.max()) - b)
            if prom < (PROM_MIN if prom_min is None else prom_min):
                continue
            a, c = v[i - 1], v[i + 1]
            denom = (a - 2 * b + c)
            dr = 0.5 * (a - c) / denom if np.isfinite(denom) and abs(denom) > 1e-9 else 0.0
            dr = float(np.clip(dr, -0.5, 0.5))
            rv = float(rs[i] + dr * BIN_W)
            if best is None or prom > best[0]:
                best = (prom, rv, float(ths[k]))
        if best is not None:
            out.append(best)
    return out


def fit_circle(pts):
    """Kasa 代数最小二乘圆拟合 → (a, b, R, rms)；点不足返回 None。"""
    if len(pts) < MIN_SEED:
        return None
    x = np.asarray([p[0] for p in pts], dtype=float)
    y = np.asarray([p[1] for p in pts], dtype=float)
    A = np.column_stack([x, y, np.ones(len(x))])
    bb = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, bb, rcond=None)
    except np.linalg.LinAlgError:
        return None
    a, b, f = sol[0] / 2, sol[1] / 2, sol[2]
    # 圆方程 x²+y² = 2a·x + 2b·y + f，其中 f = R² − a² − b² → R² = f + a² + b²
    R2 = f + a * a + b * b
    if R2 <= 0:
        return None
    R = float(np.sqrt(R2))
    d = np.hypot(x - a, y - b) - R
    rms = float(np.sqrt(np.mean(d * d)))
    return float(a), float(b), R, rms


def robust_fit(pts, iters=3):
    """鲁棒 Kasa 拟合。

    两段防线（v1 教训）：
      0) 初值预筛 — 谷点应大致落在同一圆周上，先用「坐标中位数中心 +
         半径中位数 ± 3·MAD」丢掉明显离群谷（邻近粒子的远谷会把
         普通最小二乘直接带飞到 R≈数千 px，整格报废）。
      1) 迭代残差剔除 — 初值正常后再按拟合残差剔离群。
    返回 (fit, keep_idx)。
    """
    if len(pts) < MIN_SEED:
        return None, list(range(len(pts)))
    P = np.asarray(pts, dtype=float)
    c0 = np.median(P, axis=0)                       # 坐标中位：环上点群的稳健中心
    rr = np.hypot(P[:, 0] - c0[0], P[:, 1] - c0[1])
    r0 = float(np.median(rr))
    mad = float(np.median(np.abs(rr - r0))) + 1e-6
    idx = [i for i in range(len(pts))
           if abs(rr[i] - r0) <= max(3.0 * 1.4826 * mad, 0.25 * r0)]
    if len(idx) < MIN_SEED:
        idx = list(range(len(pts)))
    fit = fit_circle([pts[i] for i in idx])
    if fit is None:
        return None, idx
    for _ in range(iters):
        a, b, R, rms = fit
        d = np.array([abs(np.hypot(pts[i][0] - a, pts[i][1] - b) - R) for i in idx])
        med = float(np.median(d))
        mad_d = float(np.median(np.abs(d - med))) + 1e-6
        keep = [j for j, i in enumerate(idx) if d[j] <= max(3.0 * 1.4826 * mad_d, 1.5)]
        if len(keep) < MIN_SEED or len(keep) == len(idx):
            break
        new_fit = fit_circle([pts[idx[j]] for j in keep])
        if new_fit is None:
            break
        idx = [idx[j] for j in keep]
        fit = new_fit
    return fit, idx


def one_round(g, cx, cy, R, prom_min=None):
    """一轮：剖面 → 谷点 → 鲁棒拟合。

    返回 dict(fit=(a,b,R,rms)|None, n, max_gap_deg, med_depth, pts, keep)
    """
    valleys = sector_profile(g, cx, cy, R, prom_min=prom_min)
    pts = [(cx + r * np.cos(th), cy + r * np.sin(th)) for _, r, th in valleys]
    fit, keep = robust_fit(pts)
    kept = [valleys[j] for j in keep] if fit is not None else []
    # 角度空隙（按保留谷点的扇区序，缺失扇区累积成空隙）
    ths = sorted([th for _, _, th in kept])
    if len(ths) >= 2:
        gaps = [ths[(i + 1) % len(ths)] - ths[i] for i in range(len(ths))]
        gaps = [g_ + 2 * np.pi for g_ in gaps if g_ <= 0]
        max_gap = float(np.degrees(max(gaps)))
    else:
        max_gap = 360.0
    med = float(np.median([d for d, _, _ in kept])) if kept else 0.0
    # v1.2 最长连续扇区弧（deg）：合格谷按扇区序取圆周最长连续段
    if kept:
        secs = sorted({int(round(th / (2.0 * np.pi / N_SEC) - 0.5)) % N_SEC
                       for _, _, th in kept})
        doubled = secs + [s + N_SEC for s in secs]
        run = cur = 1
        for i in range(1, len(doubled)):
            cur = cur + 1 if doubled[i] == doubled[i - 1] + 1 else 1
            if cur > run:
                run = cur
        run = min(run, len(secs))
        run_deg = float(run * 360.0 / N_SEC)
    else:
        run_deg = 0.0
    return dict(fit=fit, n=len(kept), max_gap=max_gap, med_depth=med,
                pts=pts, valleys=kept, run_deg=run_deg)


def evaluate(g: np.ndarray, cx: float, cy: float, R: float, prom_min=None) -> dict:
    """B 门主入口：二轮迭代 + 判据 → 严档 PASS/REJECT + 全部特征。

    prom_min：凸起度阈值覆盖（None=用 PROM_MIN 严档；数字=自适应复试档，
    调用方按局部对比度自定，如 max(4, 0.3*max_prom)）。
    """
    H, W = g.shape
    r1 = one_round(g, cx, cy, R, prom_min=prom_min)
    if r1["fit"] is None:
        return dict(ok=False, reason="fit_fail", n=0, rn2=None,
                    out_of_frame=None, margin=None,
                    cx2=cx, cy2=cy, R2=R, gap2=r1["max_gap"], medd2=r1["med_depth"],
                    run_deg=r1["run_deg"])
    a1, b1, R1, rms1 = r1["fit"]
    if not (0.5 * R <= R1 <= 2.0 * R):
        # 一轮拟合半径离谱 → 退化几何，不再二轮（v1 教训：R≈2688px 全格报废）
        a, b, Rf, rms = a1, b1, R1, rms1
        r2 = r1
    else:
        r2 = one_round(g, a1, b1, R1, prom_min=prom_min)   # 二轮迭代精化
        fit2 = r2["fit"] if r2["fit"] is not None else r1["fit"]
        a, b, Rf, rms = fit2
        if not (0.5 * R <= Rf <= 2.0 * R):
            a, b, Rf, rms = a1, b1, R1, rms1
            r2 = r1
    rn = rms / max(Rf, 1e-6)                            # 归一化残差（v4 单位 bug 教训）
    margin = float(min(a, W - a, b, H - b) - Rf)        # 圆心到最近边界 − 半径
    out = margin < 0
    # 圈位标定（只修输出圆，不改判据——rn/出画/覆盖率都在标定前的原始拟合上算，
    # 保证 45 格回归结果与 v1.0 逐格一致，标定零风险回退 = CAL_* 归零）
    ax, by, Rf = a + CAL_DX, b + CAL_DY, Rf + CAL_DR
    n = r2["n"]
    run_deg = r2["run_deg"]
    hard_fail = n < MIN_SEED
    low_cov = n < MIN_N                                 # 覆盖不足：16 扇区里合格谷太少
    strict_ok = (not hard_fail) and (not low_cov) and (not out) and (rn <= DELTA_MAX)
    # v1.2 连续度支线：谷略少（≥RUN_MIN_N）但连成 ≥RUN_MIN_DEG 的整段圆弧 → 仍放行
    run_ok = ((not hard_fail) and (not out) and (rn <= DELTA_MAX)
              and RUN_MIN_DEG > 0 and n >= RUN_MIN_N and run_deg >= RUN_MIN_DEG)
    ok = strict_ok or run_ok
    if ok:
        why = "pass"
    elif out:
        why = "out_of_frame"
    elif hard_fail or low_cov:
        why = "low_coverage"
    else:
        why = "high_residual"
    return dict(ok=ok, reason=why,
                n=n, rn2=round(rn, 4), out_of_frame=bool(out), margin=round(margin, 1),
                cx2=round(ax, 1), cy2=round(by, 1), R2=round(Rf, 1),
                gap2=round(r2["max_gap"]), medd2=round(r2["med_depth"], 1),
                run_deg=round(run_deg, 1), via_run=bool(run_ok and not strict_ok),
                rn1=round(rms1 / max(R1, 1e-6), 4), n1=r1["n"])


# ---------------- 45 格金标准回归 ----------------
def gold_regression(triage: Path):
    cls = json.loads((triage / "_miss21_class.json").read_text(encoding="utf-8"))
    gold = json.loads((triage / "labels_14_2h_fig3objects.json").read_text(encoding="utf-8"))
    cands = {c["id"]: c for c in json.loads((triage / "select_fig3_review.json").read_text(encoding="utf-8"))}
    frames_dir = Path(os.environ.get("MPD_GOLD_FRAMES", "frames"))
    miss = cls["miss_class"]
    usable = set(cls["usable"])
    BLOCK = sorted(k for k, v in miss.items() if v != "OFFSET")   # 13 = EDGE+PHANTOM+CLUSTER
    assert len(BLOCK) == 13, len(BLOCK)

    cache, recs = {}, {}
    for cid, c in cands.items():
        fno = c["frame"]
        if fno not in cache:
            cache[fno] = load_gray(frames_dir / f"frame_{fno:05d}.jpg").astype(np.float32)
        recs[cid] = evaluate(cache[fno], c["c_x"], c["c_y"], c["c_r"])

    leak = [i for i in BLOCK if recs[i]["ok"]]
    drop = sorted(i for i in usable if not recs[i]["ok"])
    print(f"[严档回归] 漏 {len(leak)}/13 {leak}  丢 {len(drop)}/24 {drop}")
    # 按根因分类看判决分布（21 没圈住 + 24 可用）
    from collections import Counter
    det = Counter()
    for cid in list(BLOCK) + sorted(usable):
        g_ = "USABLE" if cid in usable else miss[cid]
        det[(g_, "PASS" if recs[cid]["ok"] else "REJECT")] += 1
    for g_ in ["EDGE", "PHANTOM", "CLUSTER", "OFFSET", "USABLE"]:
        p = det[(g_, "PASS")]; rj = det[(g_, "REJECT")]
        if p + rj:
            print(f"    {g_:8s} PASS {p:>2d} / REJECT {rj:>2d}")
    target = (1, 1)
    got = (len(leak), len(drop))
    print("PASS ✅ 漏1/丢1（优于原型 v7 的漏1/丢7）" if got == target
          else f"FAIL ❌ 目标 {target} 实得 {got}")
    return recs, got == target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", help="triage 工作目录（跑 45 格金标准回归）")
    ap.add_argument("--frame")
    ap.add_argument("--cx", type=float)
    ap.add_argument("--cy", type=float)
    ap.add_argument("--r", type=float)
    a = ap.parse_args()
    if a.gold:
        gold_regression(Path(a.gold))
        return
    if not (a.frame and a.cx is not None and a.cy is not None and a.r):
        ap.error("需要 --gold，或 --frame/--cx/--cy/--r")
    g = load_gray(a.frame).astype(np.float32)
    res = evaluate(g, a.cx, a.cy, a.r)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
