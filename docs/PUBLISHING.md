# 发布清单（内部文档）

> 这份文档的读者只有一个人：作者本人。所以用中文写。
> README / TUTORIAL 面向外部用户，那两份用英文和中文各一份是有意的分工。

除了**三步必须用 GitHub 账号操作**的步骤，其余全部已完成。按顺序往下做即可；
全程不碰任何实验室数据。

---

## 当前状态

| 项目 | 状态 |
|---|---|
| 仓库内容（代码 + README + TUTORIAL + 4 张图 + CI + 测试） | **完成** |
| 本地 commit（分支 `master`，8 个提交） | **完成** |
| 硬编码绝对路径清理 | **完成** — 4 处 |
| 帧文件名假设（`frame_*.jpg`）清理 | **完成** — 2 处 |
| ASR 链 / API key / 备份 / 冲突文件排除 | **完成** — 见 `docs/EXCLUDED.md` |
| 临时目录（`_ps1*`、`_reg_*`、`_smoke*`、`_synth*`）移出跟踪并忽略 | **完成** — 2026-10-28 |
| 仓库内的真实显微镜帧 | **零** — 只有合成生成器 |
| `docs/images/` 里的图 | **零实验室数据** — 全部由 `make_synthetic.py` 生成，另加手绘流程图 |
| README 破图修复 | **完成** — 原 `YOURNAME` CI 徽章 404，已移除；待 push 后按步骤 1 加回 |
| `pip install -e .` 验证 | **完成** — 2026-10-28，Python 3.13 |
| 合成数据端到端 + P/R 断言 | **完成** — P 99.2% / R 88.0%，69 s/帧 |
| 打包冒烟（zip 解压到全新目录实跑） | **完成** — 2026-10-28 |
| CI workflow | **完成** — `.github/workflows/ci.yml`，py 3.9 / 3.11 / 3.12 |
| README、TUTORIAL、MIT LICENSE、CITATION.cff、requirements、pyproject | **完成** |
| GitHub remote + push | **你** |
| Zenodo DOI | **你**（点两下，见步骤 4） |

当前 tracked 文件 **25 个 / 443 KB**；发布包 `../microparticle-detector-v1.0.0.zip`（248 KB，
`git archive` 生成，不含 `.git`）。

---

## 步骤 1 — 补两条需要真仓库才能显示的徽章（1 分钟）

README 现在只带三条**不需要仓库也能解析**的徽章（License / Python / OpenCV）。CI 徽章
被删掉了，因为 `github.com/YOURNAME/...` 是 404——README 顶上一个破图比没有徽章更糟。

**推完（步骤 3）且 CI 绿了之后**，把下面两行加到现有徽章下方：

```markdown
[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
<!-- 步骤 4 拿到 DOI 之后再加这一行 -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
```

`OWNER/REPO` 换成真实的 `用户名/仓库名`。除了这两处，仓库里**没有别的占位符**。

推送前建议顺手把作者邮箱填成真的（只改最后一次提交）：

```bash
git config user.name  "He Qizhen"
git config user.email "你的真实邮箱"
git commit --amend --reset-author --no-edit
```

## 步骤 2 — 建空仓库

GitHub 上 **New repository** →

- 名字 `microparticle-detector`
- **Public**
- **不要**勾选 README / .gitignore / license —— 三样仓库里都已经有了
- 创建

## 步骤 3 — 推送

```bash
cd Products/oss/microparticle-detector
git remote add origin https://github.com/OWNER/microparticle-detector.git
git branch -M main
git push -u origin main
```

然后打开 **Actions** 标签页，三个 job 应该 5 分钟内变绿。
如果没绿，**九成是 OpenCV 装不上**（workflow 里已经用 `opencv-python-headless` 规避
runner 没有 `libGL` 的问题，所以真挂了就得看具体日志）。

## 步骤 4 — Zenodo DOI（这一步才让它变成可引用的对象）

1. 用 GitHub 账号登录 <https://zenodo.org>。
2. **Settings → GitHub** → 把 `microparticle-detector` 打开（**ON**）。
3. 回 GitHub 仓库：**Releases → Draft a new release** →
   - tag 填 `v1.0.0`，标题填 `v1.0.0`，发布。
4. Zenodo 一分钟内给出 DOI，复制。
5. 填到两个地方，再推一次：

```markdown
<!-- README.md，徽章区下方 -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
```

```yaml
# CITATION.cff，追加一行
doi: 10.5281/zenodo.XXXXXXX
```

这个 DOI 就是 TPM 论文 Methods 里可以引的对象——**不用等任何期刊**。

---

## 哪些东西是故意不放进去的

- **22 帧标注数据**（含 bad / miss 标签）。属于实验室资产，需要导师（PI）批准；即便批了，
  也建议单独开一个数据仓库 `tpm-microsphere-benchmark`（CC BY 4.0），这样代码和数据
  可以分开引用。批准到手后，datasheet 模板和帧/标注的目录结构我可以直接生成。
- **A 线**（`s6_triage` + `s6_size_measure`）。依赖外部的标准球标定文件；没有那个文件时
  它会静默跳过标定，对外部用户是误导。除非标定文件也能一起发，否则不复活。
- **ASR / AI 视频分析链**。与检测无关，而且带 `MIMO_API_KEY` 处理逻辑。

逐文件的排除理由：`docs/EXCLUDED.md`。

---

## 发布之后，值得补的两个对照

1. **我们的工具跑 PSCount 的 20 张公开测试帧**（纯 CPU）。这是目前数字最缺的
   跨体系、留出集检验——结论已知是 4.9% recall，补的是正式记录。
2. **Cellpose-SAM 零样本跑我们的 22 帧**（需要 GPU 机器）。对标 PSCount 自报的
   零样本 MAE 65.5 颗/图。

两个数字都该进 README 的 Performance 段，并且**明确标成留出集**。
