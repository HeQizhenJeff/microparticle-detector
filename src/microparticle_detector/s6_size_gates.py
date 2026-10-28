#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""s6_size_gates — B PASS 之后的粒径分选闸门（P0–P3），2026-10-12 固化。

> 定位：对象级后处理——**只回答「这个已过 B 门的圈，能不能进微球粒径表」**。
> 上游依赖：s6_b_gate（提供 ok / d_M / d_B / cx2 / cy2 / rn2 / n）。
> 产物类别 cls：breject | giant | grow | dup | resid | kept（互斥，按序判定）。
> 由工作目录 `261003_triage/_size_gates.py` 固化而来（三轮迭代 + 45 格金标准回归）。

四道闸（按序）：

P0 团簇道（GIANT）：d_B > GIANT_DM(110 px ≈ 8.38 µm)
   依据：用户 2026-10-09 鉴定「d>110 px 组 = 油滴挨在一起」；2026-10-12 抽样
   目检 9/9 = 多球团簇或纹理条纹（圈内 3–5 颗球，无单球可圈，用户「橙圈全
   都是圈错的」正是此意）→ 单列分道，不进微球表。

P1 半径增长闸（GROW）：d_M ≥ 40 px ∧ d_B/d_M > 1.25 ∧ rn2 > GROW_RESCUE_MAX(0.06)
   依据：B 拟合圆相对种子异常外扩 = 套住邻球/混杂区。45 格金标准 ratio 全在
   0.85–1.06，坏圈 1.26–1.96，中间是空的。只对 d_M≥40 px 生效——小种子 B 向
   外扩找真环是设计行为（30–40px 档中位比 1.48），且小种子未标定。
   🔴 rn2 豁免（2026-10-12 用户 12 格目检裁定）：grow 池里「种子测小、B 修正
   到位」的准圈占多数（12 格中 11 格，rn2 0.006–0.052），唯一坏格 rn2=0.0836
   → 按 rn2 双峰切：**rn2 ≤ 0.06 救回（216/242），rn2 > 0.06 仍剔（26/242，
   目检全为跨球/空圈）**。豁免逻辑 = rn2 低说明 B 的环是真实灰度环、拟合自洽，
   ratio 高只证明机器种子测小，不证明 B 错。用户原话「挺怕 P1 收太紧会挑的太
   有代表性，忽略一些重要的东西」→ 此闸宁松勿紧，只留拟合不自洽的。

P2 同球去重（DUP）：同帧两 kept 圈拟合圆心距 < DUP_FRAC(0.5)×min(R1,R2)（d_B≥30px）
   两枚机器种子撞同一颗球、B 各自收敛到同一环（实测拟合心距 = 0px）→ 同球重复
   测量。保留质量优者（rn2 小者优先，其次 n 大者），另一枚标 dup。
   🔴 必须用**拟合圆心**判：种子心距不可靠——相邻两球种子心距 17–31px 但拟合已
   各归各位（拟合心距 54px），按种子判会误杀真·相邻球。

P3 残差闸（RESID）：d_M ≥ 40 px ∧ rn2 > RES_MAX(0.04)
   B 自身 PASS 门限 rn≤0.10 过松；45 格金标准好球 rn 全部 ≤0.0219（门限 0.04
   有 1.8× 边距）；rn>0.04 样本目检多为包络圈/偏移圈（用户指出的「没圈中」主要
   形态之一）。只对 ≥40px 生效——<40px 无金标准、且小球 rn 受像素格限制天然偏高。
   🔴 经 P1 豁免救回的对象**不走 P3**（两闸标定人群不同，勿混用）：P3 的 0.04
   标定于 ratio≤1.06 人群（含 7.9µm 包络圈 rn=0.0579）；被救回的 grow 是
   ratio>1.25 人群，其阈值由用户 12 格目检标定 = 0.06。救回条件本身已含 rn2 检查。

🔴 负结果（勿再试，除非先补标注）：
   ① P2b「圈内竞争」（别的够大球心落进拟合圆 → 拒）：好球圈内 5/14 有竞争种子
      （最近 0.31R、竞争者 d_M 高至 208px），唯一坏球在 0.53R——完全重叠，任何
      阈值都误杀，被 45 格金标准否决。
   ② 扇区覆盖数 n ≥ 13：金标准好球 min n=13 但目检 n=9–12 有多个完好圈（13.5%
      杀伤面一半误杀）。
   ③ comp 判别量（拟合圆 0.85R 内有无别的够大种子中心）：对 grow 池零判别力
      （全池 0%）——跨球对象是机器掩码把两球并成一个种子、圈内根本没有第二枚
      种子。与 ②① 同根：竞争类判据在本体系抓不到并球。

🔴 标注图红线：**圈必须画在 B 拟合圆心 (cx2,cy2)，不是种子圆心 (x,y)**
   （v1 显示 bug：画种子心 → kept 圆心偏移中位 8.3px、最大 34.8px，用户看到的
   「没圈中」很大程度是显示错位）。渲染脚本见 s6_size_annot.py。

已知边界：
   ① 45 格金标准来自 14_2h 单视频 4 帧（2 对焦+2 失焦）；13_2h 跨视频对象级
      金标准 2026-10-12 起标注中——**未打分前本节战绩只对 14_2h 成立**；
   ② 唯一已知漏网 29-5（rn=0.0207、ratio≈1.05、dup）——「圈内独占性」问题，
      见负结果 ①；
   ③ P1 豁免放行的 216 个按阈值批量放行、非逐个目检（12 格标定阈值）；其中
      ratio 1.6–1.9 的 13 个属抽查面，如发现系统性套邻球再加 ratio 上限联合判。

用法：
  模块： from s6_size_gates import classify, apply_gates, GIANT_DM, GROW_MAX
  回归： python s6_size_gates.py --gold <triage目录> [--seg TPMT_14_2h]
        [--labels <json>] [--cands <json>] [--csv <objects.csv>]
  摘要： python s6_size_gates.py --objects <objects.csv>
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

GIANT_DM = 110.0        # px，巨球/团簇分道下限（用户 10-09 鉴定）
GROW_MAX = 1.25         # d_B/d_M 上限（d_M≥40px 种子）
GROW_MIN_SEED = 40.0    # px，增长闸生效的种子下限
GROW_RESCUE_MAX = 0.06  # grow 豁免上限：rn2≤此值 = 种子测小、B 修正到位
                        #（用户 12 格目检标定：好圈 max 0.0519 / 坏圈 0.0836）
DUP_FRAC = 0.5          # 拟合心距 < DUP_FRAC×min(R1,R2) → 同球重复
DUP_MIN_DB = 30.0       # px，去重只管 d_B≥30px 的圈（更小的圈贴太近是常态）
RES_MAX = 0.04          # rn2 上限（金标准好球 max 0.0219，×1.8 边距）
RES_MIN_SEED = 40.0     # px，残差闸只在已验证量程内生效


def _to_float(x):
    """容错转 float；空/非数返回 None。"""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None      # nan 也当 None


def classify(ok, d_M, d_B, rn2=None):
    """返回 'breject' | 'giant' | 'grow' | 'kept'。d_B 允许 nan（拟合失败时）。
    rn2 给出且 ≤ GROW_RESCUE_MAX 时，grow 豁免为 kept（种子测小、B 修正到位）。
    （resid/dup 在 apply_gates 内追加判定）"""
    if not ok or d_B != d_B:      # d_B != d_B 即 nan
        return "breject"
    if d_B > GIANT_DM:
        return "giant"
    if d_M >= GROW_MIN_SEED and (d_B / d_M) > GROW_MAX:
        rn = _to_float(rn2)
        if rn is not None and rn <= GROW_RESCUE_MAX:
            return "kept"
        return "grow"
    return "kept"


def _is_rescued(r):
    """kept 但 ratio>1.25 且 d_M≥40 → 只能是经豁免救回的 grow（不变式）。"""
    return (r["cls"] == "kept" and r["d_M"] >= GROW_MIN_SEED
            and r["d_B"] == r["d_B"] and r["d_B"] / r["d_M"] > GROW_MAX)


def apply_gates(rows, has_fit=True, allow_missing_rn2=False):
    """逐对象 classify（含 P1 rn2 豁免）+ 帧内 P2 去重 + P3 残差闸。
    rows 需含 seg/frame/d_M/d_B/ok/rn2；P2 还需拟合圆心 cx2/cy2
    （has_fit=False 时只跳过 P2，P3 照常）。

    缺 rn2 的防护（2026-10-28）：旧实现把 rn2 缺失当 0.0（=完美圆），
    P3 残差闸会**静默全失效**且不报错。现在：
      - has_fit=True 且整表无一条有效 rn2 → raise（设计上不可能，必有 bug）
      - has_fit=False 且无 rn2 → stderr 明确提示残差闸不生效（无拟合表的预期）
      - 个别行 rn2 为空且落在 P3 生效范围内 → 计数并在 stderr 警告
    确实要跳过残差闸时显式传 allow_missing_rn2=True。

    就地写 r['cls']，返回 rows。"""
    if rows and not allow_missing_rn2:
        n_rn = sum(1 for r in rows if _to_float(r.get("rn2")) is not None)
        if n_rn == 0:
            if has_fit:
                raise ValueError(
                    f"apply_gates: 输入 {len(rows)} 行，没有一条有效 rn2 值。"
                    f"has_fit=True 的表必然带拟合残差，缺 rn2 说明上游列名/导出"
                    f"出错；旧行为会把它当 0.0，令 P3 残差闸静默全失效。"
                    f"确实要跳过残差闸请显式传 allow_missing_rn2=True。")
            print(f"[apply_gates] has_fit=False 且表内无 rn2：P3 残差闸不生效"
                  f"（无拟合表的预期行为，但 resid 类将不会出现）",
                  file=sys.stderr)
    for r in rows:
        r["cls"] = classify(r["ok"], r["d_M"], r["d_B"], rn2=r.get("rn2"))
    if has_fit:
        _dedup(rows)
    # P3 残差闸：d_M ≥ 40px 且 rn2 过高（金标准好球 max 0.0219）
    # 经 P1 豁免救回的 grow 不走 P3（标定人群不同，见 docstring）
    n_blank_p3 = 0
    for r in rows:
        if r["cls"] != "kept" or r["d_M"] < RES_MIN_SEED:
            continue
        if _is_rescued(r):
            continue
        rn = _to_float(r.get("rn2"))
        if rn is None:
            n_blank_p3 += 1
            rn = 0.0
        if rn > RES_MAX:
            r["cls"] = "resid"
    if n_blank_p3:
        print(f"[apply_gates] 警告：{n_blank_p3} 个 d_M≥{RES_MIN_SEED:.0f}px 的"
              f"圈 rn2 为空，已按 0.0 放行（P3 对它们无判定力）",
              file=sys.stderr)
    return rows


def _dedup(rows):
    """P2 同球去重（拟合圆心几乎重合 → 保留 rn2 优者）。"""
    byf = defaultdict(list)
    for r in rows:
        if r["cls"] == "kept" and r["d_B"] >= DUP_MIN_DB:
            cx, cy = r.get("cx2"), r.get("cy2")
            if cx is None or cy is None or cx != cx or cy != cy:
                continue
            byf[(r["seg"], r["frame"])].append(r)
    for rs in byf.values():
        # 冲突对：拟合圆心几乎重合（键用 id，dict 不可哈希）
        conflicts = {}              # id(r) -> [r, [同球其它对象]]
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                d = math.hypot(a["cx2"] - b["cx2"], a["cy2"] - b["cy2"])
                if d < DUP_FRAC * min(a["d_B"], b["d_B"]) / 2.0:
                    conflicts.setdefault(id(a), [a, []])[1].append(b)
                    conflicts.setdefault(id(b), [b, []])[1].append(a)
        if not conflicts:
            continue
        # 质量序贪心：rn2 小者优，其次 n 大者
        def qual(r):
            rn = r.get("rn2")
            rn = float(rn) if rn is not None else 1e9
            try:
                n = int(r.get("n") or 0)
            except Exception:
                n = 0
            return (rn, -n)
        alive = set(conflicts)
        for key in sorted(conflicts, key=lambda k: qual(conflicts[k][0])):
            r, others = conflicts[key]
            if key not in alive:
                continue
            # r 胜出 → 它的冲突者全部标 dup
            for o in others:
                ko = id(o)
                if ko in alive and ko != key:
                    alive.discard(ko)
                    o["cls"] = "dup"
    return rows


# ------------------------------------------------------------------ CLI

def _load_objects(csv_path):
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["x"] = float(r["x"]); r["y"] = float(r["y"])
            r["d_M"] = float(r["d_M"])
            r["d_B"] = float(r["d_B"]) if r["d_B"] else float("nan")
            r["ok"] = r["ok"] in ("True", "true", "1")
            r["cx2"] = float(r["cx2"]) if r.get("cx2") else float("nan")
            r["cy2"] = float(r["cy2"]) if r.get("cy2") else float("nan")
            r["rn2"] = float(r["rn2"]) if r.get("rn2") else None
            rows.append(r)
    return rows


def _resolve(pool, r):
    """若 r 被标 dup，回溯到同球胜者（拟合圆重合的 kept）。
    返回 (实际测量该球的行或 None, 是否经 dup 合并)。"""
    if r["cls"] != "dup":
        return r, False
    for k in pool:
        if k is r or k["cls"] != "kept" or k["frame"] != r["frame"]:
            continue
        if k["cx2"] != k["cx2"]:
            continue
        d = math.hypot(k["cx2"] - r["cx2"], k["cy2"] - r["cy2"])
        if d < 0.5 * min(k["d_B"], r["d_B"]) / 2.0:
            return k, True
    return r, False


def run_gold(triage, seg, labels_name, cands_name, csv_name):
    """45 格金标准回归：误杀 = 0 才 PASS（exit 0），否则 exit 2。"""
    triage = Path(triage)
    cells = json.loads((triage / labels_name).read_text(encoding="utf-8"))["cells"]
    cands = {c["id"]: c for c in json.loads((triage / cands_name)
                                           .read_text(encoding="utf-8"))}
    rows = _load_objects(triage / csv_name)
    has_fit = any(r["cx2"] == r["cx2"] for r in rows)
    print(f"rows={len(rows)} has_fit={has_fit}  seg={seg}")
    apply_gates(rows, has_fit=has_fit)
    pool = [r for r in rows if r["seg"] == seg]

    def find(frame_no, x, y):
        best, bd = None, 1e9
        for r in pool:
            if r["frame"] != f"frame_{frame_no:05d}.jpg":
                continue
            d = math.hypot(r["x"] - x, r["y"] - y)
            if d < bd:
                bd, best = d, r
        return best, bd

    n_good_pass = n_kill_good = n_good_dup = 0
    n_bad_pass = n_bad_dup = 0
    lines = []
    for cid, v in sorted(cells.items(), key=lambda kv: (kv[1]["frame"], kv[1]["k"])):
        c = cands.get(cid)
        if not c:
            continue
        r, dist = find(v["frame"], c["c_x"], c["c_y"])
        if r is None or dist > 30:
            continue
        good = v["circ_v"] != "没圈住"
        if good and r["ok"]:
            n_good_pass += 1
            eff, merged = _resolve(pool, r)
            if eff["cls"] != "kept":
                n_kill_good += 1
                lines.append(f"  KILL-GOOD {cid} circ={v['circ_v']} cls={eff['cls']} "
                             f"dist={dist:.0f} d_M={eff['d_M']:.0f} d_B={eff['d_B']:.0f}")
            elif merged:
                n_good_dup += 1
                lines.append(f"  dup-合并 {cid} circ={v['circ_v']} → 胜者 d_B={eff['d_B']:.0f}"
                             f"（同一拟合圆，球仍被测量）")
        if not good and r["ok"]:
            n_bad_pass += 1
            eff, merged = _resolve(pool, r)
            if eff["cls"] != "kept":
                n_bad_dup += 1
                lines.append(f"  坏格被拦 {cid} circ={v['circ_v']} 经{r['cls']}"
                             f"{'→胜者' + eff['cls'] if merged else ''}")

    print(f"\n金标准好球 且 B PASS: {n_good_pass}")
    print(f"  其中被闸门标非 kept: {n_kill_good}  （=0 才算过）")
    print(f"  其中经 dup 合并（球仍被测量）: {n_good_dup}")
    print(f"金标准『没圈住』 且 B PASS: {n_bad_pass}，其中被闸门拦下: {n_bad_dup}")
    if lines:
        print("\n".join(lines))

    print(f"\n=== {seg} 全部 dup 对（金标准帧内）===")
    for r in [x for x in pool if x["cls"] == "dup"]:
        win = None
        for k in pool:
            if k["cls"] == "kept" and k["frame"] == r["frame"] and \
               math.hypot(k["cx2"] - r["cx2"], k["cy2"] - r["cy2"]) \
               < 0.5 * min(k["d_B"], r["d_B"]) / 2:
                win = k
        print(f"  {r['frame'][6:11]} dup@({r['x']:.0f},{r['y']:.0f}) d_M={r['d_M']:.0f} "
              f"d_B={r['d_B']:.0f} rn={r['rn2']}  胜者d_B={win['d_B'] if win else '?'}")

    ok = (n_kill_good == 0)
    print(f"\n{'PASS' if ok else 'FAIL'} — 误杀 {n_kill_good}")
    return 0 if ok else 2


def run_objects(csv_path):
    rows = _load_objects(csv_path)
    has_fit = any(r["cx2"] == r["cx2"] for r in rows)
    apply_gates(rows, has_fit=has_fit)
    per = defaultdict(lambda: defaultdict(int))
    for r in rows:
        per[r["seg"]][r["cls"]] += 1
    for seg, cnt in sorted(per.items()):
        tot = sum(cnt.values())
        keep = cnt.get("kept", 0)
        print(f"{seg}: 总 {tot}  kept {keep} ({keep / tot * 100:.0f}%)  "
              + " ".join(f"{k}={v}" for k, v in sorted(cnt.items()) if k != "kept"))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", metavar="TRIAGE_DIR",
                    help="金标准回归：读 labels/cands/objects.csv，误杀=0 才 exit 0")
    ap.add_argument("--seg", default="TPMT_14_2h")
    ap.add_argument("--labels", default=None,
                    help="标注 json（默认 <triage>/labels_<seg短名>_fig3objects.json）")
    ap.add_argument("--cands", default=None,
                    help="候选 json（默认 <triage>/select_fig3_review.json）")
    ap.add_argument("--csv", dest="csvname", default="_size_objects.csv")
    ap.add_argument("--objects", metavar="CSV", help="对 objects.csv 跑闸门并打印分类摘要")
    a = ap.parse_args()

    if a.gold:
        short = a.seg.replace("TPMT_", "")
        labels = a.labels or f"labels_{short}_fig3objects.json"
        cands = a.cands or "select_fig3_review.json"
        sys.exit(run_gold(a.gold, a.seg, labels, cands, a.csvname))
    if a.objects:
        sys.exit(run_objects(a.objects))
    ap.print_help()
