import json
import os
import subprocess
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
)

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

COL_FILE = 0
COL_INFO = 1
COL_STATUS = 2
COL_TRIES = 3
COL_MESSAGE = 4


def probe_video_metadata(path: str) -> tuple[str, str]:
    """Best-effort video metadata probe via ffprobe.

    Returns a (short_summary, long_tooltip) tuple. If ffprobe is unavailable
    or the file isn't readable, returns ("", "") and the caller should fall
    back gracefully.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,codec_name",
                "-show_entries", "format=duration,size,format_long_name",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", ""
    if result.returncode != 0:
        return "", ""
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return "", ""

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    if not streams:
        return "", ""
    s = streams[0]
    w = s.get("width")
    h = s.get("height")
    codec = s.get("codec_name") or ""
    fps_str = s.get("r_frame_rate") or "0/1"
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except Exception:
        fps = 0.0
    try:
        duration_s = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration_s = 0.0
    try:
        size_b = int(fmt.get("size") or 0)
    except (TypeError, ValueError):
        size_b = 0
    container = fmt.get("format_long_name") or ""

    parts: list[str] = []
    if w and h:
        parts.append(f"{w}×{h}")
    if fps:
        parts.append(f"{fps:.0f}fps" if abs(fps - round(fps)) < 0.05 else f"{fps:.2f}fps")
    if duration_s:
        m = int(duration_s) // 60
        sec = int(duration_s) % 60
        if m >= 60:
            h_ = m // 60
            m = m % 60
            parts.append(f"{h_}:{m:02d}:{sec:02d}")
        else:
            parts.append(f"{m}:{sec:02d}")
    short = " ".join(parts)

    long_lines: list[str] = [path]
    if w and h:
        long_lines.append(f"Resolution: {w}×{h}")
    if fps:
        long_lines.append(f"Frame rate: {fps:.3f} fps")
    if duration_s:
        long_lines.append(f"Duration: {duration_s:.2f} s")
    if codec:
        long_lines.append(f"Video codec: {codec}")
    if container:
        long_lines.append(f"Container: {container}")
    if size_b:
        mb = size_b / (1024 * 1024)
        long_lines.append(f"File size: {mb:.1f} MB")
    return short, "\n".join(long_lines)


class QueueTable(QTableWidget):
    """Table of queued videos with drag-and-drop support."""

    files_added = Signal(list)
    duplicate_requested = Signal(list)  # list of paths to add as duplicates

    def __init__(self):
        super().__init__(0, 5)
        self.setHorizontalHeaderLabels(["File", "Info", "Status", "Tries", "Message"])
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_INFO, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TRIES, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_MESSAGE, QHeaderView.Stretch)

        self.paths: list[str] = []

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        added = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.splitext(path)[1].lower() in VIDEO_EXTS:
                self.add_file(path)
                added.append(path)
        if added:
            self.files_added.emit(added)
            event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._remove_selected_rows()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        rows = sorted({i.row() for i in self.selectedIndexes()})
        menu = QMenu(self)
        dup_action = menu.addAction("Duplicate row")
        dup_action.setEnabled(bool(rows))
        del_action = menu.addAction("Remove row")
        del_action.setEnabled(bool(rows))
        chosen = menu.exec(event.globalPos())
        if chosen is dup_action:
            paths = [self.paths[r] for r in rows if 0 <= r < len(self.paths)]
            for p in paths:
                self.add_file(p)
            if paths:
                self.duplicate_requested.emit(paths)
        elif chosen is del_action:
            self._remove_selected_rows()

    def _remove_selected_rows(self):
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < self.rowCount():
                self.removeRow(r)
                del self.paths[r]

    def add_file(self, path: str) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self.paths.append(path)

        name_item = QTableWidgetItem(os.path.basename(path))
        name_item.setToolTip(path)
        self.setItem(row, COL_FILE, name_item)

        # Probe metadata synchronously — ffprobe reads only the container header
        # so this is fast even for big files. Falls back silently if unavailable.
        info_short, info_long = probe_video_metadata(path)
        info_item = QTableWidgetItem(info_short)
        if info_long:
            info_item.setToolTip(info_long)
            # Also enrich the filename tooltip so hovering anywhere on the row
            # surfaces the metadata.
            name_item.setToolTip(info_long)
        self.setItem(row, COL_INFO, info_item)

        self.setItem(row, COL_STATUS, QTableWidgetItem("Queued"))
        self.setItem(row, COL_TRIES, QTableWidgetItem("0"))
        self.setItem(row, COL_MESSAGE, QTableWidgetItem(""))

    def clear_all(self) -> None:
        self.setRowCount(0)
        self.paths.clear()

    def reset_statuses(self) -> None:
        for r in range(self.rowCount()):
            self.item(r, COL_STATUS).setText("Queued")
            self.item(r, COL_TRIES).setText("0")
            self.item(r, COL_MESSAGE).setText("")

    def set_status(self, row: int, status: str, tries: int | None = None, message: str | None = None) -> None:
        if 0 <= row < self.rowCount():
            self.item(row, COL_STATUS).setText(status)
            if tries is not None:
                self.item(row, COL_TRIES).setText(str(tries))
            if message is not None:
                self.item(row, COL_MESSAGE).setText(message)
