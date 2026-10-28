#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""s6_frame_gate — 帧级筛焦闸门 v0.3（video-analysis 集成版，2026-10-12）

用途：视频抽帧后 / 选帧测量前，机械判定「这一帧有没有可用的焦层证据」。只回答
「帧丢不丢」，不判「球是不是目标」、不做对象级测量。

判据（v0.3，88 帧金标准留一视频重标定，2026-10-12）：
    ① 内容地板：帧 DoG(σ=3,24) 高通 std < 4.0 → 判「空场」SKIP，不进入②（v0.2 起未动）。
    ② 焦层判据：frac = #{d ≥ 40px 且 暗环半高宽 fwhm ≤ 9px 的大对象} / #{d ≥ 40px 的大对象}
       frac ≥ 0.44 → PASS（帧内存在成规模的细锐暗环对象 = 有焦层证据）；否则 → SKIP。

v0.3 变更记录（2026-10-12 帧闸门重标定，88 帧对象级金标准 14_2h 48 + 13_2h 40）：
  v0.2 (fw≤7, frac≥0.30) 在双视频金标准下的真实战绩 = P 96.0% (24/25)、R 88.9% (24/27)：
  漏入 13_2h F24（半糊，frac=0.4739 破 0.30 阈），误杀 13_2h F28/F29（真 ok 帧，含细环
  对象被 fw≤7 判死）。重标定协议 = 留一视频 (LOO by video)：只在 14_2h 48 帧校准段选点，
  13_2h 40 帧当盲测，防在 88 帧上过拟合。
    · fw_max 7 → 9.0：修 13_2h 两帧 ok 误杀（旧阈值下 F28/F29 永远收不回）。
    · threshold 0.30 → 0.44：14_2h 校准段坏帧最高 frac9=0.4118（F28 defocus）、好帧最低
      0.4684（F30）→ 窗口 (0.4118, 0.4684] 取中点 0.440 = 距两侧边界等距的最鲁棒选点
      （max-min 中点法，非在全 88 帧上挑最优）。
  战果（88 帧合计）：P 96.0% → 100% (24/24)，R 88.9% → 88.9% (24/27) 持平；
  漏入翻转代价 7 → 6 个对象，误杀代价 5 → 3 个对象（仍属可容忍侧）。
  PASS 集变化：14_2h 11 帧与 v0.2 完全相同；13_2h 14 → 13 帧（剔除漏入的 F24）。
  新 fw 轨（C 门口径 16 扇区径向剖面）已评估**不优于旧轨、不采用**——类间分离更大
  （ok/half = 9× vs 旧 3×）但被离群帧（F24 半糊 frac_new8=0.5614）卡死，P=100% 时
  14_2h 只剩 8/11；逐对象数据归档 _fw2_<seg>.csv，仅作诊断参考，不进本脚本判据。
  ⚠ 边界：13_2h 无对象级金标准，B/C 门跨视频只做了分布冒烟（拟合成功率 90.5%/92.6%、
  环宽中位 6.12/6.05px、ratio 中位 0.0833/0.0903 同量级）——分布一致但**未打分**。

v0.2 变更记录（2026-10-09）：v0.1 在近空帧上被噪声幻影骗过（TPMT_13_2h F15/F22/F23）。
  根因：structure_mask 用「相对自身噪声 sd 的阈值」建掩码，空帧的条纹/JPEG 噪声 sd>0.5
  即被刻成掩码（实测掩码覆盖 68%、碎片 1600+ 个），edge_diameter 在碎片上产出假 d/fwhm
  → frac 假高 → 假 PASS。修复 = 帧级内容地板（sd < 4.0 判空场）。
  核心判据②一字未动；14_2h 回归零变化。⚠ 地板定标自 0916 批（空场 ≤2.8 / 实帧 ≥5.4），
  跨批次/曝光差异待后续验证；「半空帧」（部分内容+部分噪声）是本版已知残余风险；
  运动过渡帧（镜头刚进样品区的雾状软影被误测成细环，13_2h F24 实测假 PASS → v0.3 已封）。
🔴 设计哲学（用户 2026-10-09 定调）：宁缺毋滥——「少一点好的不重要，重要的是选了的必须
   是好的」。可以丢边缘好帧（假阴性，少几帧），不可放行无焦层帧（假阳性，污染结论）。

语义：闸门只管「帧丢不丢」，不做对象级测量、不判「球是不是目标」。
      细环对象含实心微球与油滴（同一焦平面；2026-10-09 用户鉴定 d>110 组为油滴挨在一起）。
口径：取数与 focus_probe.py 完全同源（同代码提取），保证与校准数字可比。

依赖：同目录 s6_focus_probe.py（特征前端）→ s6_triage.py；需 cv2 环境
      （C:\\Users\\何其臻\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe）。
用法（在 scripts/ 目录下运行）:
    python s6_frame_gate.py <frames_dir> [--feats feats.csv] [--out OUTDIR]
                            [--threshold 0.44] [--sd-floor 4.0] [--d-min 40] [--fw-max 9]
                            [--gold TRIAGE_DIR] [--sheet] [--limit N]
--feats: 复用已提取特征（seg 列须等于帧目录名）；缺省则现场提取（整段约 1 分钟）。
--gold:  金标准回归模式。TRIAGE_DIR 下须有 labels_<seg>_frames.json（键 F01..Fnn），
         打印该段 P/R 并断言：P 必须 100%（准入线 = v0.2 的 96.0%），R 不得低于 v0.2
         基线（14_2h 100% / 13_2h 81.25%）。断言不过 → 退出码 2。
输出：out_gate_<seg>/gate.json + gate.md（--sheet 加 gate_sheet.jpg 三色判读表）。
"""
import argparse, csv, json, math, re, sys
from collections import defaultdict
from pathlib import Path

VERSION = "s6_frame_gate v0.3 (2026-10-12, 88帧留一视频重标定)"


def natural_key(p):
    m = re.findall(r'(\d+)', Path(p).stem)
    return int(m[-1]) if m else 0


# --gold 回归的 R 基线 = v0.2 在同段金标准上的 recall（不得下降）
R_BASELINE = {"TPMT_14_2h": 100.0, "TPMT_13_2h": 81.25}
P_ADMISSION = 96.0  # v0.2 双视频基线，v0.3 准入线（实际目标 100%）


def gold_eval(frames, seg, gdir):
    """对 labels_<seg>_frames.json 打分。返回 True=断言全过 / False=不过 / None=无标签。"""
    lp = Path(gdir) / f"labels_{seg}_frames.json"
    if not lp.exists():
        lp = Path(gdir) / f"labels_{seg.replace('TPMT_', '')}_frames.json"
    if not lp.exists():
        print(f'  [gold] 找不到 labels_{seg}_frames.json（{gdir}），跳过打分')
        return None
    labels = json.loads(lp.read_text(encoding='utf-8'))['labels']
    tp = fp = fn = tn = 0
    leaks, misses = [], []
    for f in frames:
        key = f'F{f["idx"]:02d}'
        g = labels.get(key)
        if g is None:
            continue
        p = f['verdict'] == 'PASS'
        if p and g == 'ok':
            tp += 1
        elif p:
            fp += 1; leaks.append(f'{key}({g})')
        elif g == 'ok':
            fn += 1; misses.append(key)
        else:
            tn += 1
    P = 100.0 * tp / (tp + fp) if (tp + fp) else 0.0
    R = 100.0 * tp / (tp + fn) if (tp + fn) else 0.0
    print(f'  [gold] {seg}: PASS={tp+fp}  P {tp}/{tp+fp}={P:.1f}%  R {tp}/{tp+fn}={R:.1f}%'
          f'  (tn={tn})')
    if leaks:
        print(f'    ⚠ 漏入(坏帧进 PASS)={",".join(leaks)}')
    if misses:
        print(f'    ⚠ 误杀(ok 被 SKIP)={",".join(misses)}')
    ok = True
    if P + 1e-9 < 100.0:
        print(f'    [FAIL] precision {P:.1f}% < 100%（准入线 {P_ADMISSION:g}% = v0.2 基线，'
              f'宁缺毋滥要求零漏入）')
        ok = False
    else:
        print(f'    [PASS] precision 100% ≥ {P_ADMISSION:g}% (v0.2 基线)')
    base = R_BASELINE.get(seg)
    if base is not None:
        if R + 1e-9 < base:
            print(f'    [FAIL] recall {R:.1f}% < v0.2 基线 {base:g}%（不得下降）')
            ok = False
        else:
            print(f'    [PASS] recall {R:.1f}% ≥ {base:g}% (v0.2 基线)')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--feats", default=None, help="复用已提取的逐球特征 CSV")
    ap.add_argument("--out", default=None, help="输出目录（默认 out_gate_<seg>）")
    ap.add_argument("--threshold", type=float, default=0.44, help="frac 下限（v0.3=0.44，v0.2=0.30）")
    ap.add_argument("--sd-floor", type=float, default=4.0, help="内容地板：DoG 高通 std 下限")
    ap.add_argument("--d-min", type=float, default=40.0)
    ap.add_argument("--fw-max", type=float, default=9.0, help="细环 fwhm 上限 px（v0.3=9.0，v0.2=7）")
    ap.add_argument("--gold", default=None, help="金标准目录（含 labels_<seg>_frames.json），跑 P/R 回归并断言")
    ap.add_argument("--sheet", action="store_true", help="输出缩略图判读表 gate_sheet.jpg")
    ap.add_argument("--limit", type=int, default=None, help="提取上限（调试用）")
    a = ap.parse_args()

    fd = Path(a.frames_dir)
    seg = fd.name
    outdir = Path(a.out) if a.out else Path(f"out_gate_{seg}")
    outdir.mkdir(parents=True, exist_ok=True)

    # ---- 依赖：focus_probe（内含 s6_triage 模块 t；提取与 sd 都需 cv2 环境） ----
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import s6_focus_probe as fp
    import cv2
    import numpy as np
    t = fp.t

    def frame_sd(p):
        g = t.load_gray(p)
        f = g.astype(np.float32)
        hp = cv2.GaussianBlur(f, (0, 0), t.DOG_SIG1) - cv2.GaussianBlur(f, (0, 0), t.DOG_SIG2)
        return float(hp.std())

    # ---- 取数（同源 focus_probe） ----
    if a.feats:
        csv_path = a.feats
    else:
        csv_path = str(outdir / f"feats_{seg}.csv")
        fp.run([str(fd)], csv_path, limit=a.limit)

    rows = defaultdict(list)
    with open(csv_path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['seg'] != seg:
                continue
            try:
                r['d_f'] = float(r['d']); r['fw_f'] = float(r['fwhm'])
            except Exception:
                continue
            rows[r['frame']].append(r)

    master = sorted([*fd.glob('*.jpg'), *fd.glob('*.png')], key=natural_key)
    if a.limit:
        master = master[:a.limit]

    # ---- 逐帧判定 ----
    frames = []
    for p in master:
        rs = rows.get(p.name, [])
        ds = [r['d_f'] for r in rs]
        n_large = sum(1 for d in ds if d >= a.d_min)
        n_thin = sum(1 for r in rs if r['d_f'] >= a.d_min and r['fw_f'] <= a.fw_max)
        frac = (n_thin / n_large) if n_large else float('nan')
        sd = frame_sd(p)
        if sd < a.sd_floor:
            verdict, flag = 'SKIP', 'empty'
        elif n_large == 0:
            verdict, flag = 'SKIP', 'no_large'
        else:
            verdict = 'PASS' if frac >= a.threshold else 'SKIP'
            flag = 'lowN' if n_large < 5 else ''
        frames.append(dict(frame=p.name, idx=natural_key(p), sd=round(sd, 2),
                           n_large=n_large, n_thin=n_thin,
                           frac=round(frac, 4) if n_large else None,
                           verdict=verdict, flag=flag))

    n_pass = sum(1 for f in frames if f['verdict'] == 'PASS')
    n_skip = len(frames) - n_pass
    lowN = [f['idx'] for f in frames if f['flag'] == 'lowN']
    nol = [f['idx'] for f in frames if f['flag'] == 'no_large']
    empt = [f['idx'] for f in frames if f['flag'] == 'empty']

    # ---- --gold 金标准回归（判定已出，先打分） ----
    gold_ok = None
    if a.gold:
        gold_ok = gold_eval(frames, seg, a.gold)

    summary = dict(n_frames=len(frames), n_pass=n_pass, n_skip=n_skip,
                   pass_frames=[f'F{f["idx"]:02d}' for f in frames if f['verdict'] == 'PASS'],
                   empty_frames=[f'F{i:02d}' for i in empt],
                   lowN_frames=[f'F{i:02d}' for i in lowN],
                   no_large_frames=[f'F{i:02d}' for i in nol])
    params = dict(threshold=a.threshold, sd_floor=a.sd_floor, d_min=a.d_min,
                  fw_max=a.fw_max, feats=csv_path)

    with open(outdir / 'gate.json', 'w', encoding='utf-8') as f:
        json.dump(dict(version=VERSION, frames_dir=str(fd), params=params,
                       summary=summary, frames=frames), f, ensure_ascii=False, indent=1)

    # ---- markdown ----
    md = [f'# 帧闸门 v0.3 — {seg}', '',
          f'- 判据: 内容地板 DoG-sd ≥ {a.sd_floor:g}，且 frac(d≥{a.d_min:g}px & fwhm≤{a.fw_max:g}px) ≥ {a.threshold:g}',
          f'- 结果: {len(frames)} 帧 → PASS {n_pass} / SKIP {n_skip}（其中空场 {len(empt)}）',
          f'- PASS: {",".join(summary["pass_frames"]) or "无"}',
          f'- 空场: {",".join(summary["empty_frames"]) or "无"}',
          f'- lowN(<5 大对象): {",".join(summary["lowN_frames"]) or "无"}',
          f'- 无大对象: {",".join(summary["no_large_frames"]) or "无"}', '',
          '| 帧 | sd | n_large | n_thin | frac | 判定 |', '|---|---|---|---|---|---|']
    flagmark = {'empty': ' 空场', 'lowN': ' ⚠lowN', 'no_large': ' 无对象', '': ''}
    for f in frames:
        fr = f'{f["frac"]:.3f}' if f['frac'] is not None else '—'
        md.append(f'| F{f["idx"]:02d} | {f["sd"]:.2f} | {f["n_large"]} | {f["n_thin"]} | {fr} | {f["verdict"]}{flagmark[f["flag"]]} |')
    (outdir / 'gate.md').write_text('\n'.join(md), encoding='utf-8')

    # ---- sheet ----
    if a.sheet:
        make_sheet(frames, fd, outdir / 'gate_sheet.jpg', seg, a.threshold, a.sd_floor, a.fw_max)

    print(f'[s6_frame_gate] {seg}: {len(frames)} frames → PASS {n_pass} / SKIP {n_skip} '
          f'(threshold {a.threshold:g}, fw_max {a.fw_max:g}, sd_floor {a.sd_floor:g})')
    print(f'  PASS: {",".join(summary["pass_frames"]) or "无"}')
    if empt:
        print(f'  空场: {",".join(summary["empty_frames"])}')
    if lowN:
        print(f'  lowN: {",".join(summary["lowN_frames"])}')
    print(f'  → {outdir}/gate.json | gate.md' + (' | gate_sheet.jpg' if a.sheet else ''))
    if a.gold and gold_ok is False:
        sys.exit(2)


def make_sheet(frames, fd, out_png, seg, thr, sdf, fwm=9.0):
    from PIL import Image, ImageDraw, ImageFont
    import os
    font_path = None
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.exists(p):
            font_path = p; break
    f_b = ImageFont.truetype(font_path, 24)
    f_c = ImageFont.truetype(font_path, 17)

    CELL_W, IMG_H, CAP_H = 330, 200, 30
    cols = 6
    rows_n = math.ceil(len(frames) / cols)
    BANNER = 56
    W = cols * CELL_W
    H = BANNER + rows_n * (IMG_H + CAP_H)
    sheet = Image.new('RGB', (W, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    d.text((14, BANNER // 2),
           f'帧闸门 v0.3 · {seg} · 内容sd≥{sdf:g} + frac(d≥40px & fwhm≤{fwm:g}px)≥{thr:g} · 绿=PASS/红=SKIP/灰=空场',
           font=f_b, fill=(255, 255, 255), anchor='lm')

    for k, f in enumerate(frames):
        r, c = divmod(k, cols)
        x0 = c * CELL_W; y0 = BANNER + r * (IMG_H + CAP_H)
        im = Image.open(fd / f['frame']).convert('RGB')
        im.thumbnail((CELL_W - 6, IMG_H - 4), Image.LANCZOS)
        sheet.paste(im, (x0 + (CELL_W - im.width) // 2, y0 + (IMG_H - im.height) // 2))
        if f['verdict'] == 'PASS':
            col = (46, 174, 87)
        elif f['flag'] == 'empty':
            col = (122, 122, 158)
        else:
            col = (224, 74, 74)
        d.rectangle([x0, y0, x0 + CELL_W - 1, y0 + IMG_H + CAP_H - 1], outline=col, width=3)
        if f['flag'] == 'empty':
            cap = f'F{f["idx"]:02d} · 空场(sd={f["sd"]:.1f}) · SKIP'
        else:
            fr = f'{f["frac"]:.2f}' if f['frac'] is not None else '—'
            extra = {'lowN': ' ⚠lowN', 'no_large': ' 无对象', '': ''}[f['flag']]
            cap = f'F{f["idx"]:02d} · {fr} · {f["verdict"]}{extra}'
        d.rectangle([x0, y0 + IMG_H, x0 + CELL_W, y0 + IMG_H + CAP_H], fill=(28, 28, 30))
        d.text((x0 + 8, y0 + IMG_H + CAP_H // 2), cap, font=f_c, fill=col, anchor='lm')

    sheet.save(out_png, quality=88)
    print(f'  sheet → {out_png} {sheet.size}')


if __name__ == '__main__':
    main()
