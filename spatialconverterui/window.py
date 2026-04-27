import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .queue_widget import QueueTable, VIDEO_EXTS
from .runner import QueueRunner


def _format_eta(seconds: float) -> str:
    if seconds < 0:
        return "ETA: —"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"ETA: {h}h {m:02d}m {s:02d}s"
    if m:
        return f"ETA: {m}m {s:02d}s"
    return f"ETA: {s}s"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpatialConverter UI")
        self.resize(1000, 720)
        self.settings = QSettings()

        # ---- settings group ----
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

        self.model_combo = QComboBox()
        self.model_combo.addItem("Small (fastest, lower quality)", "small")
        self.model_combo.addItem("Base", "base")
        self.model_combo.addItem("Large (slowest, best quality)", "large")
        saved_model = self.settings.value("model_size", "large", type=str)
        idx = self.model_combo.findData(saved_model)
        self.model_combo.setCurrentIndex(idx if idx >= 0 else 2)

        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.0, 240.0)
        self.fps_spin.setDecimals(2)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setSpecialValueText("source fps")
        self.fps_spin.setValue(float(self.settings.value("target_fps", 0.0)))

        self.shift_left_spin = QSpinBox()
        self.shift_left_spin.setRange(0, 200)
        self.shift_left_spin.setValue(int(self.settings.value("shift_left", 10)))

        self.shift_right_spin = QSpinBox()
        self.shift_right_spin.setRange(0, 200)
        self.shift_right_spin.setValue(int(self.settings.value("shift_right", 50)))

        shifts_row = QHBoxLayout()
        shifts_row.addWidget(QLabel("L:"))
        shifts_row.addWidget(self.shift_left_spin)
        shifts_row.addSpacing(12)
        shifts_row.addWidget(QLabel("R:"))
        shifts_row.addWidget(self.shift_right_spin)
        shifts_row.addStretch(1)

        settings_box = QGroupBox("Conversion settings")
        form = QFormLayout(settings_box)
        form.addRow("spatialconverter path:", path_row)
        form.addRow("Max retries on failure:", self.retries_spin)
        form.addRow("Depth model:", self.model_combo)
        form.addRow("Target FPS (0 = source):", self.fps_spin)
        form.addRow("Eye shifts:", shifts_row)

        # ---- Spatial output settings ----
        self.hfov_spin = QDoubleSpinBox()
        self.hfov_spin.setRange(1.0, 180.0)
        self.hfov_spin.setDecimals(2)
        self.hfov_spin.setSingleStep(1.0)
        self.hfov_spin.setSuffix("°")
        self.hfov_spin.setValue(float(self.settings.value("hfov", 63.4)))

        self.cdist_spin = QDoubleSpinBox()
        self.cdist_spin.setRange(0.0, 200.0)
        self.cdist_spin.setDecimals(2)
        self.cdist_spin.setSingleStep(0.5)
        self.cdist_spin.setSuffix(" mm")
        self.cdist_spin.setValue(float(self.settings.value("cdist", 19.24)))

        self.hadjust_spin = QDoubleSpinBox()
        self.hadjust_spin.setRange(-10.0, 10.0)
        self.hadjust_spin.setDecimals(3)
        self.hadjust_spin.setSingleStep(0.01)
        self.hadjust_spin.setValue(float(self.settings.value("hadjust", 0.02)))

        self.projection_combo = QComboBox()
        self.projection_combo.setEditable(True)
        for value in ("rect", "fisheye", "half_equirect"):
            self.projection_combo.addItem(value)
        self.projection_combo.setCurrentText(
            self.settings.value("projection", "rect", type=str)
        )

        self.spatial_extra_edit = QLineEdit(
            self.settings.value("spatial_extra", "", type=str)
        )
        self.spatial_extra_edit.setPlaceholderText('e.g. --primary right')

        spatial_box = QGroupBox("Spatial output (./spatial flags)")
        spatial_form = QFormLayout(spatial_box)
        spatial_form.addRow("Horizontal FOV:", self.hfov_spin)
        spatial_form.addRow("Camera distance:", self.cdist_spin)
        spatial_form.addRow("Horizontal adjust:", self.hadjust_spin)
        spatial_form.addRow("Projection:", self.projection_combo)
        spatial_form.addRow("Extra args:", self.spatial_extra_edit)

        # group the two settings boxes side-by-side so vertical space is preserved
        settings_row = QHBoxLayout()
        settings_row.addWidget(settings_box, 1)
        settings_row.addWidget(spatial_box, 1)

        # ---- queue ----
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

        # ---- current item / progress group ----
        self.current_label = QLabel("No item running")
        self.phase_label = QLabel("Idle")
        self.eta_label = QLabel("ETA: —")
        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 1)
        self.current_progress.setValue(0)
        self.current_progress.setTextVisible(True)
        self.current_progress.setFormat("")

        progress_box = QGroupBox("Current item")
        pg_layout = QVBoxLayout(progress_box)
        top_row = QHBoxLayout()
        top_row.addWidget(self.current_label, 1)
        top_row.addWidget(self.phase_label)
        pg_layout.addLayout(top_row)
        pg_layout.addWidget(self.current_progress)
        pg_layout.addWidget(self.eta_label)

        # ---- console output group ----
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.log.clear)

        log_box = QGroupBox("Console output")
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self.log, 1)
        log_btn_row = QHBoxLayout()
        log_btn_row.addStretch(1)
        log_btn_row.addWidget(clear_log_btn)
        log_layout.addLayout(log_btn_row)

        # ---- splitter wrapping queue+progress and console so user can resize ----
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        exts = " ".join(sorted(VIDEO_EXTS))
        top_layout.addWidget(QLabel(f"Queue (drag video files here — accepted: {exts}):"))
        top_layout.addWidget(self.queue, 1)
        top_layout.addLayout(btn_row)
        top_layout.addWidget(progress_box)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_widget)
        splitter.addWidget(log_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(settings_row)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.runner: QueueRunner | None = None

    # ---- actions ----

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

        model_size = self.model_combo.currentData()
        target_fps = float(self.fps_spin.value())
        shift_left = int(self.shift_left_spin.value())
        shift_right = int(self.shift_right_spin.value())
        hfov = float(self.hfov_spin.value())
        cdist = float(self.cdist_spin.value())
        hadjust = float(self.hadjust_spin.value())
        projection = self.projection_combo.currentText().strip() or "rect"
        spatial_extra = self.spatial_extra_edit.text()

        self.settings.setValue("converter_path", path)
        self.settings.setValue("max_retries", self.retries_spin.value())
        self.settings.setValue("model_size", model_size)
        self.settings.setValue("target_fps", target_fps)
        self.settings.setValue("shift_left", shift_left)
        self.settings.setValue("shift_right", shift_right)
        self.settings.setValue("hfov", hfov)
        self.settings.setValue("cdist", cdist)
        self.settings.setValue("hadjust", hadjust)
        self.settings.setValue("projection", projection)
        self.settings.setValue("spatial_extra", spatial_extra)

        self.queue.reset_statuses()
        self.log.clear()
        self._reset_progress_panel()

        self.runner = QueueRunner(
            list(self.queue.paths),
            path,
            self.retries_spin.value(),
            model_size=model_size,
            target_fps=target_fps,
            shift_left=shift_left,
            shift_right=shift_right,
            hfov=hfov,
            cdist=cdist,
            hadjust=hadjust,
            projection=projection,
            spatial_extra=spatial_extra,
        )
        self.runner.item_started.connect(self._on_item_started)
        self.runner.item_finished.connect(self._on_item_finished)
        self.runner.item_phase.connect(self._on_item_phase)
        self.runner.item_progress.connect(self._on_item_progress)
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
        self.model_combo.setEnabled(not running)
        self.fps_spin.setEnabled(not running)
        self.shift_left_spin.setEnabled(not running)
        self.shift_right_spin.setEnabled(not running)
        self.hfov_spin.setEnabled(not running)
        self.cdist_spin.setEnabled(not running)
        self.hadjust_spin.setEnabled(not running)
        self.projection_combo.setEnabled(not running)
        self.spatial_extra_edit.setEnabled(not running)

    def _reset_progress_panel(self):
        self.current_label.setText("No item running")
        self.phase_label.setText("Idle")
        self.current_progress.setRange(0, 1)
        self.current_progress.setValue(0)
        self.current_progress.setFormat("")
        self.eta_label.setText("ETA: —")

    # ---- runner signal handlers ----

    def _on_item_started(self, row: int, attempt: int):
        status = "Running" if attempt == 1 else "Retrying"
        self.queue.set_status(row, status, tries=attempt)
        name = os.path.basename(self.queue.paths[row]) if 0 <= row < len(self.queue.paths) else f"row {row}"
        suffix = "" if attempt == 1 else f"  (retry {attempt - 1})"
        self.current_label.setText(f"{name}  ({row + 1}/{len(self.queue.paths)}){suffix}")
        self.phase_label.setText("Starting…")
        self.current_progress.setRange(0, 0)  # busy/indeterminate until first known total
        self.current_progress.setFormat("")
        self.eta_label.setText("ETA: —")

    def _on_item_phase(self, row: int, phase: str):
        self.phase_label.setText(phase)

    def _on_item_progress(self, row: int, done: int, total: int, eta: float):
        if total > 0:
            self.current_progress.setRange(0, total)
            self.current_progress.setValue(done)
            self.current_progress.setFormat(f"%v / %m frames (%p%)")
        else:
            self.current_progress.setRange(0, 0)
            self.current_progress.setFormat("")
        self.eta_label.setText(_format_eta(eta))

    def _on_item_finished(self, row: int, ok: bool, msg: str):
        self.queue.set_status(row, "Done" if ok else "Failed", message=msg)

    def _on_queue_finished(self):
        self._set_running(False)
        self.statusBar().showMessage("Queue finished.", 5000)
        self._reset_progress_panel()

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
