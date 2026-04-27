# spatialconverterui

A small drag-and-drop macOS GUI for queueing 2D-to-spatial video conversions
through [spatialconverter](https://github.com/Matt2Harrington/vision-utils/tree/main/spatialconverter).

Add unlimited videos, hit Start, and the app processes each one sequentially.
On failure, it automatically retries up to a configurable number of times.

## Features

- Drag-and-drop a queue of any size
- Per-item status: Queued / Running / Retrying / Done / Failed
- Auto-retry on failure (configurable, default 3)
- Sequential execution (one GPU job at a time)
- Live log view of converter output
- Settings persist between launches

## Install

**Requirements:** macOS, Python 3.10–3.14, [poetry](https://python-poetry.org/)
on PATH, and git. A Vision-Pro-capable Apple Silicon machine is recommended —
the depth-estimation model is heavy.

### Prerequisites (skip what you already have)

```bash
brew install python@3.13 poetry git
python3.13 --version   # confirm it's installed
poetry --version
```

> **Use Python 3.13, not 3.14.** Homebrew's `python@3.14` ships a `pyexpat`
> built against a newer `libexpat` than macOS provides, which crashes any
> Python tool that touches XML (`Symbol not found:
> _XML_SetAllocTrackerActivationThreshold`). 3.13 is stable and matches the
> project's supported range.

### Fresh machine — one-shot setup

This installs both this UI **and** the converter it drives, side-by-side.

```bash
# Pick a parent folder for both repos
mkdir -p ~/Documents/Projects && cd ~/Documents/Projects

# 1) Core converter
git clone https://github.com/Matt2Harrington/vision-utils.git
cd vision-utils/spatialconverter
poetry env use python3.13
poetry install
# transformers needs a from-source install (poetry can't resolve it cleanly)
poetry run pip install -q "git+https://github.com/huggingface/transformers.git"
cd ../..

# 2) This UI
git clone https://github.com/Matt2Harrington/spatialconverterui.git
cd spatialconverterui
poetry env use python3.13
poetry install
```

### Already have vision-utils checked out

```bash
git clone https://github.com/Matt2Harrington/spatialconverterui.git
cd spatialconverterui
poetry env use python3.13
poetry install
```

## Run

```bash
poetry run spatialconverterui
```

On first launch, click **Browse…** and point **spatialconverter path** at the
outer `vision-utils/spatialconverter/` directory (the one with `pyproject.toml`).
The path persists between launches.

> **First conversion is slow.** Hugging Face will download the Depth-Anything-V2
> weights on the first run (~1.3 GB for Large, ~100 MB for Small). Subsequent
> runs use the cached model.

In the UI:

1. Confirm **spatialconverter path** is set to the outer `spatialconverter/`
   directory (the one containing `pyproject.toml`).
2. Adjust runtime settings (all persist between launches):

   **Conversion settings** (control speed / quality of the depth-shift step)
   - **Max retries on failure** — default 3.
   - **Depth model** — Small / Base / Large. Smaller is dramatically faster
     but lower quality. Large preserves the original behavior.
   - **Target FPS** — `0` keeps the source fps. Setting it lower than the
     source samples frames at a stride and proportionally cuts runtime
     (e.g. 60 → 30 fps roughly halves runtime).
   - **Eye shifts (L / R)** — depth-shift amounts for the left/right eyes.
     Defaults 10 / 50. Larger gap = more pronounced 3D effect.

   **Spatial output** (passed verbatim to Mike Swanson's `./spatial` tool)
   - **Horizontal FOV** — degrees. Default `63.4` (iPhone 15 Pro main lens).
     If footage looks "too zoomed in" on Vision Pro, raise this. Rough
     starting points: 90° for general widescreen, 110-120° for action
     cameras / ultrawides, 63-77° for typical phone main / mirrorless.
   - **Camera distance** — eye baseline in mm. Default `19.24`.
   - **Horizontal adjust** — alignment offset. Default `0.02`.
   - **Projection** — `rect`, `fisheye`, or `half_equirect`. The combo is
     editable, so any value the `spatial` tool supports can be typed.
   - **Extra args** — free-form flags appended verbatim to the `./spatial
     make` command (e.g. `--primary right`). For anything the dropdowns
     don't cover.
3. Drag video files into the queue (or use **Add Files…**).
4. Hit **Start**. Use **Stop** to halt after the current item finishes.

## How it runs each job

For each queued video, the runner resolves spatialconverter's venv interpreter
via `poetry env info -e` (so it never accidentally uses spatialconverterui's
venv) and invokes:

```bash
<spatialconverter-venv-python> main.py \
  --video <absolute-video-path> \
  --model-size {small|base|large} \
  --shift-left N --shift-right N \
  --hfov F --cdist F --hadjust F --projection STR \
  [--target-fps F] \
  [--spatial-extra "<...>"]
```

with `cwd` set to `<spatialconverter path>/spatialconverter` and `PYTHONPATH`
set to `<spatialconverter path>` so that `./spatial`, `./iPhone15Pro.args`,
and `from spatialconverter.X import Y` all resolve.

> Requires a version of `spatialconverter` that supports these CLI flags
> (added alongside this UI). Older copies of `spatialconverter` will fail
> with "unrecognized arguments" — pull the matching update before running.

If the process exits non-zero, the item is retried up to `max_retries` times
before being marked Failed. The queue then continues with the next item.

## Troubleshooting

If a conversion fails, check the in-app console pane for one of these markers:

- **`Symbol not found: _XML_SetAllocTrackerActivationThreshold`** during
  `poetry install` or `poetry run` — Homebrew's `python@3.14` is broken on
  macOS. Switch to 3.13:
  ```bash
  brew install python@3.13
  brew unlink python@3.14   # optional
  cd <project-dir>
  poetry env remove --all
  poetry env use python3.13
  poetry install
  ```
- **`ERROR: could not resolve spatialconverter's venv interpreter`** —
  `poetry install` was never run inside `vision-utils/spatialconverter/`.
  Re-run step 1 of the install block.
- **`ModuleNotFoundError: No module named 'transformers'`** — the from-source
  transformers install was skipped or failed. Re-run:
  ```bash
  cd ~/Documents/Projects/vision-utils/spatialconverter
  poetry run pip install -q "git+https://github.com/huggingface/transformers.git"
  ```
- **`Using interpreter: …spatialconverterui…`** at the top of the log —
  the path field points at the wrong directory. It should be the **outer**
  `spatialconverter/` (the one with `pyproject.toml`), not the inner one and
  not the UI repo.
- **Output looks "way too zoomed in" on Vision Pro** — the source isn't
  iPhone-15-Pro footage. Bump **Horizontal FOV** to 90 (general widescreen),
  110-120 (action cam / ultrawide), or whatever matches your source lens.

## Notes

- Launch from a terminal (`poetry run spatialconverterui`) so the `poetry`
  binary is on PATH. A bundled `.app` launched from Finder won't inherit your
  shell PATH and will fail to find `poetry`.
- Only video extensions are accepted via drag-drop:
  `.mp4 .mov .m4v .avi .mkv`.
