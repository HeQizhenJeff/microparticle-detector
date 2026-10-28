#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""s6_size_annot — 粒径分选实物标注图（P0–P3 彩圈 + µm 数字 + 10 µm 比例尺）。

用途：内部核验/用户抽查——肉眼核对「圈是不是套在球上、数字是不是这球的直径」。
**不入 ELN**（ELN 嵌图仍走 burn_eln.py 烧比例尺）。

配色（与 s6_size_gates 的 cls 一一对应）：
  白实线 = kept 入表（标 d_B µm）｜橙 = P0 团簇「簇」｜黄 = P1 增长闸「扩」
  紫虚线 = P2 同球重复「重」｜红 = P3 残差「残」
  青细线 = B REJECT（1px、无标签，仅示位；--no-reject 可退回完全不画）

🔴 B REJECT 必须画（2026-10-13 用户裁定，DSC_2307 通用性试跑后）：
   「宁缺毋滥 ≠ 放弃少数群，放弃会看不清真实情况」→ 此前 breject 完全不画，
   导致 F45 有 114 个「发现了但不给看」的球在图上呈现为"漏圈"，用户无法区分
   「检测漏了」与「检到了被拒」。改为青细线画出（1px、不写标签避免糊屏）。
   B 拒常无拟合（fit_fail）→ 圆心/半径退回种子 (x,y,d_M/2)。

🔴 标注图红线（2026-10-12 定）：**圈心一律用 B 拟合圆心 (cx2,cy2)**——入表口径
   真身；无拟合字段时对本帧现场跑 s6_b_gate.evaluate 补齐，缺失才退回种子心。
   教训：v1 画在种子心上 → kept 圆心偏移中位 8.3px、最大 34.8px，用户看到的
   「没圈中」很大程度是显示错位而非算法错误。
比例尺：右下白棒 + 「10 µm」在棒正上方水平居中（ELN 定稿样式，勿改）。

用法：
  python s6_size_annot.py --csv <objects.csv> --seg TPMT_14_2h --frame frame_00030.jpg
        [--framedir DIR] [--out DIR] [--um-per-px 0.0762] [--bar-um 10]
  framedir 省略时从 --frame 路径推导；out 默认当前目录。
依赖：numpy + PIL；s6_size_gates.py（同目录）；现场补齐拟合时另需 s6_b_gate.py。
"""
import argparse
import csv
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent          # 相对本文件定位，防技能目录搬迁
spec = importlib.util.spec_from_file_location(
    "s6_size_gates", str(HERE / "s6_size_gates.py"))
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="s6 全量对象表（含 x/y/d_M/d_B/ok/rn2/cx2/cy2）")
    ap.add_argument("--seg", required=True)
    ap.add_argument("--frame", required=True)
    ap.add_argument("--framedir", default=None,
                    help="帧目录；省略时从 --frame 的路径推导，仍无法确定则报错")
    ap.add_argument("--out", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--um-per-px", type=float, default=0.0762)
    ap.add_argument("--bar-um", type=float, default=10.0)
    ap.add_argument("--no-reject", action="store_true",
                    help="不画 B REJECT 青线（退回 2026-10-13 前的旧版行为）")
    a = ap.parse_args()

    if a.framedir:
        framedir = Path(a.framedir)
    elif Path(a.frame).exists():
        framedir = Path(a.frame).parent
    else:
        ap.error("需要 --framedir（帧图所在目录），或把 --frame 写成完整路径")
    um, bar_um = a.um_per_px, a.bar_um
    bar_px = bar_um / um

    objs = []
    with open(a.csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["seg"] != a.seg or r["frame"] != a.frame:
                continue
            r["d_M"] = float(r["d_M"])
            r["d_B"] = float(r["d_B"]) if r["d_B"] else float("nan")
            r["d_B_um"] = float(r["d_B_um"]) if r.get("d_B_um") else float("nan")
            r["ok"] = r["ok"] in ("True", "true", "1")
            r["cx2"] = float(r["cx2"]) if r.get("cx2") else float("nan")
            r["cy2"] = float(r["cy2"]) if r.get("cy2") else float("nan")
            r["rn2"] = float(r["rn2"]) if r.get("rn2") else None
            objs.append(r)
    if not objs:
        sys.exit(f"no objects for {a.seg}/{a.frame}")
    has_fit = any(np.isfinite(r["cx2"]) for r in objs)
    if not has_fit:
        # CSV 无拟合圆心（旧版/重跑未完成）→ 对本帧现场跑 evaluate 补齐
        spec_b = importlib.util.spec_from_file_location(
            "s6_b_gate", str(HERE / "s6_b_gate.py"))
        bg = importlib.util.module_from_spec(spec_b)
        spec_b.loader.exec_module(bg)
        g = bg.load_gray(framedir / a.frame).astype(np.float32)
        for r in objs:
            e = bg.evaluate(g, float(r["x"]), float(r["y"]), r["d_M"] / 2.0)
            r["cx2"] = e.get("cx2", float("nan"))
            r["cy2"] = e.get("cy2", float("nan"))
            r["rn2"] = e.get("rn2")
        has_fit = True
        print(f"[annot] 现场 evaluate 补齐拟合圆心: {len(objs)} 对象")
    G.apply_gates(objs, has_fit=has_fit)

    im = Image.open(framedir / a.frame).convert("RGB")
    dr = ImageDraw.Draw(im)
    try:
        fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        fntb = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 19)
    except Exception:
        fnt = fntb = ImageFont.load_default()

    n = defaultdict(int)
    STYLE = {"kept": (255, 255, 255), "giant": (255, 170, 40), "grow": (255, 210, 0),
             "dup": (200, 120, 255), "resid": (255, 90, 90),
             "breject": (0, 220, 255)}
    TAG = {"kept": "", "giant": " 簇", "grow": " 扩", "dup": " 重", "resid": " 残"}
    for r in objs:
        cls = r["cls"]
        if cls == "breject" and a.no_reject:
            continue                                     # 旧版行为：全不画
        # 🔴 圆心：B 拟合圆心（入表真身）；缺失才退回种子
        if np.isfinite(r["cx2"]):
            x, y = r["cx2"], r["cy2"]
        else:
            x, y = float(r["x"]), float(r["y"])
        # B 拒常 fit_fail → d_B 为 nan，退回种子直径 d_M/2
        rad = r["d_B"] / 2.0 if np.isfinite(r["d_B"]) and r["d_B"] > 0 \
            else r["d_M"] / 2.0
        if not np.isfinite(rad) or rad <= 0:
            continue
        col = STYLE[cls]
        if cls == "breject":
            # 青细线：只示位不标注（1px，避免几百个圈糊屏）
            dr.ellipse([x - rad, y - rad, x + rad, y + rad], outline=col, width=1)
            n[cls] += 1
            continue
        if cls == "dup":
            bbox = [x - rad, y - rad, x + rad, y + rad]
            for a0 in range(0, 360, 24):
                dr.arc(bbox, a0, a0 + 14, fill=col, width=2)
        else:
            dr.ellipse([x - rad, y - rad, x + rad, y + rad], outline=col,
                       width=2 if cls == "kept" else 3)
        d_um = r["d_B"] * um if r["d_B_um"] != r["d_B_um"] else r["d_B_um"]
        lbl = f"{d_um:.1f}" + TAG[cls]
        dr.text((x + rad + 2, y - 8), lbl, font=fnt, fill=col,
                stroke_width=2, stroke_fill=(0, 0, 0))
        n[cls] += 1

    # 比例尺：右下角白棒，标签在棒正上方水平居中（ELN 定稿样式，勿改）
    W, H = im.size
    bx1 = W - 40
    bx0 = bx1 - bar_px
    by = H - 46
    dr.line([bx0, by, bx1, by], fill=(255, 255, 255), width=5)
    dr.line([bx0, by - 8, bx0, by + 8], fill=(255, 255, 255), width=3)
    dr.line([bx1, by - 8, bx1, by + 8], fill=(255, 255, 255), width=3)
    dr.text(((bx0 + bx1) / 2, by - 12), f"{bar_um:.0f} µm", font=fntb,
            fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0), anchor="ms")

    n_rej = sum(1 for r in objs if r["cls"] == "breject")
    rej_txt = "未画" if a.no_reject else "青线(无标签)"
    hdr = (f"{a.seg} {a.frame} · 白圈=入表 {n['kept']} · 橙簇 {n['giant']} · "
           f"黄扩 {n['grow']} · 紫重 {n['dup']} · 红残 {n['resid']} · "
           f"青线=B拒 {n_rej} {rej_txt}")
    dr.rectangle([0, 0, W, 30], fill=(0, 0, 0))
    dr.text((10, 5), hdr, font=fnt, fill=(240, 240, 240))

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)      # 目录不存在直接崩过（2026-10-13）
    out = out / f"size_annot_{a.seg}_{Path(a.frame).stem}.jpg"
    im.save(out, quality=90)
    print("saved:", out, im.size,
          f"keep={n['kept']} giant={n['giant']} grow={n['grow']} dup={n['dup']} "
          f"resid={n['resid']} rej={n_rej}({rej_txt})")


if __name__ == "__main__":
    main()
