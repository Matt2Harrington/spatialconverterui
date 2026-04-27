import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

COL_FILE = 0
COL_STATUS = 1
COL_TRIES = 2
COL_MESSAGE = 3


class QueueTable(QTableWidget):
    """Table of queued videos with drag-and-drop support."""

    files_added = Signal(list)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["File", "Status", "Tries", "Message"])
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
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
            rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
            for r in rows:
                self.removeRow(r)
                del self.paths[r]
            return
        super().keyPressEvent(event)

    def add_file(self, path: str) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self.paths.append(path)
        name_item = QTableWidgetItem(os.path.basename(path))
        name_item.setToolTip(path)
        self.setItem(row, COL_FILE, name_item)
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
