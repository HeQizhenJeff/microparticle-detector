# -*- coding: utf-8 -*-
"""S6-CR 粘连簇救回通道（clump rescue，2026-10-22 落正本）

定位：**对象级补充检出**——在现有管线（DoG 种子 → B 门 → P0–P3 → S6-R 暗环
通道）之外，对「未解释环带」做多种子源补扫，专打 E 类粘连球漏检。纯增量，
只加不删（去重时基线圈先占位）。

谱系：工作区原型 `_ringgap4.py` v4.2（四种子源补扫）+ `_proto_v5.py`
（CLEAN 迭代 + DAOPHOT 双圆拟合），2026-10-20~22 三道验收全过后落正本。

机制（v5 管线 = 三层递进，全部过 B 门 s6_b_gate.evaluate 安全网）：
  第一层 v4 底座（run_frame）——对未解释暗环带连通簇依次尝试：
    ① 拟合种子：Kasa 代数拟合 → 半径窗 (0.9,1.0,1.1)r 过门；
    ② 质心 fallback：拟合失败或 rms>max(2.5,0.18r) → 质心+maxdist 缩放；
    ②b 双球拆分回退（v4.2 刀②）：①②都拒的 ≥600px 大簇沿像素 PCA 主轴
       投影、直方图谷底切两半各自重拟合；防过切三护栏 = 半径范围 +
       圆心距≥0.8(r1+r2) + 两半都过 B 门（半圈环天然凑不齐多扇区谷链）；
    ③ 亮核种子：亮核距离变换局部极大（亮斑中心=球心）；
    ④ 微稠密扫（v4.2 刀①）：≥400px 残余簇 bbox+12 内 stride8、半径
       (10,13,16)；**逐格判定**——格点落在既有过门圈内才跳（原「bbox 内
       有任一过门圈就整簇跳过」会把双球粘连簇整簇跳掉 = M 型漏检根因）。
  第二层 CLEAN 迭代（模块A，Högbom 1974 射电干涉）：新过门圈回喂解释集
    → 重算未解释 mask → 再扫；被首轮大圈遮住的小球环碎片第 2 轮起露出。
  第三层 DAOPHOT 双圆联合拟合（模块B，Stetson 1987 拥挤星场）：v4+CLEAN
    都没出圈的残余大簇 → 两亮核初值 → EM 交替拟合 → 两圆各过 B 门才收。

战绩（2026-10-21~22，DSC_2307 用户 4 开发帧标注 30 错 + 26 漏 + 注入帧 +
138 格金标准审计）：
  - v5 端到端：注入孤立球 34/40 → 39/40（00070 满分 20/20）；
  - M 型漏检（粘连簇拟合错位）救回 3/9，其余 6 个为机制边界（半径菜单
    不匹配 / 簇面积<400 / 格点覆盖），不再追；
  - 旧圈零丢失、30 个用户标注假阳性零撞位（只增不减红线）；
  - 138 格审计：救回 33 ≥ v4 32，泄漏 20（新增 3 泄漏经用户标注+定量
    复核均为基线层问题，非本通道新增）；
  - 性能：sector 向量化 + bbox 等价剪枝 + dm/种子同帧缓存 + 多进程，
    ≈48 s/帧（1920×1080，--workers 2）。
已知边界：
  ① 只救「暗环还在」的球——两球完全糊成一坨（8 字腰看不清）救不动；
  ② 圈数会变多（含部分同球小圈），下游统计前须过 P2 去重 / 人工抽查；
  ③ 失焦帧（如 14_2h f20/f35）上基线层本身 ~10% 假阳性，本通道不解决
    对焦问题——失焦帧先过 S0-F 对焦评分再决定是否送检；
  ④ 参数为 DSC_2307/14_2h/13_2h 三批校准，跨批次曝光差异未验，改参
    先跑 138 格金标准回归。

用法：
  python s6_clump_rescue.py --frames <帧目录> [--baseline <kept.csv>]
      [--ring <ring_passed.json>] [--out extras.csv] [--mode v5|v4]
      [--iters N] [--workers N] [--no-sweep] [--no-bright] [--no-daophot]
      [--select 00010,00030] [--limit N]
  baseline CSV 需含 frame 列；有 cls 列则只取 cls==kept；半径取 d_B/2
  （无则 d/2）；圆心优先 cx2/cy2（无则 x/y）。--ring 为 JSON
  {frame: [[cx,cy,r],...]}（S6-R 过门圈）。两者都作 expl（已解释集）。
  输出 extras.csv 列：frame,cx,cy,r（与 s6_ring_channel 同口径，
  下游 P2 去重通用）。
"""
import argparse
import csv
import importlib.util as _ilu
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

# accepted frame extensions (public build: no longer assumes *.jpg naming)
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

HERE = Path(__file__).resolve().parent
_s = _ilu.spec_from_file_location("bg", str(HERE / "s6_b_gate.py"))
BG = _ilu.module_from_spec(_s)
_s.loader.exec_module(BG)

# ---- 默认参数（=原型 v4.2 / v5，三批视频校准值，勿随手改；改前跑 138 格回归）----
MIN_PX = 30            # 簇最小像素
R_MIN, R_MAX = 5.0, 60.0
FB_RMS = lambda r: max(2.5, 0.18 * r)   # ② fallback 触发阈（=v2 fit_circle 的 rms 上限）
DT_MIN = 6.0           # ③ 亮核 dt 最小半径
DT_PEAK_DIST = 7       # ③ 峰间最小距离
SWEEP_AREA = 400       # ④ 触发微扫的簇面积下限
SWEEP_STRIDE = 8
SWEEP_RADII = (10.0, 13.0, 16.0)
SWEEP_PAD = 12
MAX_SWEEP = 15         # ④ 每帧最多微扫多少簇（取最大者）
SPLIT_MIN_PX = 600     # ②b 触发双球拆分的簇像素下限（单球环带 ~300-500px）
EM_ITERS = 6           # 模块B EM 轮数
JOINT_MIN_PX = 25      # 每圆最少分到的像素
DEDUP_FRAC = 0.5
CLEAN_ITERS = 2        # 默认总轮数（1 = 关 CLEAN，仅 v4 底座）
# 刀④ 半叠区差异化严审（2026-10-23）：v5 新圈对最近解释圈 sep∈[HG_LO,HG_HI)
# 且 B 门谷数 n<HG_NMIN → 砍。治理「贴着真球的歪圈」；DSC 开发帧行为逐位不变。
HG_LO, HG_HI, HG_NMIN = 0.7, 0.9, 9
# 刀⑥ 微扫三护栏（2026-10-23，用户人工标注 3 帧 491 圈驱动）：
#   标注实测 sweep 支线错误率 52.5%（59 圈 31 错），只占 12% 的圈却贡献 66% 的错误。
#   根因 = SWEEP_RADII 写死 (10,13,16)：球径中位 26.2px 的帧（14_2h_00024）拿半尺寸
#   圈去套 → 该帧 sweep 24/24 全错。三护栏：
#     ⑥a 半径档按帧内 expl 半径中位 ×(0.85,1.0,1.15) 自适应；
#     ⑥b 输出圆半径须在探测半径 ×[0.72,1.35]（旧实现一轮 ≤2R、二轮 ≤4R 会漂到 45px）；
#     ⑥c 圆周暗环掩膜支撑率 sup ≥ 0.80（真球暗环连续：好圈 sup 中位 0.98 / 坏圈 0.56）。
#   标注 A/B：坏圈消除 5/31（旧）→ 27/31；好圈保留 28/28 → 27/28。
SWEEP_ADAPT = True
SWEEP_MIN_EXPL = 20    # expl 圈太少 → 中位不可信，退回固定档
SWEEP_DRIFT_LO, SWEEP_DRIFT_HI = 0.72, 1.35
SWEEP_SUP_ON = True
SWEEP_SUP_MIN = 0.80
SWEEP_SUP_NA = 64      # 圆周采样点数
SWEEP_SUP_DIL = 5      # 掩膜膨胀核（±2px，吸收拟合半径误差）

# 刀⑦ bright（亮核）与 base 重叠即弃（2026-10-27，用户 22 帧标注驱动）
# 机制：bright 找的是「比局部背景亮 0.6σ 的团块」。对焦好的帧，球是清晰暗环、
#   球本身不亮，反倒是球间背景空隙亮 → bright 只能在球缝凑圈；对焦差的帧，球糊成
#   亮团，bright 才补得到真球。数据：base 圈多（对焦好）的帧 bright 错率 38–100%，
#   base 圈少（失焦）的帧 0–5%。
# 判据：sep = 圆心距/(r_bright + r_base) < 1.0（两圆重叠）→ 弃。
#   ⚠ 只对 bright 生效：fit 的 sep<1.0 圈裁图确认多为**精确套在真球上**（base 大圈
#   把几个球圈一起、fit 才是准的），砍了会掉精度；fit 错误率本身仅 2.4%。
# 实测（22 帧 7038 圈 / 用户标错 194）：bright 481→273 圈，错 102→16（21.2%→5.9%）；
#   整帧标错 194→108（−44%），总圈 −3%。覆盖不降有数学保证：被弃圈的最近 base 圈仍在。
BASE_OVL_ON = True
BASE_OVL_SEP = 1.0

# 刀⑧ 圈内亮瓣数（nlobe）闸（2026-10-27，用户 22 帧标注驱动；v5 输出端纯减法）
# 机制：一个圈应当只圈住**一颗球** → 圈内（0.85R）亮区连通域（面积 ≥3% 圆面积）
#   应当 ≤2 个。团簇大圈会同时包住 2–4 个亮瓣；实测 r=94/66/58px 的巨型 fit 圈
#   全是「一个暗环带里套着 2–3 颗球」Kasa 拟合出来的，B 门 n=6~16 全过（谷链自洽）。
# 判据来源：9 条判据（rn2 / 尺寸比 q / 亮核占比 k / 暗环支撑 sup / 中心-中环强度差
#   cdiff / 亮瓣占比 lfrac / 内切圆心数 / 贴边度 / 与最近圈重叠 sep）逐一 AUC 扫描，
#   只有 nlobe 有精度（fit 层 8 坏 : 8 好，好圈损失 0.5%）。
# 实测（22 帧 7038 圈 / 用户标错 194，存活圈上算）：砍 13 坏（fit 8 + sweep 3 +
#   base 1 + split 1），误砍 35（base 25 / fit 8 / sweep 2，均为 0.52% 好圈）。
#   裁图（_knife8_bad.jpg / _knife8_goodloss.jpg）：13/13 该砍；误砍的 35 张里
#   大半是空缺白圈（base 层本身漏标的假阳），真·好球损失 <5。
# ⚠ 射程：治「一圈圈多球 / 圈在空缺」，治不了「尺寸对、位置偏」的正常形状错圈。
LOBES_ON = True
LOBE_MAX = 2               # nlobe >= 3 → 砍
LOBE_R_FRAC = 0.85         # 取样半径（×R）
LOBE_MIN_AREA_FRAC = 0.03  # 亮瓣最小面积（×πR²），滤掉噪点
LOBE_BG_SIGMA = 31         # 局部背景高斯 σ（与 bright_dt_seeds 同口径）
LOBE_THR_SIGMA = 0.6       # 亮区阈值 = bgm + 0.6·MAD-σ

# 刀⑨ split 通道默认关闭（2026-10-27 用户裁决「砍掉但技术保留」）
# 用户 22 帧标注：split 17 圈 6 错（35.3%，全库最高），且错的是 r=48/31 跨球大圈，
# 对粒径统计伤害最大。代码与 call site 全部保留，--split 可随时重开（回归/未来复用）。
SPLIT_ON = False


# ================= 底座工具（= v4.2 原型） =================
def dark_ring_mask(g):
    gf = g.astype(np.float32)
    bgm = cv2.GaussianBlur(gf, (0, 0), 31)
    sd = float(np.median(np.abs(gf - bgm))) * 1.4826
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    blackhat = cv2.morphologyEx(g.astype(np.uint8), cv2.MORPH_CLOSE, k).astype(np.float32) - gf
    return ((blackhat > 0.6 * sd) & (gf < bgm)).astype(np.uint8) * 255


def unexplained_band(mask, circles):
    """扣掉已解释圈的环带像素（|d-r|<=3）。

    v4.1 无损剪枝（2026-10-21 性能刀②）：|d−r|<=3 ⇒ d<=r+3 ⇒ |dx|,|dy| <= r+3，
    故只需在每圈 bbox 窗内算 sqrt，窗 kill 集合与全图逐像素完全相同（逐位等价）。
    """
    m = mask.copy()
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return m
    kill = np.zeros(len(xs), bool)
    for (cx, cy, r) in circles:
        rr = r + 3
        win = (np.abs(xs - cx) <= rr) & (np.abs(ys - cy) <= rr)
        if not win.any():
            continue
        d = np.sqrt((xs[win] - cx) ** 2 + (ys[win] - cy) ** 2)
        kill[win] |= np.abs(d - r) <= 3
    m[ys[kill], xs[kill]] = 0
    return m


def fit_circle(xs_, ys_):
    """Kasa 代数圆拟合 → (cx, cy, r, rms) 或 None（不设 rms 上限，由门裁决）"""
    if len(xs_) < 8:
        return None
    A = np.column_stack([xs_, ys_, np.ones(len(xs_))])
    b = xs_ ** 2 + ys_ ** 2
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except Exception:
        return None
    cx, cy = sol[0] / 2, sol[1] / 2
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    if not (R_MIN <= r <= R_MAX):
        return None
    res = np.sqrt((xs_ - cx) ** 2 + (ys_ - cy) ** 2) - r
    rms = float(np.sqrt((res ** 2).mean()))
    return float(cx), float(cy), float(r), rms


def split_doublet(g, cxs, cys):
    """②b 双球簇拆分回退（v4.2 刀② 2026-10-22）。

    M 型漏检根因：相邻两球的环带并成一个连通簇 → Kasa 拟合出两球之间
    的垃圾圆心 + 偏大半径 → 半径窗全错位 → ①② 都拒；微扫又被邻球
    过门圈跳过（刀①已修）。本函数处理「①拟合 + ②质心 fallback 都失败」
    的 ≥SPLIT_MIN_PX 大簇：沿像素分布主轴（PCA 第一主成分）投影，在
    投影谷底（直方图中央 60% 区间最小 bin）切成两半，各自重新拟合过门。
    防过切护栏见 docstring ②b。返回 [(cx, cy, r), ...]（至多 2 个）。
    """
    if len(cxs) < 2 * SPLIT_MIN_PX // 3:
        return []
    mx, my = float(cxs.mean()), float(cys.mean())
    dx, dy = cxs - mx, cys - my
    cov = np.cov(np.vstack([dx, dy]))
    w, v = np.linalg.eigh(cov)
    ax = v[:, int(np.argmax(w))]          # 主轴（两球连线方向）
    t = dx * ax[0] + dy * ax[1]           # 投影坐标
    lo, hi = np.percentile(t, [5, 95])
    if hi - lo < 6.0:
        return []
    hist, edges = np.histogram(t, bins=32, range=(lo, hi))
    if hist.sum() < 2 * MIN_PX:
        return []
    c_lo, c_hi = int(32 * 0.2), int(32 * 0.8)
    if c_hi <= c_lo:
        return []
    k = c_lo + int(np.argmin(hist[c_lo:c_hi]))
    thr = 0.5 * (edges[k] + edges[k + 1])
    m1, m2 = t < thr, t >= thr
    if m1.sum() < MIN_PX or m2.sum() < MIN_PX:
        return []
    fits = []
    for m in (m1, m2):
        cf = fit_circle(cxs[m], cys[m])
        if cf is None:
            return []
        fits.append(cf)
    (x1, y1, r1, rms1), (x2, y2, r2, rms2) = fits
    d12 = math.hypot(x1 - x2, y1 - y2)
    if d12 < 0.8 * (r1 + r2):
        return []                       # 圆心太近 = 假切
    # 两半各自过门（B 门是最硬护栏：半圈环过不了多扇区谷链）
    out = []
    for (fcx, fcy, fr) in ((x1, y1, r1), (x2, y2, r2)):
        res = gate_seed(g, fcx, fcy, [fr * s for s in (0.9, 1.0, 1.1)])
        if res:
            out.append((res["cx2"], res["cy2"], res["R2"]))
    return out


def bright_dt_seeds(g):
    """③ 亮核距离变换局部极大 → [(cx, cy, dt_r)]（球心=亮斑内切圆心）"""
    gf = g.astype(np.float32)
    bgm = cv2.GaussianBlur(gf, (0, 0), 31)
    sd = float(np.median(np.abs(gf - bgm))) * 1.4826
    bright = (gf > bgm + 0.6 * sd).astype(np.uint8)
    dt = cv2.distanceTransform(bright, cv2.DIST_L2, 5)
    k = cv2.getStructuringElement(cv2.MORPH_RECT,
                                  (2 * DT_PEAK_DIST + 1, 2 * DT_PEAK_DIST + 1))
    mx = cv2.dilate(dt, k)
    peaks = (dt == mx) & (dt >= DT_MIN)
    ys, xs = np.nonzero(peaks)
    return [(float(x), float(y), float(dt[y, x])) for x, y in zip(xs, ys)]


def gate_seed(g, cx, cy, rlist, drift=False):
    """依次试半径组，返回首个过门结果。

    drift=True（刀⑥b，仅微扫格点用）：输出圆半径须在探测半径的
    [SWEEP_DRIFT_LO, SWEEP_DRIFT_HI] 倍内，否则该档视为「套不上」继续试下一档。
    """
    for rr in rlist:
        if not (R_MIN <= rr <= R_MAX):
            continue
        try:
            res = BG.evaluate(g, float(cx), float(cy), float(rr))
        except Exception:
            continue
        if res.get("ok"):
            if drift and not (SWEEP_DRIFT_LO * rr <= res["R2"] <= SWEEP_DRIFT_HI * rr):
                continue
            return res
    return None


def mask_support(dm_dil, x, y, r):
    """刀⑥c 圆周暗环掩膜支撑率（0~1）。dm_dil = 已膨胀的暗环掩膜。"""
    H, W = dm_dil.shape
    hit = 0
    for k in range(SWEEP_SUP_NA):
        a = 2.0 * math.pi * k / SWEEP_SUP_NA
        px = int(round(x + r * math.cos(a)))
        py = int(round(y + r * math.sin(a)))
        if 0 <= py < H and 0 <= px < W and dm_dil[py, px]:
            hit += 1
    return hit / float(SWEEP_SUP_NA)


def sweep_radii_for(expl):
    """刀⑥a 按帧内已检测球的实测半径定微扫半径档。

    固定档 (10,13,16) 只对球径 ~12px 的帧成立；球径 26px 的帧微扫等于用半尺寸
    圈乱套（标注实测该帧 24/24 全错）。expl 不足 SWEEP_MIN_EXPL 圈时中位不可信 →
    退回固定档（行为与旧版一致）。
    """
    if not SWEEP_ADAPT:
        return SWEEP_RADII
    rs = sorted(float(r) for (_, _, r) in expl if r and r > 0)
    if len(rs) < SWEEP_MIN_EXPL:
        return SWEEP_RADII
    med = rs[len(rs) // 2]
    return tuple(round(med * s, 2) for s in (0.85, 1.0, 1.15))


# ================= 第一层：v4 底座补扫 =================
def run_frame_v4(g, expl, dm=None, bright_seeds=None,
                 use_sweep=True, use_bright=True):
    """四种子源补扫。dm / bright_seeds 可外部注入（同帧缓存复用，输出逐位不变）。
    返回 (去重圈列表, seed 数, 过门数, 微扫簇数, 簇总数)。
    """
    H0, W0 = g.shape
    if dm is None:
        dm = dark_ring_mask(g)
    um = unexplained_band(dm, expl)
    um2 = cv2.morphologyEx(um, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    ys_all, xs_all = np.nonzero(um2)
    passes = []
    split_passes = []    # ②b 双球拆分结果（最后追加，旧圈先占位 → 只增不减）
    clumps = []          # ④ 待微扫候选 (area, x0, y0, x1, y1)
    n_seed = 0

    if len(xs_all):
        n, lab, stats, cent = cv2.connectedComponentsWithStats(um2, 8)
        labs = lab[ys_all, xs_all]
        order = np.argsort(labs, kind="stable")
        ys_s, xs_s, labs_s = ys_all[order], xs_all[order], labs[order]
        bounds = np.searchsorted(labs_s, np.arange(n + 1))
        for i in range(1, n):
            a, b = bounds[i], bounds[i + 1]
            if b - a < MIN_PX:
                continue
            cxs, cys = xs_s[a:b].astype(float), ys_s[a:b].astype(float)
            cx0, cy0 = float(cxs.mean()), float(cys.mean())
            # ① 拟合种子（不管 rms 都送门）
            cf = fit_circle(cxs, cys)
            res = None
            if cf:
                fcx, fcy, fr, frms = cf
                res = gate_seed(g, fcx, fcy, [fr * s for s in (0.9, 1.0, 1.1)])
                n_seed += 3
            # ② v2 式 fallback：拟合失败或 rms 超阈 → 质心+maxdist 缩放
            if res is None:
                rad = float(np.sqrt(((cxs - cx0) ** 2 + (cys - cy0) ** 2).max()))
                if cf is None or cf[3] > FB_RMS(cf[2]):
                    res = gate_seed(g, cx0, cy0, [max(6.0, rad * s) for s in (0.55, 0.7, 0.85)])
                    n_seed += 3
            # ②b 双球簇拆分回退（v4.2 刀②）：结果先收集、最后追加
            # 刀⑨（2026-10-27）：split 通道默认关闭，代码保留（--split 重开）
            if SPLIT_ON and res is None and b - a >= SPLIT_MIN_PX:
                split_passes.extend(split_doublet(g, cxs, cys))
            if res:
                passes.append((res["cx2"], res["cy2"], res["R2"]))
            if b - a >= SWEEP_AREA:
                x0 = max(0, int(cxs.min()) - SWEEP_PAD)
                y0 = max(0, int(cys.min()) - SWEEP_PAD)
                x1 = min(W0, int(cxs.max()) + SWEEP_PAD + 1)
                y1 = min(H0, int(cys.max()) + SWEEP_PAD + 1)
                clumps.append((b - a, x0, y0, x1, y1))

    # ③ 亮核种子（全帧；外部注入则复用同帧缓存）
    if use_bright:
        if bright_seeds is None:
            bright_seeds = bright_dt_seeds(g)
        for (cx, cy, dt_r) in bright_seeds:
            res = gate_seed(g, cx, cy, [dt_r * s for s in (0.9, 1.0, 1.2, 1.5)])
            n_seed += 4
            if res:
                # 刀⑦ bright 与 base 重叠即弃（base 已圈住该球 → bright 只是重复/错位）
                if BASE_OVL_ON and expl and any(
                        math.hypot(res["cx2"] - a, res["cy2"] - b)
                        < BASE_OVL_SEP * (res["R2"] + R) for (a, b, R) in expl):
                    continue
                passes.append((res["cx2"], res["cy2"], res["R2"]))

    # ④ 残余粘连簇微稠密扫（v4.2 刀① 逐格判定）：格点落在既有过门圈内
    #    才跳（省时间），其余照扫；passes 在循环中增长，新扫出的圈也
    #    会抑制后续格点 → 不会重复打已覆盖区域。
    n_sweep = 0
    if use_sweep:
        sradii = sweep_radii_for(expl)      # 刀⑥a 帧自适应半径档
        if SWEEP_SUP_ON:
            _k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (SWEEP_SUP_DIL, SWEEP_SUP_DIL))
            dm_dil = cv2.dilate(dm, _k)
        else:
            dm_dil = None
        clumps.sort(reverse=True, key=lambda t: t[0])
        for (area, x0, y0, x1, y1) in clumps[:MAX_SWEEP]:
            n_sweep += 1
            for cy in range(y0 + 3, y1 - 2, SWEEP_STRIDE):
                for cx in range(x0 + 3, x1 - 2, SWEEP_STRIDE):
                    if any(math.hypot(cx - a, cy - b) < R for (a, b, R) in passes):
                        continue
                    res = gate_seed(g, float(cx), float(cy), sradii, drift=True)
                    if res and dm_dil is not None:
                        # 刀⑥c 圆周必须是连续暗环（球缝凑出的零碎弧 → 砍，且不占位）
                        if mask_support(dm_dil, res["cx2"], res["cy2"],
                                        res["R2"]) < SWEEP_SUP_MIN:
                            res = None
                    n_seed += 1
                    if res:
                        passes.append((res["cx2"], res["cy2"], res["R2"]))

    # ②b 结果并入（在微扫之后 → 去重时旧圈/微扫圈先占位）
    passes += split_passes

    # 去重（内部 → expl）
    uniq = []
    for p in passes:
        ok = True
        for q in uniq:
            if math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5 * (p[2] + q[2]):
                ok = False
                break
        if ok:
            for q in expl:
                if math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5 * (p[2] + q[2]):
                    ok = False
                    break
        if ok:
            uniq.append(p)
    return uniq, n_seed, len(passes), n_sweep, len(clumps)


# ================= 第二层：CLEAN 迭代（模块A） =================
def dedup_passes(passes, explained):
    uniq = []
    for p in passes:
        ok = True
        for q in uniq:
            if math.hypot(p[0] - q[0], p[1] - q[1]) < DEDUP_FRAC * (p[2] + q[2]):
                ok = False
                break
        if ok:
            for q in explained:
                if math.hypot(p[0] - q[0], p[1] - q[1]) < DEDUP_FRAC * (p[2] + q[2]):
                    ok = False
                    break
        if ok:
            uniq.append(p)
    return uniq


def clean_scan(g, explained, n_iters=CLEAN_ITERS, dm=None, bright_seeds=None,
               use_bright=True):
    """迭代：同款种子+门，但新圈回喂解释集。返回 (新增圈, 每轮统计)。
    dm / bright_seeds：同帧缓存注入（性能刀②，同帧复用、输出逐位不变）。
    """
    if dm is None:
        dm = dark_ring_mask(g)
    if bright_seeds is None:
        bright_seeds = bright_dt_seeds(g)
    new_all, stats = [], []
    explained = list(explained)
    for it in range(n_iters):
        um = unexplained_band(dm, explained)
        um2 = cv2.morphologyEx(um, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        passes = []
        n_seed = 0
        if cv2.countNonZero(um2):
            n, lab, statsC, cent = cv2.connectedComponentsWithStats(um2, 8)
            for i in range(1, n):
                a = statsC[i, cv2.CC_STAT_AREA]
                if a < MIN_PX:
                    continue
                mask_i = (lab == i)
                ys_, xs_ = np.nonzero(mask_i)
                cxs, cys = xs_.astype(float), ys_.astype(float)
                cx0, cy0 = float(cxs.mean()), float(cys.mean())
                cf = fit_circle(cxs, cys)
                res = None
                if cf:
                    fcx, fcy, fr, frms = cf
                    res = gate_seed(g, fcx, fcy, [fr * s for s in (0.9, 1.0, 1.1)])
                    n_seed += 3
                if res is None:
                    rad = float(np.sqrt(((cxs - cx0) ** 2 + (cys - cy0) ** 2).max()))
                    if cf is None or cf[3] > FB_RMS(cf[2]):
                        res = gate_seed(g, cx0, cy0,
                                        [max(6.0, rad * s) for s in (0.55, 0.7, 0.85)])
                        n_seed += 3
                if res:
                    passes.append((res["cx2"], res["cy2"], res["R2"]))
        # 亮核种子每轮都跑（CLEAN 第二轮常在残差里冒出新亮核；同帧缓存复用）
        if use_bright:
            for (cx, cy, dt_r) in bright_seeds:
                if any(math.hypot(cx - q[0], cy - q[1]) <= q[2] for q in explained):
                    continue
                res = gate_seed(g, cx, cy, [dt_r * s for s in (0.9, 1.0, 1.2, 1.5)])
                n_seed += 4
                if res:
                    # 刀⑦ 同上：bright 与已圈球重叠即弃
                    if BASE_OVL_ON and explained and any(
                            math.hypot(res["cx2"] - q[0], res["cy2"] - q[1])
                            < BASE_OVL_SEP * (res["R2"] + q[2]) for q in explained):
                        continue
                    passes.append((res["cx2"], res["cy2"], res["R2"]))
        new = dedup_passes(passes, explained)
        stats.append(dict(iter=it + 1, seeds=n_seed, passed=len(passes), new=len(new)))
        if not new:
            break
        new_all += new
        explained += new      # ← CLEAN 回喂
    return new_all, stats


# ================= 第三层：DAOPHOT 双圆联合拟合（模块B） =================
def bright_peaks_in(g, x0, y0, x1, y1, min_dt=5.0, min_dist=7):
    """指定窗口内的亮核 dt 峰"""
    sub = g[y0:y1, x0:x1].astype(np.float32)
    if sub.size == 0:
        return []
    gf = sub
    bgm = cv2.GaussianBlur(gf, (0, 0), 31)
    sd = float(np.median(np.abs(gf - bgm))) * 1.4826
    bright = (gf > bgm + 0.6 * sd).astype(np.uint8)
    dt = cv2.distanceTransform(bright, cv2.DIST_L2, 5)
    k = cv2.getStructuringElement(cv2.MORPH_RECT,
                                  (2 * min_dist + 1, 2 * min_dist + 1))
    mx = cv2.dilate(dt, k)
    peaks = (dt == mx) & (dt >= min_dt)
    ys, xs = np.nonzero(peaks)
    out = [(float(x + x0), float(y + y0), float(dt[y, x])) for x, y in zip(xs, ys)]
    out.sort(key=lambda t: -t[2])
    return out


def joint_two_fit(xs, ys, init):
    """EM 双圆联合拟合。init = [(cx,cy,r0), (cx,cy,r0)]。返回两圆或 None"""
    c = [list(t) for t in init]
    pts_x, pts_y = xs.copy(), ys.copy()
    for _ in range(EM_ITERS):
        d1 = np.hypot(pts_x - c[0][0], pts_y - c[0][1]) - c[0][2]
        d2 = np.hypot(pts_x - c[1][0], pts_y - c[1][1]) - c[1][2]
        assign = np.abs(d1) <= np.abs(d2)
        fitted = []
        for s in (assign, ~assign):
            fx, fy = pts_x[s], pts_y[s]
            if len(fx) < JOINT_MIN_PX:
                return None
            cf = fit_circle(fx, fy)
            if cf is None:
                return None
            fitted.append([cf[0], cf[1], cf[2]])
        shift = max(math.hypot(fitted[i][0] - c[i][0], fitted[i][1] - c[i][1])
                    for i in (0, 1))
        c = fitted
        if shift < 0.3:
            break
    # 两圆必须分开且都在合理范围
    dd = math.hypot(c[0][0] - c[1][0], c[0][1] - c[1][1])
    if dd < 0.5 * (c[0][2] + c[1][2]):
        return None
    for cc in c:
        if not (R_MIN <= cc[2] <= R_MAX):
            return None
    return c


def daophot_clump(g, x0, y0, x1, y1, um_mask):
    """对残余簇窗口做双圆联合拟合试探。返回过门的圈列表"""
    peaks = bright_peaks_in(g, x0, y0, x1, y1)
    if len(peaks) < 2:
        return []
    p1, p2 = peaks[0], peaks[1]
    # r0：峰到窗口内该簇像素的中位距离（截断）
    ys_, xs_ = np.nonzero(um_mask[y0:y1, x0:x1])
    if len(xs_) < 2 * JOINT_MIN_PX:
        return []
    cxs, cys = xs_.astype(float) + x0, ys_.astype(float) + y0
    init = []
    for (px, py, pdt) in (p1, p2):
        d = np.hypot(cxs - px, cys - py)
        r0 = float(np.median(d[d < np.percentile(d, 60)])) if (d < np.percentile(d, 60)).any() else pdt
        init.append([px, py, float(np.clip(r0, R_MIN, R_MAX))])
    j = joint_two_fit(cxs, cys, init)
    if j is None:
        return []
    out = []
    for (cx, cy, r) in j:
        res = gate_seed(g, cx, cy, [r * s for s in (0.9, 1.0, 1.1)])
        if res:
            out.append((res["cx2"], res["cy2"], res["R2"]))
    return out


# ================= 总入口：v5 = v4 底座 + CLEAN + DAOPHOT =================
def bright_mask(g):
    """全局亮区掩膜（与 bright_dt_seeds 同口径 + 3×3 开运算去噪点）。刀⑧用。"""
    gf = g.astype(np.float32)
    bgm = cv2.GaussianBlur(gf, (0, 0), LOBE_BG_SIGMA)
    sd = float(np.median(np.abs(gf - bgm))) * 1.4826
    bm = (gf > bgm + LOBE_THR_SIGMA * sd).astype(np.uint8)
    return cv2.morphologyEx(bm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def count_lobes(bm, x, y, r):
    """圈内（0.85R）亮瓣数。1 个 = 单球；≥3 个 = 一圆圈住多球。"""
    rr = int(round(LOBE_R_FRAC * r))
    if rr < 4:
        return 1
    H, W = bm.shape
    x0, y0 = int(round(x)) - rr, int(round(y)) - rr
    m = np.zeros((2 * rr + 1, 2 * rr + 1), np.uint8)
    cv2.circle(m, (rr, rr), rr, 1, -1)
    ys, xs = np.nonzero(m)
    xg, yg = xs + x0, ys + y0
    ok = (xg >= 0) & (xg < W) & (yg >= 0) & (yg < H)
    sub = np.zeros_like(m)
    if not ok.any():
        return 0
    sub[ys[ok], xs[ok]] = bm[yg[ok], xg[ok]]
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(sub, 8)
    amin = max(6, int(LOBE_MIN_AREA_FRAC * np.pi * r * r))
    return sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= amin)


def lobe_filter(bm, circles):
    """刀⑧：圈内亮瓣 ≥ LOBE_MAX+1 → 砍（纯减法，不占位、不改其它圈）。"""
    kept, n_cut = [], 0
    for p in circles:
        if count_lobes(bm, p[0], p[1], p[2]) > LOBE_MAX:
            n_cut += 1
            continue
        kept.append(p)
    return kept, n_cut


def halfgate_filter(g, circles, expl):
    """刀④ 半叠区差异化严审（2026-10-23 用户拍板）。

    sep = 圆心距/(r1+r2) 对最近解释圈（expl = kept∪ring，不含 v5 自身）。
    sep∈[0.7,0.9) 且 B 门谷数 n<9 → 砍。治理「贴着真球的歪圈」——11 条单圈
    局部判据轴全灭后，首条活下来的两变量组合（几何位置 × 证据强度）。
    n 在最终输出坐标上重放 BG.evaluate 取得；出画圈 B 门给低 n 也会被砍
    （8 个出画圈附带清理，裁图目检 197/197 全部该砍）。
    验收：189 预期 + 8 出画附带；4 开发帧救回 M 型全安全（sep=0.00）；
    DSC 四帧 402 圈砍 0 逐位不变。返回 (保留圈列表, 砍数)。
    """
    kept_out, n_cut = [], 0
    for p in circles:
        best = None
        for q in expl:
            if q[2] > 0:
                s = math.hypot(p[0] - q[0], p[1] - q[1]) / (p[2] + q[2])
                if best is None or s < best:
                    best = s
        if best is not None and HG_LO <= best < HG_HI:
            try:
                res = BG.evaluate(g, p[0], p[1], p[2])
            except Exception:
                res = None
            n = int(res.get("n") or 0) if res else 0
            if n < HG_NMIN:
                n_cut += 1
                continue
        kept_out.append(p)
    return kept_out, n_cut


def run_frame_v5(g, expl, clean_iters=CLEAN_ITERS, use_daophot=True,
                 use_sweep=True, use_bright=True, use_halfgate=True):
    """三层递进。返回 (圈列表, 详情dict)。

    性能刀②（2026-10-21）：dm / bright_seeds 每帧算一次，v4 轮 / CLEAN /
    DAOPHOT 三处注入复用——同输入同输出，逐位不变。
    """
    dm = dark_ring_mask(g)
    bseeds = bright_dt_seeds(g)
    # 第一层 = v4（保持向后一致：含微扫）
    base, n_seed4, n_pass4, n_sweep, n_clump = run_frame_v4(
        g, expl, dm=dm, bright_seeds=bseeds,
        use_sweep=use_sweep, use_bright=use_bright)
    detail = dict(seed4=n_seed4, pass4=n_pass4, sweep=n_sweep, clump=n_clump)
    explained = list(expl) + list(base)
    # 第二层 CLEAN 迭代
    new, cstats = ([], [])
    if clean_iters > 1:
        new, cstats = clean_scan(g, explained, n_iters=clean_iters - 1,
                                 dm=dm, bright_seeds=bseeds, use_bright=use_bright)
        explained += new
    detail["clean"] = cstats
    # 第三层 DAOPHOT 残余簇：v4+CLEAN 都没出圈的大簇
    dnew = []
    if use_daophot:
        um = unexplained_band(dm, explained)   # 复用同帧 dm
        um2 = cv2.morphologyEx(um, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        H0, W0 = g.shape
        n, lab, statsC, cent = cv2.connectedComponentsWithStats(um2, 8)
        cands = []
        for i in range(1, n):
            a = statsC[i, cv2.CC_STAT_AREA]
            if a < 200:
                continue
            x, y, w, h = (statsC[i, cv2.CC_STAT_LEFT], statsC[i, cv2.CC_STAT_TOP],
                          statsC[i, cv2.CC_STAT_WIDTH], statsC[i, cv2.CC_STAT_HEIGHT])
            has = any(x - 8 <= q[0] <= x + w + 8 and y - 8 <= q[1] <= y + h + 8
                      for q in explained)
            if has:
                continue
            cands.append((a, max(0, x - 6), max(0, y - 6),
                          min(W0, x + w + 7), min(H0, y + h + 7)))
        cands.sort(reverse=True, key=lambda t: t[0])
        detail["daophot_tried"] = len(cands[:10])
        for (a, x0, y0, x1, y1) in cands[:10]:
            got = daophot_clump(g, x0, y0, x1, y1, um)
            for p in got:
                if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= DEDUP_FRAC * (p[2] + q[2])
                       for q in explained):
                    dnew.append(p)
                    explained.append(p)
    detail["clean_new"] = len(new)
    detail["daophot_new"] = len(dnew)
    outs = list(base) + new + dnew
    # 刀④ 半叠区严审（输出端纯减法；--no-halfgate 时逐位同加刀前）
    if use_halfgate and expl:
        outs, n_hg = halfgate_filter(g, outs, expl)
    else:
        n_hg = 0
    detail["halfgate_cut"] = n_hg
    # 刀⑧ 圈内亮瓣数闸（输出端纯减法；--no-lobes 时逐位同加刀前）
    if LOBES_ON and outs:
        outs, n_lb = lobe_filter(bright_mask(g), outs)
    else:
        n_lb = 0
    detail["lobe_cut"] = n_lb
    return outs, detail


# ================= CLI =================
def _load_expl(args):
    """expl（已解释集）：baseline kept CSV + ring JSON 合并"""
    expl_all = {}
    if args.baseline:
        for r in csv.DictReader(open(args.baseline, encoding="utf-8")):
            if "cls" in r and r["cls"] != "kept":
                continue
            if not (r.get("d_B") or r.get("d")):
                continue
            cx = float(r["cx2"]) if r.get("cx2") else float(r["x"])
            cy = float(r["cy2"]) if r.get("cy2") else float(r["y"])
            d = float(r["d_B"]) if r.get("d_B") else float(r["d"])
            expl_all.setdefault(r["frame"], []).append((cx, cy, d / 2))
    if args.ring:
        ring = json.loads(Path(args.ring).read_text(encoding="utf-8"))
        for f, lst in ring.items():
            expl_all.setdefault(f, []).extend((a, b, rr) for a, b, rr in lst)
    return expl_all


def _run_one(job):
    """单帧 worker（多进程入口；计算逻辑与串行完全一致）。"""
    global SWEEP_ADAPT, SWEEP_SUP_ON, BASE_OVL_ON, LOBES_ON, SPLIT_ON
    (fpath, expl, mode, clean_iters, use_daophot, use_sweep, use_bright,
     use_halfgate, use_sweep_adapt, use_sweep_sup, use_baseovl,
     use_lobes, use_split, prom_min) = job
    # 刀⑥/⑦/⑧/⑨ 开关随 job 传（multiprocessing spawn 不继承模块全局）
    SWEEP_ADAPT = use_sweep_adapt
    SWEEP_SUP_ON = use_sweep_sup
    BASE_OVL_ON = use_baseovl
    LOBES_ON = use_lobes
    SPLIT_ON = use_split
    # 凸起门按 job 透传（spawn 不继承；None = 用 s6_b_gate 的默认 PROM_MIN）
    if prom_min is not None:
        BG.PROM_MIN = prom_min
    fpath = Path(fpath)
    g = BG.load_gray(fpath).astype(np.float32)
    t0 = time.time()
    if mode == "v5":
        outs, detail = run_frame_v5(g, expl, clean_iters=clean_iters,
                                    use_daophot=use_daophot,
                                    use_sweep=use_sweep, use_bright=use_bright,
                                    use_halfgate=use_halfgate)
        hg = (f" 半叠砍={detail['halfgate_cut']}" if detail["halfgate_cut"] else "")
        lb = (f" 瓣砍={detail['lobe_cut']}" if detail.get("lobe_cut") else "")
        tag = (f"v4+={len(outs) - detail['clean_new'] - detail['daophot_new']} "
               f"clean+={detail['clean_new']} dao+={detail['daophot_new']}{hg}{lb}")
    else:
        outs, n_seed, n_pass, n_sweep, n_clump = run_frame_v4(
            g, expl, use_sweep=use_sweep, use_bright=use_bright)
        tag = f"种子={n_seed} 过门={n_pass} 微扫={n_sweep}/{n_clump}簇"
    return fpath.name, [list(map(float, p)) for p in outs], time.time() - t0, tag


def main():
    ap = argparse.ArgumentParser(description="S6-CR 粘连簇救回通道")
    ap.add_argument("--frames", required=True,
                    help="帧目录（支持 jpg/png/tif/bmp 等）")
    ap.add_argument("--baseline", help="kept CSV（expl 来源，可选）")
    ap.add_argument("--ring", help="S6-R 过门圈 JSON（expl 来源，可选）")
    ap.add_argument("--out", help="输出 CSV（默认 <帧目录>/_clump_extras.csv）")
    ap.add_argument("--mode", choices=["v5", "v4"], default="v5")
    ap.add_argument("--iters", type=int, default=CLEAN_ITERS,
                    help="CLEAN 总轮数（1=关 CLEAN；仅 v5）")
    ap.add_argument("--workers", type=int, default=1, help="进程数（内存紧张限 2）")
    ap.add_argument("--no-sweep", action="store_true", help="关微稠密扫")
    ap.add_argument("--no-bright", action="store_true", help="关亮核种子")
    ap.add_argument("--no-daophot", action="store_true", help="关 DAOPHOT 层")
    ap.add_argument("--no-halfgate", action="store_true",
                    help="关刀④半叠区严审（开时输出=加刀前逐位减法）")
    ap.add_argument("--no-sweep-adapt", action="store_true",
                    help="关刀⑥a 微扫半径帧自适应（退回固定档 10/13/16）")
    ap.add_argument("--no-sweep-sup", action="store_true",
                    help="关刀⑥c 微扫圆周暗环掩膜支撑率闸（保留⑥a/⑥b）")
    ap.add_argument("--no-baseovl", action="store_true",
                    help="关刀⑦ bright 与 base 重叠即弃（开时=对焦好的帧不再重复圈球）")
    ap.add_argument("--select", help="逗号分隔帧名子串过滤，如 00010,00030")
    ap.add_argument("--no-lobes", action="store_true",
                    help="关刀⑧圈内亮瓣数闸（nlobe>=3 弃；开时=纯减法）")
    ap.add_argument("--split", action="store_true",
                    help="重开刀⑨ split 双球拆分通道（默认关，技术保留）")
    ap.add_argument("--prom-min", type=float, default=None,
                    help="覆盖 B 门的凸起度下限 PROM_MIN（默认 12）。跨体系换数据时"
                         "这是第一个要重标的参数：相位型暗环球约 80 灰度，"
                         "吸收型实心暗球只有 12–30，不降此门会大面积漏检")
    ap.add_argument("--limit", type=int, help="最多跑前 N 帧")
    a = ap.parse_args()

    frdir = Path(a.frames)
    frames = sorted(str(p) for p in frdir.iterdir()
                    if p.suffix.lower() in IMG_EXT)
    if a.select:
        pats = a.select.split(",")
        frames = [f for f in frames if any(p in f for p in pats)]
    if a.limit:
        frames = frames[:a.limit]
    if not frames:
        raise SystemExit(f"no image files in {frdir} (looked for {list(IMG_EXT)}); "
                         f"check --frames and --select")

    expl_all = _load_expl(a)
    out_path = Path(a.out) if a.out else frdir / "_clump_extras.csv"

    print(f"S6-CR: mode={a.mode} iters={a.iters} workers={a.workers} "
          f"sweep={not a.no_sweep} bright={not a.no_bright} "
          f"daophot={not a.no_daophot} halfgate={not a.no_halfgate} "
          f"sweep_adapt={not a.no_sweep_adapt} sweep_sup={not a.no_sweep_sup} "
          f"baseovl={not a.no_baseovl} lobes={not a.no_lobes} "
          f"split={a.split} prom_min={a.prom_min} | {len(frames)} 帧", flush=True)
    t_all = time.time()
    jobs = [(f, (expl_all.get(Path(f).name) or expl_all.get(Path(f).stem)
                 or expl_all.get(str(Path(f))) or []), a.mode, a.iters,
             not a.no_daophot, not a.no_sweep, not a.no_bright,
             not a.no_halfgate, not a.no_sweep_adapt, not a.no_sweep_sup,
             not a.no_baseovl, not a.no_lobes, a.split, a.prom_min)
            for f in frames]

    if a.workers > 1:
        from multiprocessing import Pool
        with Pool(a.workers) as pool:
            results = pool.map(_run_one, jobs)
    else:
        results = [_run_one(j) for j in jobs]

    n_tot = 0
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "cx", "cy", "r"])
        for name, outs, el, tag in results:
            n_tot += len(outs)
            print(f"{name}: 出圈={len(outs)} {tag} ({el:.0f}s)", flush=True)
            for (cx, cy, r) in outs:
                w.writerow([name, f"{cx:.1f}", f"{cy:.1f}", f"{r:.1f}"])
    print(f"\n=== 合计 {n_tot} 圈 → {out_path}  用时 {time.time()-t_all:.0f}s ===",
          flush=True)


if __name__ == "__main__":
    main()
