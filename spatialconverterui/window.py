import os
import shutil
import subprocess

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
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
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .queue_widget import QueueTable, VIDEO_EXTS
from .runner import PreviewRunner, QueueRunner


class PreviewDialog(QDialog):
    """Modeless window that displays the preview PNG with a Show in Finder button."""

    def __init__(self, png_path: str, parent=None):
        super().__init__(parent)
        self.png_path = png_path
        self.setWindowTitle(f"Preview — {os.path.basename(png_path)}")
        self.resize(1200, 720)

        pixmap = QPixmap(png_path)
        if pixmap.isNull():
            label = QLabel(f"Failed to load preview image:\n{png_path}")
        else:
            label = QLabel()
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignCenter)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(label)

        info = QLabel(png_path)
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.setWordWrap(True)

        show_btn = QPushButton("Show in Finder")
        show_btn.clicked.connect(self._show_in_finder)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(info, 1)
        btn_row.addWidget(show_btn)
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addLayout(btn_row)

    def _show_in_finder(self):
        try:
            subprocess.run(["open", "-R", self.png_path], check=False)
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open Finder:\n{e}")


class ClipPreviewDialog(QDialog):
    """Lightweight dialog for clip previews — just confirms the path and
    offers Open / Show in Finder. No embedded video playback."""

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.setWindowTitle("Preview Clip Ready")
        self.resize(560, 200)

        title = QLabel("Preview clip rendered with current settings:")
        path = QLabel(video_path)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(True)
        hint = QLabel(
            "Open it in your usual player (Apple Photos for spatial .mov, "
            "Moon Player for raw stereo) to evaluate."
        )
        hint.setWordWrap(True)

        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._open)
        finder_btn = QPushButton("Show in Finder")
        finder_btn.clicked.connect(self._show_in_finder)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(finder_btn)
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(path)
        layout.addStretch(1)
        layout.addWidget(hint)
        layout.addLayout(btn_row)

    def _open(self):
        try:
            subprocess.run(["open", self.video_path], check=False)
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open file:\n{e}")

    def _show_in_finder(self):
        try:
            subprocess.run(["open", "-R", self.video_path], check=False)
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open Finder:\n{e}")


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
        self.setWindowTitle("Spatial Converted")
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

        # Auto-open completed output in Finder
        self.auto_open_check = QCheckBox("Auto-open output in Finder when queue finishes")
        self.auto_open_check.setChecked(
            self.settings.value("auto_open_on_finish", True, type=bool)
        )

        # Watch folder
        self.watch_path_edit = QLineEdit(self.settings.value("watch_folder", "", type=str))
        self.watch_path_edit.setPlaceholderText("/path/to/folder to monitor")
        watch_browse_btn = QPushButton("Browse…")
        watch_browse_btn.clicked.connect(self._browse_watch_folder)
        watch_path_row = QHBoxLayout()
        watch_path_row.addWidget(self.watch_path_edit, 1)
        watch_path_row.addWidget(watch_browse_btn)

        self.watch_enabled_check = QCheckBox("Watch & auto-add new videos")
        self.watch_enabled_check.setToolTip(
            "When on, any new videos appearing in the watch folder are added to the queue. "
            "Existing videos in the folder are added once when the watch is enabled."
        )
        self.watch_enabled_check.setChecked(
            self.settings.value("watch_enabled", False, type=bool)
        )
        self.watch_enabled_check.toggled.connect(self._on_watch_toggled)

        self.watch_auto_start_check = QCheckBox("Auto-start queue when new files arrive")
        self.watch_auto_start_check.setChecked(
            self.settings.value("watch_auto_start", False, type=bool)
        )

        self.watch_archive_check = QCheckBox("Move done files to 'processed/' subfolder")
        self.watch_archive_check.setToolTip(
            "When a video sourced from the watch folder finishes successfully, "
            "move the source file into <watch folder>/processed/ so it won't be "
            "re-queued. The output files stay where they were created."
        )
        self.watch_archive_check.setChecked(
            self.settings.value("watch_archive", True, type=bool)
        )

        settings_box = QGroupBox("Conversion settings")
        form = QFormLayout(settings_box)
        form.addRow("spatialconverter path:", path_row)
        form.addRow("Max retries on failure:", self.retries_spin)
        form.addRow("Depth model:", self.model_combo)
        form.addRow("Target FPS (0 = source):", self.fps_spin)
        form.addRow("Eye shifts:", shifts_row)
        form.addRow("Output zoom:", self.zoom_spin)
        form.addRow("Stereo format:", self.stereo_format_combo)
        form.addRow("", self.auto_open_check)
        form.addRow("Watch folder:", watch_path_row)
        form.addRow("", self.watch_enabled_check)
        form.addRow("", self.watch_auto_start_check)
        form.addRow("", self.watch_archive_check)

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
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setEnabled(False)
        self.preview_btn.setToolTip(
            "Render a single frame of the selected video with the current settings — "
            "much faster than a full conversion. Useful for tuning HFOV / shifts / zoom before committing."
        )
        self.preview_btn.clicked.connect(self._start_preview)
        self.preview_clip_btn = QPushButton("Preview Clip")
        self.preview_clip_btn.setEnabled(False)
        self.preview_clip_btn.setToolTip(
            "Render a 3-second clip from the middle of the selected video. Slower than "
            "a single-frame preview but lets you evaluate motion and audio sync."
        )
        self.preview_clip_btn.clicked.connect(self._start_preview_clip)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addWidget(self.show_finder_btn)
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.preview_clip_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        # Track per-row output paths reported by the runner, and update the
        # Show in Finder button as the user changes selection.
        self._row_outputs: dict[int, str] = {}
        # runner index → queue row, populated each time a run starts so we can
        # skip Done rows without breaking signal-handler row indices.
        self._runner_to_queue: dict[int, int] = {}
        # Queue rows that produced an OUTPUT during the current run only —
        # used so auto-open reveals a fresh result, not a stale Done.
        self._this_run_processed: set[int] = set()
        self.queue.itemSelectionChanged.connect(self._update_show_finder_button)
        self.queue.rows_about_to_remove.connect(self._on_queue_rows_removing)

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
        self.preset_combo.addItem("SBS + Spatial — 50% narrower & 25% farther", "sbs_extra_narrow_far")
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
        self.preview_runner: PreviewRunner | None = None

        # Watch-folder state
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_watch_dir_changed)
        self._watch_seen: set[str] = set()
        self._watch_active_path: str = ""
        self._watch_pending_start = False
        # Apply saved watch state on launch
        if self.watch_enabled_check.isChecked() and self.watch_path_edit.text().strip():
            self._enable_watch()

    # ---- actions ----

    def _browse_path(self):
        d = QFileDialog.getExistingDirectory(self, "Choose spatialconverter directory")
        if d:
            self.path_edit.setText(d)

    def _browse_watch_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose folder to watch")
        if d:
            self.watch_path_edit.setText(d)
            self.settings.setValue("watch_folder", d)
            if self.watch_enabled_check.isChecked():
                # Re-enable to point at the new path
                self._disable_watch()
                self._enable_watch()

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
        self._this_run_processed.clear()
        self._runner_to_queue.clear()
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

        # Skip already-completed rows so re-Start doesn't re-process Done items.
        self._runner_to_queue = {}
        filtered_paths: list[str] = []
        for queue_row, video_path in enumerate(self.queue.paths):
            if self.queue.is_done(queue_row):
                continue
            self._runner_to_queue[len(filtered_paths)] = queue_row
            filtered_paths.append(video_path)

        if not filtered_paths:
            QMessageBox.information(
                self,
                "Nothing to do",
                "All queued items are already Done. Right-click a row → Duplicate to re-process.",
            )
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
        self.settings.setValue("auto_open_on_finish", self.auto_open_check.isChecked())
        self.settings.setValue("watch_folder", self.watch_path_edit.text().strip())
        self.settings.setValue("watch_enabled", self.watch_enabled_check.isChecked())
        self.settings.setValue("watch_auto_start", self.watch_auto_start_check.isChecked())
        self.settings.setValue("watch_archive", self.watch_archive_check.isChecked())

        # Only reset rows we're actually going to re-process; leave Done alone.
        self.queue.reset_statuses(skip_statuses=["Done"])
        self.log.clear()
        # Clear stale outputs only for rows we're re-running; keep Done outputs.
        for queue_row in list(self._row_outputs.keys()):
            if not self.queue.is_done(queue_row):
                self._row_outputs.pop(queue_row, None)
        self._this_run_processed.clear()
        self._update_show_finder_button()
        self._reset_progress_panel()

        self.runner = QueueRunner(
            filtered_paths,
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
        skipped = len(self.queue.paths) - len(filtered_paths)
        skipped_msg = f" ({skipped} already Done, skipped)" if skipped else ""
        self.statusBar().showMessage(
            f"Running {len(filtered_paths)} item(s)…{skipped_msg}"
        )
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
        self.watch_path_edit.setEnabled(not running)
        self.watch_enabled_check.setEnabled(not running)
        self.watch_auto_start_check.setEnabled(not running)
        self.watch_archive_check.setEnabled(not running)
        self.auto_open_check.setEnabled(not running)
        self.spatial_enabled_check.setEnabled(not running)
        # When running, also keep spatial-dependent fields disabled regardless
        # of the checkbox; when idle, restore them based on the checkbox state.
        if running:
            self.reset_iphone_btn.setEnabled(False)
        else:
            self._apply_spatial_enabled(self.spatial_enabled_check.isChecked())
        # Preview button respects the queue running state too.
        self._update_preview_button()

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
        elif key in (
            "sbs_narrow_far", "sbs_narrow_close", "sbs_wide_far", "sbs_wide_close",
            "sbs_extra_narrow_far",
        ):
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
        if key == "sbs_extra_narrow_far":
            # 50% narrower than the "narrower" preset (HFOV 50 → 25),
            # 25% farther than the "farther" preset (shift gap 20 → 15).
            self.hfov_spin.setValue(25.0)
            self.shift_left_spin.setValue(0)
            self.shift_right_spin.setValue(15)
        else:
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
            "sbs_extra_narrow_far": "50% narrower & 25% farther (HFOV 25, shifts 0/15)",
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

    def _to_queue_row(self, runner_row: int) -> int:
        """Translate a runner-side row (index into the filtered items list)
        into the corresponding queue table row. Returns -1 if no mapping
        (the row was removed from the queue mid-run)."""
        return self._runner_to_queue.get(runner_row, -1)

    def _on_queue_rows_removing(self, queue_rows: list[int]):
        """Keep our tracking dicts/sets aligned with the queue table when the
        user removes rows. queue_rows arrives in descending order so we can
        process each removal as a discrete shift-down."""
        for queue_row in queue_rows:
            # If the runner is still running and this row maps to a runner
            # index, ask the runner to skip it (and kill the in-flight
            # subprocess if it's the one currently running).
            if self.runner and self.runner.isRunning():
                runner_row = None
                for rr, qr in self._runner_to_queue.items():
                    if qr == queue_row:
                        runner_row = rr
                        break
                if runner_row is not None:
                    self.runner.request_skip(runner_row)
                    del self._runner_to_queue[runner_row]
            else:
                # No active run; just drop any stale mapping entry.
                stale = [rr for rr, qr in self._runner_to_queue.items() if qr == queue_row]
                for rr in stale:
                    del self._runner_to_queue[rr]

            # Shift remaining mapping entries down past the removed queue row.
            self._runner_to_queue = {
                rr: (qr - 1 if qr > queue_row else qr)
                for rr, qr in self._runner_to_queue.items()
            }

            # Same shift for outputs and the this-run set.
            self._row_outputs.pop(queue_row, None)
            self._row_outputs = {
                (qr - 1 if qr > queue_row else qr): path
                for qr, path in self._row_outputs.items()
            }

            shifted_processed: set[int] = set()
            for qr in self._this_run_processed:
                if qr == queue_row:
                    continue
                shifted_processed.add(qr - 1 if qr > queue_row else qr)
            self._this_run_processed = shifted_processed

        self._update_show_finder_button()

    def _on_item_started(self, runner_row: int, attempt: int):
        queue_row = self._to_queue_row(runner_row)
        if queue_row < 0:
            # Row was removed before this attempt started. The runner skips it
            # internally; no UI to update.
            return
        status = "Running" if attempt == 1 else "Retrying"
        self.queue.set_status(queue_row, status, tries=attempt)
        name = (
            os.path.basename(self.queue.paths[queue_row])
            if 0 <= queue_row < len(self.queue.paths)
            else f"row {queue_row}"
        )
        suffix = "" if attempt == 1 else f"  (retry {attempt - 1})"
        total = len(self._runner_to_queue) or len(self.queue.paths)
        self.current_label.setText(f"{name}  ({runner_row + 1}/{total}){suffix}")
        self.phase_label.setText("Starting…")
        self.current_progress.setRange(0, 0)  # busy/indeterminate until first known total
        self.current_progress.setFormat("")
        self.eta_label.setText("ETA: —")

    def _on_item_phase(self, runner_row: int, phase: str):
        self.phase_label.setText(phase)

    def _on_item_progress(self, runner_row: int, done: int, total: int, eta: float):
        if total > 0:
            self.current_progress.setRange(0, total)
            self.current_progress.setValue(done)
            self.current_progress.setFormat(f"%v / %m frames (%p%)")
        else:
            self.current_progress.setRange(0, 0)
            self.current_progress.setFormat("")
        self.eta_label.setText(_format_eta(eta))

    def _on_item_output(self, runner_row: int, path: str):
        queue_row = self._to_queue_row(runner_row)
        if queue_row < 0:
            return
        self._row_outputs[queue_row] = path
        self._this_run_processed.add(queue_row)
        self._update_show_finder_button()

    def _on_item_finished(self, runner_row: int, ok: bool, msg: str):
        queue_row = self._to_queue_row(runner_row)
        if queue_row < 0:
            # Row was removed; nothing to update in the table.
            return
        self.queue.set_status(queue_row, "Done" if ok else "Failed", message=msg)
        self._update_show_finder_button()
        if (
            ok
            and self.watch_archive_check.isChecked()
            and self._watch_active_path
        ):
            self._archive_done_source(queue_row)

    def _archive_done_source(self, queue_row: int) -> None:
        """If the source video for `queue_row` is sitting in the active watch
        folder, move it into <watch folder>/processed/ so it won't be picked
        up again. No-op for files that aren't in the watch folder."""
        if not (0 <= queue_row < len(self.queue.paths)):
            return
        src = self.queue.paths[queue_row]
        if not os.path.isfile(src):
            return
        try:
            src_dir = os.path.realpath(os.path.dirname(src))
            watch_dir = os.path.realpath(self._watch_active_path)
        except OSError:
            return
        if src_dir != watch_dir:
            return  # not from the active watch folder

        processed_dir = os.path.join(self._watch_active_path, "processed")
        try:
            os.makedirs(processed_dir, exist_ok=True)
        except OSError as e:
            self.log.appendPlainText(f"WARN: could not create {processed_dir}: {e}")
            return

        base = os.path.basename(src)
        dest = os.path.join(processed_dir, base)
        if os.path.exists(dest):
            name, ext = os.path.splitext(base)
            i = 1
            while os.path.exists(os.path.join(processed_dir, f"{name}_{i}{ext}")):
                i += 1
            dest = os.path.join(processed_dir, f"{name}_{i}{ext}")

        try:
            shutil.move(src, dest)
            self.log.appendPlainText(f"Archived source: {src} → {dest}")
        except OSError as e:
            self.log.appendPlainText(f"WARN: could not move {src} → {dest}: {e}")

    def _on_queue_finished(self):
        self._set_running(False)
        self.statusBar().showMessage("Queue finished.", 5000)
        self._reset_progress_panel()
        # Auto-open the first output produced *during this run* (not a stale
        # Done from a previous run). Falls back to nothing if no fresh outputs.
        if self.auto_open_check.isChecked() and self._this_run_processed:
            for queue_row in sorted(self._this_run_processed):
                path = self._row_outputs.get(queue_row)
                if path and os.path.exists(path):
                    try:
                        subprocess.run(["open", "-R", path], check=False)
                    except Exception:
                        pass
                    break

    # ---- Show in Finder ----

    def _selected_row(self) -> int:
        rows = sorted({i.row() for i in self.queue.selectedIndexes()})
        return rows[0] if rows else -1

    def _update_show_finder_button(self):
        row = self._selected_row()
        path = self._row_outputs.get(row)
        self.show_finder_btn.setEnabled(bool(path) and os.path.exists(path))
        self._update_preview_button()

    def _update_preview_button(self):
        row = self._selected_row()
        has_video = 0 <= row < len(self.queue.paths)
        preview_running = bool(self.preview_runner and self.preview_runner.isRunning())
        queue_running = bool(self.runner and self.runner.isRunning())
        enabled = has_video and not preview_running and not queue_running
        self.preview_btn.setEnabled(enabled)
        self.preview_clip_btn.setEnabled(enabled)

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

    # ---- Watch folder ----

    def _on_watch_toggled(self, checked: bool):
        self.settings.setValue("watch_enabled", checked)
        if checked:
            self._enable_watch()
        else:
            self._disable_watch()

    def _enable_watch(self):
        folder = self.watch_path_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            self.statusBar().showMessage(
                "Watch folder is not a valid directory; not watching.", 4000
            )
            self.watch_enabled_check.setChecked(False)
            return
        if self._watch_active_path:
            self._disable_watch()
        self._watch_active_path = folder
        self._fs_watcher.addPath(folder)
        # Initial scan: add any existing video files.
        self._scan_watch_folder(folder, include_existing=True)
        self.statusBar().showMessage(f"Watching {folder}", 4000)

    def _disable_watch(self):
        if self._watch_active_path:
            self._fs_watcher.removePath(self._watch_active_path)
            self._watch_active_path = ""
        self._watch_seen.clear()

    def _on_watch_dir_changed(self, path: str):
        self._scan_watch_folder(path, include_existing=False)

    def _scan_watch_folder(self, folder: str, include_existing: bool):
        try:
            entries = os.listdir(folder)
        except OSError:
            return
        new_videos: list[str] = []
        for name in entries:
            full = os.path.join(folder, name)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in VIDEO_EXTS:
                continue
            if full in self._watch_seen:
                continue
            if full in self.queue.paths:
                self._watch_seen.add(full)
                continue
            if not include_existing and full not in self._watch_seen:
                pass  # treat as new — fall through and add
            new_videos.append(full)

        for v in sorted(new_videos):
            self.queue.add_file(v)
            self._watch_seen.add(v)

        if new_videos:
            self.statusBar().showMessage(
                f"Watch folder: added {len(new_videos)} file(s) to queue.", 4000
            )
            self._update_show_finder_button()  # refresh preview-button enable state
            if self.watch_auto_start_check.isChecked():
                # Debounce: schedule one auto-start in 2s. If files keep arriving,
                # the run condition is re-checked when the timer fires.
                if not self._watch_pending_start:
                    self._watch_pending_start = True
                    QTimer.singleShot(2000, self._maybe_auto_start)

    def _maybe_auto_start(self):
        self._watch_pending_start = False
        if (
            self.watch_auto_start_check.isChecked()
            and self.queue.paths
            and not (self.runner and self.runner.isRunning())
            and not (self.preview_runner and self.preview_runner.isRunning())
        ):
            self._start()

    # ---- Preview ----

    def _start_preview(self):
        self._launch_preview(clip_mode=False)

    def _start_preview_clip(self):
        self._launch_preview(clip_mode=True)

    def _launch_preview(self, clip_mode: bool):
        if self.preview_runner and self.preview_runner.isRunning():
            return
        row = self._selected_row()
        if row < 0 or row >= len(self.queue.paths):
            return
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Missing path", "Set the spatialconverter path first.")
            return

        video = self.queue.paths[row]
        kind = "clip" if clip_mode else "frame"
        self.statusBar().showMessage(f"Rendering {kind} preview for {os.path.basename(video)}…")
        self.log.appendPlainText(f"--- Preview ({kind}): {video} ---")

        self.preview_runner = PreviewRunner(
            video_path=video,
            converter_path=path,
            model_size=self.model_combo.currentData(),
            target_fps=float(self.fps_spin.value()),
            shift_left=int(self.shift_left_spin.value()),
            shift_right=int(self.shift_right_spin.value()),
            hfov=float(self.hfov_spin.value()),
            cdist=float(self.cdist_spin.value()),
            hadjust=float(self.hadjust_spin.value()),
            projection=self.projection_combo.currentText().strip() or "rect",
            spatial_extra=self.spatial_extra_edit.text(),
            zoom=float(self.zoom_spin.value()),
            stereo_format=self.stereo_format_combo.currentData() or "ou",
            spatial_enabled=self.spatial_enabled_check.isChecked(),
            clip_mode=clip_mode,
            clip_duration=3.0,
        )
        self.preview_runner.log_line.connect(self.log.appendPlainText)
        self.preview_runner.finished_ok.connect(self._on_preview_ok)
        self.preview_runner.finished_err.connect(self._on_preview_err)
        self.preview_runner.finished.connect(self._update_preview_button)
        self._update_preview_button()
        self.preview_runner.start()

    def _on_preview_ok(self, output_path: str):
        self.statusBar().showMessage(f"Preview ready: {output_path}", 5000)
        # Dispatch by extension: .png → image dialog, video → clip dialog
        if output_path.lower().endswith(".png"):
            dlg = PreviewDialog(output_path, parent=self)
        else:
            dlg = ClipPreviewDialog(output_path, parent=self)
        dlg.show()

    def _on_preview_err(self, msg: str):
        self.statusBar().showMessage(f"Preview failed: {msg}", 5000)
        QMessageBox.warning(self, "Preview failed", msg)

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
