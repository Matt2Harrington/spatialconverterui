import os
import re
import signal
import subprocess
import time
from PySide6.QtCore import QThread, Signal


def _kill_process_group(proc: "subprocess.Popen | None", sig: int) -> None:
    """Send `sig` to the process group of `proc`. Safe to call when proc is
    None or already exited."""
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _wait_or_kill(proc: "subprocess.Popen", term_grace: float = 2.0, kill_grace: float = 1.0) -> int:
    """After SIGTERM has been sent, wait up to term_grace for clean exit, then
    escalate to SIGKILL on the process group and wait kill_grace more.
    Returns the exit code (-1 if still alive somehow)."""
    try:
        return proc.wait(timeout=term_grace)
    except subprocess.TimeoutExpired:
        pass
    _kill_process_group(proc, signal.SIGKILL)
    try:
        return proc.wait(timeout=kill_grace)
    except subprocess.TimeoutExpired:
        return -1


_FRAME_TOTAL_RE = re.compile(r"Processed (\d+) frames")
_FRAME_RE = re.compile(r"frame:\s*(\d+)")
_OUTPUT_RE = re.compile(r"OUTPUT:\s*(.+?)\s*$")


class QueueRunner(QThread):
    """
    Runs each queued video sequentially via the spatialconverter CLI.

    Resolves spatialconverter's venv interpreter once via `poetry env info -e`
    (so we don't accidentally inherit spatialconverterui's venv), then invokes
    that python directly:
        <spatialconverter-venv-python> main.py --video <abs-path> ...
    with cwd set to <converter_path>/spatialconverter so that ./spatial and
    ./iPhone15Pro.args resolve. Retries up to max_retries on non-zero exit.

    Parses converter log lines to drive a progress bar:
      - "Processed N frames" sets the total
      - "frame: K" advances the per-frame counter
    """

    item_started = Signal(int, int)         # row, attempt (1-based)
    item_finished = Signal(int, bool, str)  # row, success, message
    item_phase = Signal(int, str)           # row, phase label
    item_progress = Signal(int, int, int, float)  # row, done, total, eta_seconds (-1 if unknown)
    item_output = Signal(int, str)          # row, output file path
    queue_finished = Signal()
    log_line = Signal(str)

    def __init__(
        self,
        items: list[str],
        converter_path: str,
        max_retries: int,
        model_size: str = "large",
        target_fps: float = 0.0,
        shift_left: int = 10,
        shift_right: int = 50,
        hfov: float = 63.4,
        cdist: float = 19.24,
        hadjust: float = 0.02,
        projection: str = "rect",
        spatial_extra: str = "",
        zoom: float = 1.0,
        stereo_format: str = "ou",
        spatial_enabled: bool = True,
    ):
        super().__init__()
        self.items = list(items)
        self.converter_path = converter_path
        self.max_retries = max_retries
        self.model_size = model_size
        self.target_fps = target_fps
        self.shift_left = shift_left
        self.shift_right = shift_right
        self.hfov = hfov
        self.cdist = cdist
        self.hadjust = hadjust
        self.projection = projection
        self.spatial_extra = spatial_extra
        self.zoom = zoom
        self.stereo_format = stereo_format
        self.spatial_enabled = spatial_enabled
        self._stop = False
        self._proc: subprocess.Popen | None = None
        self._python_exe: str = ""

    def stop(self) -> None:
        self._stop = True
        # SIGTERM the whole process group so multiprocessing workers and the
        # ./spatial subprocess go too — not just the wrapper python process.
        # The runner thread will escalate to SIGKILL if anything hangs past
        # the grace period.
        _kill_process_group(self._proc, signal.SIGTERM)

    def run(self) -> None:
        cwd = os.path.join(self.converter_path, "spatialconverter")
        if not os.path.isdir(cwd):
            self.log_line.emit(f"ERROR: inner spatialconverter dir not found at {cwd}")
            self.queue_finished.emit()
            return

        python_exe = self._resolve_converter_python()
        if not python_exe:
            self.log_line.emit(
                "ERROR: could not resolve spatialconverter's venv interpreter. "
                f"Run `cd {self.converter_path} && poetry install` and try again."
            )
            self.queue_finished.emit()
            return
        self.log_line.emit(f"Using interpreter: {python_exe}")
        self._python_exe = python_exe

        for row, video in enumerate(self.items):
            if self._stop:
                break

            total_tries = self.max_retries + 1
            success = False
            last_err = ""

            for attempt in range(1, total_tries + 1):
                if self._stop:
                    break
                self.item_started.emit(row, attempt)
                self.item_phase.emit(row, "Reading frames…")
                self.item_progress.emit(row, 0, 0, -1.0)
                self.log_line.emit(
                    f"[{row + 1}/{len(self.items)}] attempt {attempt}/{total_tries}: {video}"
                )

                try:
                    rc = self._run_one(cwd, video, row)
                except FileNotFoundError as e:
                    last_err = f"{e}"
                    self.log_line.emit(f"ERROR: {last_err}")
                    break

                if self._stop:
                    last_err = "stopped"
                    break
                if rc == 0:
                    success = True
                    break
                last_err = f"exit code {rc}"
                self.log_line.emit(f"FAILED ({last_err})")

            if self._stop:
                self.item_finished.emit(row, False, "stopped")
                break

            self.item_finished.emit(row, success, "" if success else last_err)

        self.queue_finished.emit()

    def _run_one(self, cwd: str, video: str, row: int) -> int:
        cmd = [
            self._python_exe, "main.py",
            "--video", os.path.abspath(video),
            "--model-size", self.model_size,
            "--shift-left", str(self.shift_left),
            "--shift-right", str(self.shift_right),
            "--hfov", str(self.hfov),
            "--cdist", str(self.cdist),
            "--hadjust", str(self.hadjust),
            "--projection", self.projection,
            "--zoom", str(self.zoom),
            "--stereo-format", self.stereo_format,
        ]
        if self.target_fps and self.target_fps > 0:
            cmd += ["--target-fps", str(self.target_fps)]
        if self.spatial_extra.strip():
            cmd += ["--spatial-extra", self.spatial_extra.strip()]
        if not self.spatial_enabled:
            cmd += ["--no-spatial"]

        env = self._clean_env()
        # main.py does `from spatialconverter.X import Y`, so the *outer*
        # spatialconverter dir must be on PYTHONPATH for the import to resolve
        # when we run the script from the inner dir (required so ./spatial and
        # ./iPhone15Pro.args resolve).
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            self.converter_path + (os.pathsep + existing if existing else "")
        )

        self._proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            # Put the child in its own process group so killing it from
            # stop() also kills its multiprocessing workers and any further
            # children (e.g. the ./spatial subprocess).
            start_new_session=True,
        )
        assert self._proc.stdout is not None

        total = 0
        seen: set[int] = set()
        t_first_frame: float | None = None
        encoding_announced = False

        for line in self._proc.stdout:
            line = line.rstrip()
            self.log_line.emit(line)
            if self._stop:
                # SIGTERM was already sent by stop(); just bail out of
                # reading. Wait + escalate happens after the loop.
                break

            m = _FRAME_TOTAL_RE.search(line)
            if m:
                total = int(m.group(1))
                self.item_phase.emit(row, "Processing frames")
                self.item_progress.emit(row, 0, total, -1.0)
                continue

            m = _OUTPUT_RE.search(line)
            if m:
                self.item_output.emit(row, m.group(1))
                continue

            m = _FRAME_RE.search(line)
            if m:
                idx = int(m.group(1))
                if idx in seen:
                    continue
                seen.add(idx)
                if t_first_frame is None:
                    t_first_frame = time.monotonic()
                eta = -1.0
                if total and len(seen) > 0 and t_first_frame is not None:
                    elapsed = time.monotonic() - t_first_frame
                    per = elapsed / len(seen)
                    eta = max(0.0, (total - len(seen)) * per)
                self.item_progress.emit(row, len(seen), total, eta)
                if total and len(seen) >= total and not encoding_announced:
                    self.item_phase.emit(row, "Encoding video…")
                    encoding_announced = True

        # If we exited the read loop because of a stop request, the SIGTERM
        # has already been sent. Wait briefly for clean exit, then SIGKILL the
        # process group if anything is hanging on.
        if self._stop and self._proc.poll() is None:
            return _wait_or_kill(self._proc)
        return self._proc.wait()

    def _clean_env(self) -> dict[str, str]:
        """Copy of os.environ with vars that would tie us to spatialconverterui's
        venv removed, so subprocesses resolve spatialconverter's env cleanly."""
        env = os.environ.copy()
        for key in ("VIRTUAL_ENV", "POETRY_ACTIVE", "PYTHONHOME"):
            env.pop(key, None)
        return env

    def _resolve_converter_python(self) -> str:
        """Ask poetry for the path to spatialconverter's venv interpreter."""
        try:
            result = subprocess.run(
                ["poetry", "env", "info", "-e"],
                cwd=self.converter_path,
                capture_output=True,
                text=True,
                env=self._clean_env(),
                timeout=30,
            )
        except Exception as e:
            self.log_line.emit(f"WARN: `poetry env info -e` failed: {e}")
            return ""
        candidate = (result.stdout or "").strip()
        if not candidate:
            self.log_line.emit(
                f"WARN: `poetry env info -e` returned nothing. stderr: {(result.stderr or '').strip()}"
            )
            return ""
        if not os.path.exists(candidate):
            self.log_line.emit(f"WARN: resolved interpreter does not exist: {candidate}")
            return ""
        return candidate


class PreviewRunner(QThread):
    """One-shot single-frame preview. Builds the same subprocess command as
    QueueRunner but with --preview, parses the OUTPUT: line, and emits the
    PNG path back. No retries, no queue iteration."""

    finished_ok = Signal(str)   # PNG path
    finished_err = Signal(str)  # error message
    log_line = Signal(str)

    def __init__(
        self,
        video_path: str,
        converter_path: str,
        model_size: str = "large",
        target_fps: float = 0.0,
        shift_left: int = 10,
        shift_right: int = 50,
        hfov: float = 63.4,
        cdist: float = 19.24,
        hadjust: float = 0.02,
        projection: str = "rect",
        spatial_extra: str = "",
        zoom: float = 1.0,
        stereo_format: str = "ou",
        spatial_enabled: bool = True,
        preview_time: float | None = None,
        clip_mode: bool = False,
        clip_duration: float = 3.0,
        clip_start: float | None = None,
    ):
        super().__init__()
        self.video_path = video_path
        self.converter_path = converter_path
        self.model_size = model_size
        self.target_fps = target_fps
        self.shift_left = shift_left
        self.shift_right = shift_right
        self.hfov = hfov
        self.cdist = cdist
        self.hadjust = hadjust
        self.projection = projection
        self.spatial_extra = spatial_extra
        self.zoom = zoom
        self.stereo_format = stereo_format
        self.spatial_enabled = spatial_enabled
        self.preview_time = preview_time
        self.clip_mode = clip_mode
        self.clip_duration = clip_duration
        self.clip_start = clip_start
        self._proc: subprocess.Popen | None = None
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        # SIGTERM the entire process group to take down workers + ./spatial
        # along with the wrapper python.
        _kill_process_group(self._proc, signal.SIGTERM)

    def run(self) -> None:
        cwd = os.path.join(self.converter_path, "spatialconverter")
        if not os.path.isdir(cwd):
            self.finished_err.emit(f"inner spatialconverter dir not found at {cwd}")
            return

        python_exe = self._resolve_converter_python()
        if not python_exe:
            self.finished_err.emit(
                f"could not resolve spatialconverter's venv. Run `cd {self.converter_path} && poetry install`."
            )
            return

        cmd = [
            python_exe, "main.py",
            "--video", os.path.abspath(self.video_path),
            "--model-size", self.model_size,
            "--shift-left", str(self.shift_left),
            "--shift-right", str(self.shift_right),
            "--hfov", str(self.hfov),
            "--cdist", str(self.cdist),
            "--hadjust", str(self.hadjust),
            "--projection", self.projection,
            "--zoom", str(self.zoom),
            "--stereo-format", self.stereo_format,
        ]
        if not self.spatial_enabled:
            cmd += ["--no-spatial"]
        if self.clip_mode:
            cmd += ["--preview-clip", "--preview-clip-duration", str(self.clip_duration)]
            if self.clip_start is not None:
                cmd += ["--preview-clip-start", str(self.clip_start)]
        else:
            cmd += ["--preview"]
            if self.preview_time is not None:
                cmd += ["--preview-time", str(self.preview_time)]

        env = os.environ.copy()
        for key in ("VIRTUAL_ENV", "POETRY_ACTIVE", "PYTHONHOME"):
            env.pop(key, None)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            self.converter_path + (os.pathsep + existing if existing else "")
        )

        self._proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
            start_new_session=True,
        )
        assert self._proc.stdout is not None

        png_path: str | None = None
        for line in self._proc.stdout:
            line = line.rstrip()
            self.log_line.emit(line)
            if self._stop:
                # SIGTERM was already sent by stop(); just bail out.
                break
            m = _OUTPUT_RE.search(line)
            if m:
                png_path = m.group(1)

        if self._stop and self._proc.poll() is None:
            rc = _wait_or_kill(self._proc)
        else:
            rc = self._proc.wait()
        if self._stop:
            self.finished_err.emit("preview cancelled")
        elif rc != 0:
            self.finished_err.emit(f"preview exited with code {rc}")
        elif not png_path or not os.path.exists(png_path):
            self.finished_err.emit("preview finished but no OUTPUT: line was found in the log")
        else:
            self.finished_ok.emit(png_path)

    def _clean_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in ("VIRTUAL_ENV", "POETRY_ACTIVE", "PYTHONHOME"):
            env.pop(key, None)
        return env

    def _resolve_converter_python(self) -> str:
        try:
            result = subprocess.run(
                ["poetry", "env", "info", "-e"],
                cwd=self.converter_path,
                capture_output=True,
                text=True,
                env=self._clean_env(),
                timeout=30,
            )
        except Exception as e:
            self.log_line.emit(f"WARN: `poetry env info -e` failed: {e}")
            return ""
        candidate = (result.stdout or "").strip()
        if candidate and os.path.exists(candidate):
            return candidate
        return ""
