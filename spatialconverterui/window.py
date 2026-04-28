import os
import subprocess

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
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

        self.zoom_spin = QDoubleSpinBox()
        self.zoom_spin.setRange(0.1, 4.0)
        self.zoom_spin.setDecimals(2)
        self.zoom_spin.setSingleStep(0.05)
        self.zoom_spin.setSuffix("×")
        self.zoom_spin.setToolTip(
            "Pre-process zoom: >1.0 crops in (zoom in), <1.0 letterboxes (zoom out), 1.0 unchanged"
        )
        self.zoom_spin.setValue(float(self.settings.value("zoom", 1.0)))

        self.stereo_format_combo = QComboBox()
        self.stereo_format_combo.addItem("Over-Under (top / bottom)", "ou")
        self.stereo_format_combo.addItem("Side-by-Side (left / right)", "sbs")
        saved_fmt = self.settings.value("stereo_format", "ou", type=str)
        idx_fmt = self.stereo_format_combo.findData(saved_fmt)
        self.stereo_format_combo.setCurrentIndex(idx_fmt if idx_fmt >= 0 else 0)

        settings_box = QGroupBox("Conversion settings")
        form = QFormLayout(settings_box)
        form.addRow("spatialconverter path:", path_row)
        form.addRow("Max retries on failure:", self.retries_spin)
        form.addRow("Depth model:", self.model_combo)
        form.addRow("Target FPS (0 = source):", self.fps_spin)
        form.addRow("Eye shifts:", shifts_row)
        form.addRow("Output zoom:", self.zoom_spin)
        form.addRow("Stereo format:", self.stereo_format_combo)

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
        for value in ("rect", "fisheye", "equirect"):
            self.projection_combo.addItem(value)
        self.projection_combo.setCurrentText(
            self.settings.value("projection", "rect", type=str)
        )

        self.spatial_extra_edit = QLineEdit(
            self.settings.value("spatial_extra", "", type=str)
        )
        self.spatial_extra_edit.setPlaceholderText('e.g. --primary right')

        self.reset_iphone_btn = QPushButton("Reset to iPhone 15 Pro")
        self.reset_iphone_btn.setToolTip(
            "Restore HFOV / camera distance / horizontal adjust / projection / extra args "
            "to the iPhone 15 Pro native spatial recording values "
            "(63.4° / 19.24 mm / 0.02 / rect)."
        )
        self.reset_iphone_btn.clicked.connect(self._reset_to_iphone_defaults)

        self.spatial_enabled_check = QCheckBox("Generate Apple spatial output (.mov)")
        self.spatial_enabled_check.setToolTip(
            "When off, the pipeline stops after producing the raw stereo file "
            "(over_under.mp4 with OU or SBS layout) and skips ./spatial tagging. "
            "Use this when targeting Moon Player or other non-Apple-spatial workflows."
        )
        self.spatial_enabled_check.setChecked(
            self.settings.value("spatial_enabled", True, type=bool)
        )
        self.spatial_enabled_check.toggled.connect(self._on_spatial_toggled)

        spatial_box = QGroupBox("Spatial output (./spatial flags)")
        spatial_form = QFormLayout(spatial_box)
        spatial_form.addRow(self.spatial_enabled_check)
        spatial_form.addRow("Horizontal FOV:", self.hfov_spin)
        spatial_form.addRow("Camera distance:", self.cdist_spin)
        spatial_form.addRow("Horizontal adjust:", self.hadjust_spin)
        spatial_form.addRow("Projection:", self.projection_combo)
        spatial_form.addRow("Extra args:", self.spatial_extra_edit)
        spatial_form.addRow("", self.reset_iphone_btn)
        # Apply current toggle state to dependent widgets right after construction.
        self._apply_spatial_enabled(self.spatial_enabled_check.isChecked())

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
        self.show_finder_btn = QPushButton("Show in Finder")
        self.show_finder_btn.setEnabled(False)
        self.show_finder_btn.setToolTip("Reveal the selected item's output file in Finder")
        self.show_finder_btn.clicked.connect(self._show_in_finder)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addWidget(self.show_finder_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        # Track per-row output paths reported by the runner, and update the
        # Show in Finder button as the user changes selection.
        self._row_outputs: dict[int, str] = {}
        self.queue.itemSelectionChanged.connect(self._update_show_finder_button)

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

        # ---- preset combo (applies a bundle of settings at once) ----
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("— Choose a preset —", None)
        self.preset_combo.addItem("iPhone 15 Pro (full spatial reset)", "iphone")
        self.preset_combo.addItem("Widescreen lens (90° HFOV)", "widescreen")
        self.preset_combo.addItem("Action camera (120° HFOV, rect)", "action_cam")
        self.preset_combo.addItem("Fisheye / panoramic (170° HFOV, fisheye)", "fisheye")
        self.preset_combo.addItem("Fast preview (Small model, 24 fps)", "fast_preview")
        self.preset_combo.addItem("Stronger 3D (shifts 0 / 100)", "strong_3d")
        self.preset_combo.addItem("VR side-by-side stereo (90° HFOV, SBS)", "vr_sbs")
        self.preset_combo.insertSeparator(self.preset_combo.count())
        self.preset_combo.addItem("SBS + Spatial — narrower & farther", "sbs_narrow_far")
        self.preset_combo.addItem("SBS + Spatial — narrower & closer", "sbs_narrow_close")
        self.preset_combo.addItem("SBS + Spatial — wider & farther", "sbs_wide_far")
        self.preset_combo.addItem("SBS + Spatial — wider & closer", "sbs_wide_close")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)

        preset_row = QHBoxLayout()
        preset_label = QLabel("Preset:")
        preset_row.addWidget(preset_label)
        preset_row.addWidget(self.preset_combo, 1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(preset_row)
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
        self._row_outputs.clear()
        self._update_show_finder_button()

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
        zoom = float(self.zoom_spin.value())
        stereo_format = self.stereo_format_combo.currentData() or "ou"
        spatial_enabled = self.spatial_enabled_check.isChecked()

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
        self.settings.setValue("zoom", zoom)
        self.settings.setValue("stereo_format", stereo_format)
        self.settings.setValue("spatial_enabled", spatial_enabled)

        self.queue.reset_statuses()
        self.log.clear()
        self._row_outputs.clear()
        self._update_show_finder_button()
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
            zoom=zoom,
            stereo_format=stereo_format,
            spatial_enabled=spatial_enabled,
        )
        self.runner.item_started.connect(self._on_item_started)
        self.runner.item_finished.connect(self._on_item_finished)
        self.runner.item_phase.connect(self._on_item_phase)
        self.runner.item_progress.connect(self._on_item_progress)
        self.runner.item_output.connect(self._on_item_output)
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
        self.zoom_spin.setEnabled(not running)
        self.stereo_format_combo.setEnabled(not running)
        self.preset_combo.setEnabled(not running)
        self.spatial_enabled_check.setEnabled(not running)
        # When running, also keep spatial-dependent fields disabled regardless
        # of the checkbox; when idle, restore them based on the checkbox state.
        if running:
            self.reset_iphone_btn.setEnabled(False)
        else:
            self._apply_spatial_enabled(self.spatial_enabled_check.isChecked())

    def _on_spatial_toggled(self, checked: bool):
        self._apply_spatial_enabled(checked)
        self.statusBar().showMessage(
            "Spatial output enabled."
            if checked
            else "Spatial output disabled — pipeline will stop at raw stereo file.",
            3000,
        )

    def _apply_spatial_enabled(self, enabled: bool):
        """Enable/disable the spatial-only fields based on the master checkbox."""
        self.hfov_spin.setEnabled(enabled)
        self.cdist_spin.setEnabled(enabled)
        self.hadjust_spin.setEnabled(enabled)
        self.projection_combo.setEnabled(enabled)
        self.spatial_extra_edit.setEnabled(enabled)
        self.reset_iphone_btn.setEnabled(enabled)

    def _reset_to_iphone_defaults(self):
        """Restore iPhone 15 Pro native spatial recording values."""
        self.hfov_spin.setValue(63.4)
        self.cdist_spin.setValue(19.24)
        self.hadjust_spin.setValue(0.02)
        self.projection_combo.setCurrentText("rect")
        self.spatial_extra_edit.setText("")
        self.statusBar().showMessage("Spatial output reset to iPhone 15 Pro defaults.", 3000)

    def _on_preset_selected(self, idx: int):
        key = self.preset_combo.itemData(idx)
        if not key:
            return
        self._apply_preset(key)
        # Reset combo back to placeholder without re-firing the handler
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _apply_preset(self, key: str):
        """Apply a named bundle of settings. Each preset only touches the
        fields relevant to its name; everything else is left as-is."""
        msg = ""
        if key == "iphone":
            self.hfov_spin.setValue(63.4)
            self.cdist_spin.setValue(19.24)
            self.hadjust_spin.setValue(0.02)
            self.projection_combo.setCurrentText("rect")
            self.spatial_extra_edit.setText("")
            msg = "iPhone 15 Pro defaults applied."
        elif key == "widescreen":
            self.hfov_spin.setValue(90.0)
            self.projection_combo.setCurrentText("rect")
            msg = "Widescreen 90° HFOV applied."
        elif key == "action_cam":
            self.hfov_spin.setValue(120.0)
            self.projection_combo.setCurrentText("rect")
            msg = "Action-cam 120° HFOV applied."
        elif key == "fisheye":
            self.hfov_spin.setValue(170.0)
            self.projection_combo.setCurrentText("fisheye")
            msg = "Fisheye 170° applied."
        elif key == "fast_preview":
            i = self.model_combo.findData("small")
            if i >= 0:
                self.model_combo.setCurrentIndex(i)
            self.fps_spin.setValue(24.0)
            msg = "Fast preview (Small model, 24 fps) applied."
        elif key == "strong_3d":
            self.shift_left_spin.setValue(0)
            self.shift_right_spin.setValue(100)
            msg = "Stronger 3D shifts (0 / 100) applied."
        elif key == "vr_sbs":
            self.hfov_spin.setValue(90.0)
            self.projection_combo.setCurrentText("equirect")
            i = self.stereo_format_combo.findData("sbs")
            if i >= 0:
                self.stereo_format_combo.setCurrentIndex(i)
            msg = "VR SBS (90° HFOV, equirect, SBS) applied."
        elif key in ("sbs_narrow_far", "sbs_narrow_close", "sbs_wide_far", "sbs_wide_close"):
            self._apply_sbs_spatial_preset(key)
            msg = ""  # _apply_sbs_spatial_preset handles its own status message
        if msg:
            self.statusBar().showMessage(f"Preset: {msg}", 3000)

    def _apply_sbs_spatial_preset(self, key: str):
        """SBS + Spatial bundles: 2×2 of {narrower, wider} × {farther, closer}.

        Narrower/wider → HFOV (50 or 110). Farther/closer → eye-shift gap
        (0/20 = recessed, 0/80 = pops out). All four also set
        stereo_format=SBS, projection=equirect, and force spatial output ON
        so the resulting .mov carries the metadata VR-aware players need.
        """
        if key.startswith("sbs_narrow"):
            self.hfov_spin.setValue(50.0)
        else:
            self.hfov_spin.setValue(110.0)

        if key.endswith("_far"):
            self.shift_left_spin.setValue(0)
            self.shift_right_spin.setValue(20)
        else:
            self.shift_left_spin.setValue(0)
            self.shift_right_spin.setValue(80)

        self.projection_combo.setCurrentText("equirect")
        i = self.stereo_format_combo.findData("sbs")
        if i >= 0:
            self.stereo_format_combo.setCurrentIndex(i)
        self.spatial_enabled_check.setChecked(True)

        labels = {
            "sbs_narrow_far": "narrower & farther (HFOV 50, shifts 0/20)",
            "sbs_narrow_close": "narrower & closer (HFOV 50, shifts 0/80)",
            "sbs_wide_far": "wider & farther (HFOV 110, shifts 0/20)",
            "sbs_wide_close": "wider & closer (HFOV 110, shifts 0/80)",
        }
        self.statusBar().showMessage(
            f"Preset: SBS + Spatial — {labels[key]} applied.", 4000
        )

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

    def _on_item_output(self, row: int, path: str):
        self._row_outputs[row] = path
        self._update_show_finder_button()

    def _on_item_finished(self, row: int, ok: bool, msg: str):
        self.queue.set_status(row, "Done" if ok else "Failed", message=msg)
        self._update_show_finder_button()

    def _on_queue_finished(self):
        self._set_running(False)
        self.statusBar().showMessage("Queue finished.", 5000)
        self._reset_progress_panel()

    # ---- Show in Finder ----

    def _selected_row(self) -> int:
        rows = sorted({i.row() for i in self.queue.selectedIndexes()})
        return rows[0] if rows else -1

    def _update_show_finder_button(self):
        row = self._selected_row()
        path = self._row_outputs.get(row)
        self.show_finder_btn.setEnabled(bool(path) and os.path.exists(path))

    def _show_in_finder(self):
        row = self._selected_row()
        path = self._row_outputs.get(row)
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "File missing", f"Expected file no longer exists:\n{path}"
            )
            return
        # macOS: `open -R <path>` reveals and selects the file in Finder.
        try:
            subprocess.run(["open", "-R", path], check=False)
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open Finder:\n{e}")

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
