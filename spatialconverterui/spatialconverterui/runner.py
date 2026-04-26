import os
import subprocess
from PySide6.QtCore import QThread, Signal


class QueueRunner(QThread):
    """
    Runs each queued video sequentially via the spatialconverter CLI.

    For each item, invokes:
        poetry run python main.py --video <abs-path>
    with cwd set to <converter_path>/spatialconverter so that ./spatial and
    ./iPhone15Pro.args resolve. Retries up to max_retries on non-zero exit.
    """

    item_started = Signal(int, int)         # row, attempt (1-based)
    item_finished = Signal(int, bool, str)  # row, success, message
    queue_finished = Signal()
    log_line = Signal(str)

    def __init__(self, items: list[str], converter_path: str, max_retries: int):
        super().__init__()
        self.items = list(items)
        self.converter_path = converter_path
        self.max_retries = max_retries
        self._stop = False
        self._proc: subprocess.Popen | None = None

    def stop(self) -> None:
        self._stop = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self) -> None:
        cwd = os.path.join(self.converter_path, "spatialconverter")
        if not os.path.isdir(cwd):
            self.log_line.emit(f"ERROR: inner spatialconverter dir not found at {cwd}")
            self.queue_finished.emit()
            return

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
                self.log_line.emit(
                    f"[{row + 1}/{len(self.items)}] attempt {attempt}/{total_tries}: {video}"
                )

                try:
                    rc = self._run_one(cwd, video)
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

    def _run_one(self, cwd: str, video: str) -> int:
        cmd = ["poetry", "run", "python", "main.py", "--video", os.path.abspath(video)]
        self._proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self.log_line.emit(line.rstrip())
            if self._stop:
                self._proc.terminate()
                break
        return self._proc.wait()
