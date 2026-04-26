# spatialconverterui

A small drag-and-drop macOS GUI for queueing 2D-to-spatial video conversions
through [spatialconverter](https://github.com/herrickfang/vision-utils/tree/main/spatialconverter).

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

Requires Python 3.10+ and [poetry](https://python-poetry.org/) on PATH.
You also need a working [spatialconverter](https://github.com/herrickfang/vision-utils/tree/main/spatialconverter)
checkout — see its README for the one-time setup.

```bash
git clone <this-repo-url> spatialconverterui
cd spatialconverterui
poetry install
```

## Run

```bash
poetry run spatialconverterui
```

In the UI:

1. Set **spatialconverter path** to the outer `spatialconverter/` directory
   (the one containing `pyproject.toml`).
2. Set **Max retries on failure** if you want something other than the default of 3.
3. Drag video files into the queue (or use **Add Files…**).
4. Hit **Start**. Use **Stop** to halt after the current item finishes.

## How it runs each job

For each queued video, the runner executes:

```bash
poetry run python main.py --video <absolute-video-path>
```

with `cwd` set to `<spatialconverter path>/spatialconverter` so that the
`./spatial` binary and `./iPhone15Pro.args` resolve correctly.

If the process exits non-zero, the item is retried up to `max_retries` times
before being marked Failed. The queue then continues with the next item.

## Notes

- Launch from a terminal (`poetry run spatialconverterui`) so the `poetry`
  binary is on PATH. A bundled `.app` launched from Finder won't inherit your
  shell PATH and will fail to find `poetry`.
- Only video extensions are accepted via drag-drop:
  `.mp4 .mov .m4v .avi .mkv`.
