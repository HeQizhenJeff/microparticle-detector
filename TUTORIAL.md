# 教程：从零跑通 microparticle-detector

> 面向第一次用这个包的人（包括三个月后的我自己）。
> 全部命令都在 Windows 10 + Python 3.13 + `opencv-python-headless` 5.0 上实跑过，
> 数字是实测值，不是估计。
>
> 预计耗时：装环境 5 min，跑通合成数据 3 min，换自己的图 20 min。

---

## 0. 先用 30 秒判断这东西该不该用

**它是给这种图用的：**

- 明场 / 相差下的 **透明胶体微球**，球缘有一圈**暗环**、球心偏亮（离焦也常见）；
- 球直径大致 20–110 px；
- 一帧里几十到几百颗，球与球会挨在一起甚至粘连；
- 你**没有**标注数据、**没有** GPU，但需要一个今天就能出、而且每个拒收都能解释的计数。

**它不是给这种图用的：**

- 实心吸光颗粒（暗色圆盘，最暗处不在球缘）→ 实测只找到 ~5 %，见 README 的
  "cross-modality test"；
- 细胞、细菌、荧光点；
- 上千万帧、要 30 FPS 的产线场景（本包每个 CPU 核约 **0.015–0.03 FPS**）；
- 换过物镜/曝光/球径的新体系，**不改 px 阈值直接用**（见 §6.3）。

判断不确定时，先做 §4.2 的「单帧试跑」：一帧跑完看标注图，肉眼 10 秒就知道对不对。

---

## 1. 安装

### 1.1 建一个干净的虚拟环境（强烈建议）

```bash
# 任意位置，示例放 D:\oss
python -m venv D:/oss/venv-mpd
# Git Bash
source D:/oss/venv-mpd/Scripts/activate
# PowerShell 用这条
# D:\oss\venv-mpd\Scripts\Activate.ps1
```

### 1.2 装依赖 + 本包

```bash
cd microparticle-detector          # 本仓库根目录（含 pyproject.toml）
python -m pip install --upgrade pip
python -m pip install numpy scipy pillow opencv-python-headless
python -m pip install -e . --no-deps
```

三个坑，先讲清楚：

| 坑 | 现象 | 处理 |
|---|---|---|
| `opencv-python` 装不上 / 缺 `libGL.so.1` | 只在 Linux 无桌面环境出现 | 用 **`opencv-python-headless`**，本包不开窗口，headless 够用 |
| `pip install -e .` 报找不到 setuptools | 极简 Python 环境 | 先 `pip install setuptools wheel` |
| 装在系统 Python 里 | 和别的项目抢版本 | 老老实实用 §1.1 的 venv |

### 1.3 自检三条

```bash
python -c "import microparticle_detector as m; print(m.__version__)"   # 期望 1.0.0
python -m microparticle_detector.s6_pipeline --help                    # 期望打出参数表
python -c "import cv2, scipy, numpy; print(cv2.__version__, scipy.__version__, numpy.__version__)"
```

三条都过 = 环境没问题，下面所有报错都可以排除「装错」这个原因。

---

## 2. 第一次跑通（合成数据，不需要任何真实图）

### 2.1 造一张有标准答案的图

```bash
python examples/make_synthetic.py --out ./demo/synth --n 150 --seed 3
```

出来 `demo/synth/synth_00000.jpg`（1024×1024）和 `truth.csv`（每颗球的真圆心+真半径）。
合成器画的是亮心 + 暗环 + 离焦模糊 + 高斯噪声，和本包假设的成像形态一致。

参数：`--n` 球数、`--size` 边长、`--r-min/--r-max` 半径范围（默认 9–14 px）、
`--sigma` 离焦模糊、`--noise` 噪声标准差、`--seed` 随机种子。

### 2.2 跑完整条链

```bash
python -m microparticle_detector.s6_pipeline \
    --frames ./demo/synth --out ./demo/out --annotate
```

实测（单核，1024×1024）：**69 s**，其中 `clump_rescue` 57 s、`ring_channel` 11 s、
`b_gate` 0.9 s。**慢的那一步是候选生成，不是判据**——所以 `--workers` 并行的是帧，
不是阶段。

### 2.3 看结果

```bash
# 命令行里先看个总数
python -c "import json;d=json.load(open('demo/out/summary.json'));print(d['kept'],d['classes'])"
```

打开 `demo/out/annot/`，白圈=入表（圈边写直径 µm）、青线=B 门拒收。对照 §5.3 的颜色表。

### 2.4 打分（这一步别跳）

```bash
python tests/check_synthetic.py \
    --truth ./demo/synth/truth.csv \
    --pred  ./demo/out/objects_classified.csv
```

期望输出：

```
truth=150  detections=133  TP=132  FP=1  FN=18
precision=99.2%  recall=88.0%
OK
```

判 TP 的规则是「预测圆心落在真圆心半个真半径内」。**88 % 的召回不是 bug**：合成器把
球摆得几乎相切，相邻球互相污染暗环，这正是本包第 4 类失效模式的复现。你拿到 88 %
说明环境正常。

---

## 3. 理解它在做什么（够用就好）

```
frames → 暗环通道 ┐
                  ├→ 合并去重 → B 门 → P0–P3 粒径闸 → circles.csv / objects_classified.csv
       → 救援通道 ┘
```

- **暗环通道**：黑帽形态学把细暗线抠出来 → Hough 找圆。专治「只剩一圈边」的球。
- **救援通道**：五路互补种子（密集区扫描 / 亮核距离变换 / CLEAN 迭代 / DAOPHOT 层 /
  可选双球拆分），专门补前一步漏掉的、埋在团簇里的球。
- **B 门**（核心）：对每个候选，从圆心放射状取 16 个方向，每个方向沿半径找「暗谷」，
  再把这些谷点拟合一个圆。谷点共圆 = 真球；谷点乱七八糟 = 假的。判 PASS 要同时满足
  `rn2 ≤ 0.10`（拟合残差）、`n ≥ 9`（16 个方向里至少 9 个有谷）、圆不出画。另有一条
  宽松支线：`n ≥ 7` 且最长连续弧 ≥ 112.5° 也放行（为了救被邻球挡掉几个方向的真球）。
  **绝大多数误检死在这一步，而且每个拒收都留了数值理由。**
- **P0–P3**：只回答「这个已过 B 门的圈，能不能进粒径表」。

细节见 README 的 "How it works"，代码开头的中文 docstring 更细。

---

## 4. 换成你自己的图

### 4.1 目录和格式

```bash
frames/
  frame_00001.jpg
  frame_00002.png
  ...
```

- 一个文件一帧，扩展名认 `.jpg/.jpeg/.png/.tif/.tiff/.bmp`；
- **文件名随便起**，不要求 `frame_*.jpg`（旧版本有这个假设，已去掉）；
- 不要有子目录；不要放缩略图或别的杂物，放进去的都会被当帧处理。

### 4.2 先跑一帧（每次换体系都先做这一步）

```bash
python -m microparticle_detector.s6_pipeline \
    --frames ./frames --out ./out_test --limit 1 --annotate
```

打开 `out_test/annot/` 那一张，只看三件事：

1. 大部分球上**有没有白圈**？
2. 白圈是不是**贴着球缘**（不是缩在球心、也不是套住两颗球）？
3. 空白处、球缝里有没有**成片的假圈**？

三种典型结果，对应三种下一步：

| 看到什么 | 说明 | 下一步 |
|---|---|---|
| 白圈基本对，个别漏 | 正常 | 去 §4.3 标定，然后全量跑 |
| 几乎没圈，青线也少 | 候选生成就没找到 → 尺度不对（球太大/太小） | §6.2 |
| 满屏青线、白圈只占少数 | B 门在拒真球 → 成像形态不符或阈值太严 | §6.3 |

### 4.3 标定 µm/px（决定所有 µm 数字对不对）

```bash
# 先用默认 0.0762 µm/px（100× 物镜 + 1.0× C 接口，本包的标定）
# 换物镜就按比例缩放：50× → 0.0762 × 100/50 = 0.1524
python -m microparticle_detector.s6_pipeline \
    --frames ./frames --out ./out --annotate \
    --um-per-px 0.1524 --bar-um 10
```

**如果手上有标准球或刻线尺，别信默认值，自己算一次：**

```
um_per_px = 已知球直径(µm) / 量到的像素直径(px)
```

量法：找 5–10 颗边缘清晰的球，取像素直径的平均值。算法输出的 `d_B`（px）乘上
`um_per_px` 就是直径，你可以在标注图上直接读白圈旁的 µm 数字来反查标定有没有错。

⚠️ `um_per_px` **只影响标注数字和比例尺，不影响检测本身**。检测里的 px 阈值是写死的，
见 §6.3。

### 4.4 全量跑

```bash
# 单核：约 30–70 s/帧，取决于图大小和球密度
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out

# 4 物理核实测加速 1.94×（内存带宽是瓶颈，加到 8 核收益很小）
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out --workers 4
```

手上有别的检测器给出的圆（比如阈值+分水岭的结果），可以当基线喂进去，先手先得、
后面的通道只补它没找到的：

```bash
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out \
    --baseline baseline.csv      # 列名：frame,cx,cy,r（也认 x,y,radius）
```

---

## 5. 输出文件怎么读

### 5.1 文件清单

| 文件 | 内容 | 你该看吗 |
|---|---|---|
| `circles.csv` | 去重后的最终圆：`frame,cx,cy,r,src` | 只要个数时看这个 |
| `objects_classified.csv` | 每个圆 + B 门测量 + `cls` 分类 | **做粒径统计时看这个** |
| `objects.csv` | 同上但没有 `cls` | 一般不看 |
| `ring.csv` / `extras.csv` | 两个通道各自的原始候选 | 调参debug 时看 |
| `_baseline_for_rescue.csv` | 传给救援通道的基线（若给了 `--baseline`） | 一般不看 |
| `summary.json` | 计数、类别分布、参数、各阶段耗时 | 每次都要看一眼 |
| `annot/` | 标注图 | 抽检必看 |

### 5.2 `objects_classified.csv` 逐列

| 列 | 含义 |
|---|---|
| `seg` | 段标签（默认取 frames 目录名，可用 `--seg` 改） |
| `frame` | 帧文件名 |
| `x, y` | **机器种子**圆心（px） |
| `d_M` | 种子直径（px），即「检测器一开始以为多大」 |
| `d_B` | **B 门拟合后的直径（px）—— 报粒径用这个** |
| `ok` | B 门是否 PASS |
| `rn2` | 归一化拟合残差 `rms/R`，越小越圆。好球一般 ≤ 0.022 |
| `cx2, cy2` | **B 门拟合圆心（px）—— 画图/后续配准用这个** |
| `n` | 16 个方向里有几个方向找到合格暗谷 |
| `cls` | `kept / giant / grow / dup / resid / breject`，见下 |
| `src` | 这个圆来自哪个通道：`baseline / ring / rescue` |

`cls` 六个值是互斥的，按顺序判定：

| `cls` | 含义 | 进粒径表吗 |
|---|---|---|
| `kept` | 通过全部闸门 | **是** |
| `giant` | P0：比一颗球还大（>110 px）的团簇/油滴 | 否 |
| `grow` | P1：圈从种子一路长到邻球上 | 否 |
| `dup` | P2：同一颗球的重复测量 | 否 |
| `resid` | P3：拟合残差过大（圈没贴合） | 否 |
| `breject` | B 门直接拒（找不到暗环/覆盖不足/出画） | 否 |

### 5.3 标注图颜色

| 图上 | 含义 |
|---|---|
| 白色实线圈 + 数字 | `kept`，数字是直径 µm |
| 橙色圈 / 黄圈 / 紫虚线 / 红圈 | P0 团簇 / P1 增长 / P2 重复 / P3 残差 |
| 青色细线（无标签） | `breject`，仅示位；嫌糊可加 `--no-reject` 关掉 |

顶部那行黑底小字是中文图例，因为代码的工作语言是中文；对照上表即读得懂。

### 5.4 生成一张粒径表

```python
import csv, collections

UM_PER_PX = 0.0762                      # ← 换成你自己的标定
rows = list(csv.DictReader(open("out/objects_classified.csv", encoding="utf-8")))

per_frame = collections.Counter()
diam = []
for r in rows:
    if r["cls"] != "kept":
        continue
    per_frame[r["frame"]] += 1
    diam.append(float(r["d_B"]) * UM_PER_PX)

diam.sort()
n = len(diam)
print("帧数", len(per_frame), "总颗粒数", n)
print("中位直径 %.2f µm" % diam[n // 2])
print("10/90 分位 %.2f / %.2f µm" % (diam[int(0.1 * n)], diam[int(0.9 * n)]))
for f, c in sorted(per_frame.items()):
    print(f, c)
```

**别只看均值**：多分散样品用中位数 + 10/90 分位；分布跨度 > 1.5 倍通常说明这批形态
不均，先回去看标注图，而不是急着调参。

---

## 6. 参数手册与调参顺序

### 6.1 全部命令行参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--frames` | 必填 | 帧目录 |
| `--out` | 必填 | 输出目录（不存在会自动建） |
| `--baseline` | 无 | 外部基线圆 CSV（`frame,cx,cy,r`） |
| `--seg` | 目录名 | 段标签，写进 CSV 的 `seg` 列 |
| `--workers` | 1 | 并行进程数；4 核实测 1.94× |
| `--limit` | 全部 | 只跑前 N 帧（试跑用） |
| `--gate` | 关 | 额外做帧级质量闸（判断这一帧值不值得数） |
| `--annotate` | 关 | 输出标注图到 `out/annot/` |
| `--no-reject` | 关 | 配合 `--annotate`：不画 B 门拒收的青线（青线可能几百条，糊屏时用） |
| `--um-per-px` | 0.0762 | 标定，只影响标注数字与比例尺 |
| `--bar-um` | 10 | 比例尺长度 µm |
| `--skip-ring` | 关 | 跳过暗环通道（调试用） |
| `--skip-rescue` | 关 | 跳过救援通道（**快 5 倍**，漏球变多） |
| `--prom-min` | 12 | B 门「谷深」下限（灰度）。调它前先读 §6.3 |

### 6.2 球太大 / 太小（改了 `--um-per-px` 还是找不到）

候选生成本身是有尺度的：暗环通道的黑帽结构元 9 px（对应环宽）、救援通道的亮核距离
变换下限 6 px、Hough 半径范围按本包标定写死。所以：

- **球直径 < 15 px**：暗环太薄，候选生成多半直接失败（按黑帽核 9 px、微扫半径下限
  10 px 推断，**未系统实测**）。建议先上采样 2× 再跑，`um_per_px` 相应减半。
- **球直径 > 110 px**：会被 P0 当团簇丢掉（`GIANT_DM = 110`）。要么降采样，要么改
  `src/microparticle_detector/s6_size_gates.py` 的 `GIANT_DM`。
- 介于两者之间但偏大：勉强能用，但 P1/P3 只在 `d_M ≥ 40 px` 时生效，等于对小球关掉
  了两道闸——这是为小球没有金标准而做的保守选择。

### 6.3 🔴 最重要的一条：px 阈值是绑定标定的

代码里的阈值（`PROM_MIN=12` 灰度、`GIANT_DM=110 px`、`GROW_MIN_SEED=40 px`、
`SWEEP_RADII=(10,13,16)`、黑帽核 9 px …）全部是在 **0.0762 µm/px、3.5–8 µm 球、
本实验室相机与曝光** 上标出来的。

**换物镜/换相机/换球径 = 这些数字全部失效**，不是「微调」，是要重新标。
重新标的底线流程：手工标 20–40 颗球做金标准 → 重放看 P/R → 一次只动一个参数。

### 6.4 调参的优先顺序（动一个，验一次）

1. `--um-per-px` —— 先把「µm 对不对」和「能不能检测」分开；
2. `--workers` —— 只是速度，不影响结果；
3. `--skip-rescue` —— 只是速度/召回的取舍，用来判断「是不是救援通道在拖时间」；
4. `--prom-min` —— 唯一暴露出来的判据参数。降它 = 放更多候选过 B 门 = 召回↑误检↑。
   本包实测：在别的体系上从 12 降到 6 只换来 1.6 个百分点召回——**它不是万能旋钮**；
5. 改源码里的阈值 —— 最后手段，改完必须在自己的金标准上重放。

---

## 7. 拿到数字之后，四步自检

1. **帧级看异常**：把每帧颗粒数排个序。某帧明显低于邻居（本包遇到过一帧 153 颗，
   邻居 ~290 颗）→ 大概率对焦坏了，**重拍这一帧，而不是调参**。
2. **抽 3 帧看标注图**：白圈有没有套错、球缝里有没有假圈。
3. **看 `summary.json` 的类别分布**：`breject` 数量远大于 `kept`（比如 5 倍以上）
   → B 门在拒真球，成像形态可能不匹配，别急着信总数。
4. **和第二个方法对一次**：粗的分水岭基线、或人工数一帧，差值超过 10 % 就不要拿去写
   论文。

---

## 8. 常见问题

**Q：一张图都没检出圈。**
先看 `summary.json` 里 `ring` / `rescue` 候选数。是 0 → 尺度不对（§6.2）或图是纯色；
有几百候选但 `kept`≈0 → B 门在拒（`breject` 全占）→ 成像形态不符（实心暗球？）或
`--prom-min` 太高。

**Q：圈太多，满屏假圈。**
先看假圈长什么样：落在球缝三角区/两颗大球之间的鞍部 → 这是文档里写明的失效模式 1、2，
**没有阈值能分开**（读过 README 的 Failure modes 就知道这两条是已知无解的）。落在
空白处 → `--prom-min` 调高，或看 §6.3。

**Q：`ModuleNotFoundError: No module named 'microparticle_detector'`。**
没装包。`pip install -e .`，或者临时 `PYTHONPATH=src python -m ...`（Windows
PowerShell 用 `$env:PYTHONPATH="src"`）。

**Q：太慢。**
`--skip-rescue` 快约 5 倍（召回掉一些）；`--workers 4` 约 2×；再快就只能降分辨率或
换赛道（训练一个网络）。**别指望这个包做产线。**

**Q：内存爆。**
`--workers` 是**进程级**并行，总内存约等于 `workers × 单帧峰值`（每个进程各持一份
opencv 运行时）。8 GB 机器保守别超过 3；报 MemoryError 就先降到 1，确认单进程能跑
再往上加。

**Q：中文路径 / 路径带空格。**
路径加引号即可，代码内部全部走 `pathlib`。Windows 下在 Git Bash 里写 `D:/a/b` 而不是
`/d/a/b`（Python 不认 MSYS 的 `/d/` 前缀）。

**Q：能不能只跑某几帧？**
把要跑的帧复制到新目录，或者 `--limit N`（只跑前 N 帧，按文件名排序）。

---

## 9. 已知局限（引用前必读）

- **速度**：单核 0.015–0.03 FPS，属于「离线跑一夜」的量级。
- **只适用于一种成像形态**：相差/明场的透明球暗环。别的形态实测只剩 ~5 % 召回。
- **阈值绑标定**：换设备/换球径必须重标（§6.3）。
- **两类结构性失效**：球缝鞍部假圆、四球围出的空腔假圆——已文档化，当前无解。
- **完全粘连的哑铃形**：环已经物理消失，任何基于环的方法都救不回来。
- **三维堆叠**：离焦面外的球会漏，数量偏低。
- **性能数字是 in-sample**：README 里的 98.66 % / 98.21 % 是在同一批 22 帧上调参后
  测的，不是留出集；单标注者、单一仪器。当上限看，别当保证。

---

## 10. 引用

```bibtex
@software{he2026microparticle,
  author  = {He, Qizhen},
  title   = {microparticle-detector: dark-ring circle detection for brightfield
             microscopy of colloidal microspheres},
  year    = {2026},
  version = {1.0.0},
  license = {MIT},
  note    = {DOI to be added on first release}
}
```

第一次正式发布后，Zenodo 会给一个 DOI，届时替换上面的 `note`，并在 README 顶部加
DOI 徽章（步骤见 `docs/PUBLISHING.md`）。

---

## 附：一次完整的最小工作流（复制粘贴用）

```bash
# 0) 环境
python -m venv D:/oss/venv-mpd && source D:/oss/venv-mpd/Scripts/activate
python -m pip install numpy scipy pillow opencv-python-headless
python -m pip install -e . --no-deps

# 1) 自检
python -m microparticle_detector.s6_pipeline --help

# 2) 单帧试跑 + 目检标注图
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out_test \
    --limit 1 --annotate --um-per-px 0.0762 --bar-um 10

# 3) 全量 + 并行
python -m microparticle_detector.s6_pipeline --frames ./frames --out ./out \
    --annotate --workers 4 --um-per-px 0.0762 --bar-um 10

# 4) 取结果
python -c "import json;d=json.load(open('out/summary.json'));print(d['kept'],d['classes'])"
```
