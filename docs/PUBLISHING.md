# Publishing checklist

Everything below is done **except** the three steps that need your GitHub account.
Work through it top to bottom; nothing here touches the lab data.

---

## Status

| Item | State |
|---|---|
| Repository contents (17 files + CI + tests) | **done** |
| Local commit on branch `master` | **done** — `b2f1411` + the CI commit |
| Hard-coded paths removed | **done** — 4 sites |
| Frame filename assumption (`frame_*.jpg`) removed | **done** — 2 sites |
| ASR chain / API-key code / backups / conflict files excluded | **done** — see `docs/EXCLUDED.md` |
| Real microscope frames in the repo | **none** — synthetic generator only |
| `pip install -e .` verified | **done** |
| Synthetic end-to-end + P/R check | **done** — P 99.2% / R 88.0% |
| CI workflow | **done** — `.github/workflows/ci.yml`, py 3.9 / 3.11 / 3.12 |
| README, MIT LICENSE, CITATION.cff, requirements, pyproject | **done** |
| GitHub remote + push | **you** |
| Zenodo DOI | **you** (2 clicks, see step 4) |

---

## Step 1 — Replace the placeholder (1 minute)

Two places carry `YOURNAME`:

- `README.md` — the CI badge URL (top of file)
- nothing else; `pyproject.toml` and `CITATION.cff` need no username

```bash
cd Products/oss/microparticle-detector
# edit README.md, replace YOURNAME
git add README.md
git -c user.name="He Qizhen" -c user.email="you@example.com" \
    commit -m "Set CI badge URL"
```

Optional but recommended before pushing: put your real email in the last two commits.

```bash
git config user.name  "He Qizhen"
git config user.email "your-real@email"
git commit --amend --reset-author --no-edit      # last commit only
```

## Step 2 — Create the empty remote

On GitHub: **New repository** →

- name `microparticle-detector`
- **Public**
- **do not** add README / .gitignore / license — the repo already has all three
- create

## Step 3 — Push

```bash
cd Products/oss/microparticle-detector
git remote add origin https://github.com/YOURNAME/microparticle-detector.git
git branch -M main
git push -u origin main
```

Then open the **Actions** tab. Three jobs should go green in ~5 minutes. If they do
not, the failure is almost always the OpenCV install (the workflow already uses
`opencv-python-headless` to avoid the missing `libGL` on the runner).

## Step 4 — Zenodo DOI (this is what makes it citable)

1. Sign in to <https://zenodo.org> with GitHub.
2. **Settings → GitHub** → flip `microparticle-detector` to **ON**.
3. Back in the repo: **Releases → Draft a new release** →
   - tag `v1.0.0`, title `v1.0.0`, publish.
4. Zenodo mints the DOI within a minute. Copy it.
5. Put it in two places and push again:

```markdown
<!-- README.md, under the badges -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
```

```yaml
# CITATION.cff, append
doi: 10.5281/zenodo.XXXXXXX
```

That DOI is the citable object for a TPM paper's Methods section — you do **not**
need to wait for any journal.

---

## What is deliberately NOT in this repo

- **The 22 annotated frames** and the bad/miss labels. These are lab assets; they
  need Prof. Wang's approval and are best kept in a *separate* data repository
  (`tpm-microsphere-benchmark`, CC BY 4.0) so code and data can be cited apart.
  A datasheet template and the frame/annotation directory layout can be prepared
  once that approval is in hand.
- **Line A** (`s6_triage` + `s6_size_measure`). It depends on an external standard-
  sphere calibration file; without that file it silently skips calibration, which
  would be misleading to an outside user. Revisit only if the calibration file can
  be shipped too.
- The ASR / AI-video-analysis chain. Unrelated to detection, and it carries
  `MIMO_API_KEY` handling.

Full reasoning per excluded file: `docs/EXCLUDED.md`.

---

## After publishing — the two comparisons that matter

1. **Our tool on PSCount's 24 public test frames** (CPU only, no GPU). This is the
   out-of-sample, cross-system check that the current numbers lack.
2. **Cellpose-SAM zero-shot on our 22 frames** (needs your GPU machine). Compare
   against PSCount's own reported zero-shot MAE of 65.5 particles/image.

Both numbers belong in the README's Performance section, labelled as held-out.
