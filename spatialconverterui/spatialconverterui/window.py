from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .queue_widget import QueueTable, VIDEO_EXTS
from .runner import QueueRunner


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpatialConverter UI")
        self.resize(960, 640)
        self.settings = QSettings()

        self.path_edit = QLineEdit(self.settings.value("converter_path", "", type=str))
        self.path_edit.setPlaceholderText("/path/to/vision-utils/spatialconverter")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 20)
        self.retries_spin.setValue(int(self.settings.value("max_retries", 3)))

        settings_box = QGroupBox("Settings")
        form = QFormLayout(settings_box)
        form.addRow("spatialconverter path:", path_row)
        form.addRow("Max retries on failure:", self.retries_spin)

        self.queue = QueueTable()

        self.add_btn = QPushButton("Add Files…")
        self.add_btn.clicked.connect(self._add_files)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear_queue)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(settings_box)
        exts = " ".join(sorted(VIDEO_EXTS))
        layout.addWidget(QLabel(f"Queue (drag video files here — accepted: {exts}):"))
        layout.addWidget(self.queue, 2)
        layout.addLayout(btn_row)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.runner: QueueRunner | None = None

    def _browse_path(self):
        d = QFileDialog.getExistingDirectory(self, "Choose spatialconverter directory")
        if d:
            self.path_edit.setText(d)

    def _add_files(self):
        pattern = "Videos (" + " ".join(f"*{e}" for e in sorted(VIDEO_EXTS)) + ")"
        files, _ = QFileDialog.getOpenFileNames(self, "Add videos", "", pattern)
        for f in files:
            self.queue.add_file(f)

    def _clear_queue(self):
        if self.runner and self.runner.isRunning():
            QMessageBox.information(self, "Busy", "Stop the queue before clearing.")
            return
        self.queue.clear_all()

    def _start(self):
        if self.runner and self.runner.isRunning():
            return
        if not self.queue.paths:
            QMessageBox.information(self, "Empty queue", "Add at least one video.")
            return
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Missing path", "Set the spatialconverter path first.")
            return

        self.settings.setValue("converter_path", path)
        self.settings.setValue("max_retries", self.retries_spin.value())

        self.queue.reset_statuses()
        self.log.clear()

        self.runner = QueueRunner(
            list(self.queue.paths), path, self.retries_spin.value()
        )
        self.runner.item_started.connect(self._on_item_started)
        self.runner.item_finished.connect(self._on_item_finished)
        self.runner.queue_finished.connect(self._on_queue_finished)
        self.runner.log_line.connect(self.log.appendPlainText)

        self._set_running(True)
        self.statusBar().showMessage(f"Running {len(self.queue.paths)} item(s)…")
        self.runner.start()

    def _stop(self):
        if self.runner and self.runner.isRunning():
            self.statusBar().showMessage("Stopping…")
            self.runner.stop()

    def _set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.add_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.path_edit.setEnabled(not running)
        self.retries_spin.setEnabled(not running)

    def _on_item_started(self, row: int, attempt: int):
        status = "Running" if attempt == 1 else "Retrying"
        self.queue.set_status(row, status, tries=attempt)

    def _on_item_finished(self, row: int, ok: bool, msg: str):
        self.queue.set_status(row, "Done" if ok else "Failed", message=msg)

    def _on_queue_finished(self):
        self._set_running(False)
        self.statusBar().showMessage("Queue finished.", 5000)

    def closeEvent(self, event):
        if self.runner and self.runner.isRunning():
            reply = QMessageBox.question(
                self,
                "Quit?",
                "A conversion is still running. Stop it and quit?",
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.runner.stop()
            self.runner.wait(5000)
        event.accept()
