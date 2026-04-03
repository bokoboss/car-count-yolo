from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import config
from .detection import detect_vehicles, normalize_settings
from .exporter import export_results_file
from .tracking import (
    DIRECTION_NEGATIVE_TO_POSITIVE,
    DIRECTION_POSITIVE_TO_NEGATIVE,
    track_vehicles,
)
from .utils import draw_line_overlay, frame_to_pixmap, load_video, read_first_frame


class PreviewLabel(QLabel):
    def __init__(self, click_handler, parent=None):
        super().__init__(parent)
        self.click_handler = click_handler

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.click_handler:
            self.click_handler(event)
        super().mousePressEvent(event)


class CountingWorker(QObject):
    progress = pyqtSignal(int, int, object, object)
    finished = pyqtSignal(object, object, object)

    def __init__(self, video_path, line_points, settings):
        super().__init__()
        self.video_path = video_path
        self.line_points = line_points
        self.settings = settings
        self.stop_requested = False

    @pyqtSlot()
    def run(self):
        latest_frame, results, error_message = track_vehicles(
            video_path=self.video_path,
            line_points=self.line_points,
            settings=self.settings,
            progress_callback=self.emit_progress,
            should_cancel=self.is_stop_requested,
        )
        self.finished.emit(latest_frame, results, error_message)

    def emit_progress(self, processed_frames, total_frames, latest_frame, counts_snapshot):
        self.progress.emit(processed_frames, total_frames, latest_frame, counts_snapshot)

    def request_stop(self):
        self.stop_requested = True

    def is_stop_requested(self):
        return self.stop_requested


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.preview_frame = None
        self.detected_preview_frame = None
        self.selected_video_path = None
        self.count_results = None
        self.count_settings = None
        self.is_counting = False
        self.stop_requested = False
        self.counting_thread = None
        self.counting_worker = None
        self.draw_mode_enabled = False
        self.pending_line_start = None
        self.count_line = None
        self.direction_labels = self.default_direction_labels()
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setGeometry(100, 100, config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        button_layout = QHBoxLayout()

        self.open_video_btn = QPushButton("Open Video")
        self.open_video_btn.clicked.connect(self.open_video)
        button_layout.addWidget(self.open_video_btn)

        self.draw_line_btn = QPushButton("Draw Count Line")
        self.draw_line_btn.clicked.connect(self.draw_count_line)
        button_layout.addWidget(self.draw_line_btn)

        self.clear_line_btn = QPushButton("Clear Count Line")
        self.clear_line_btn.clicked.connect(self.clear_count_line)
        button_layout.addWidget(self.clear_line_btn)

        self.direction_labels_btn = QPushButton("Set Direction Labels")
        self.direction_labels_btn.clicked.connect(self.set_direction_labels)
        button_layout.addWidget(self.direction_labels_btn)

        self.detect_btn = QPushButton("Detect Vehicles")
        self.detect_btn.clicked.connect(self.detect_current_preview)
        button_layout.addWidget(self.detect_btn)

        self.start_counting_btn = QPushButton("Start Counting")
        self.start_counting_btn.clicked.connect(self.start_counting)
        button_layout.addWidget(self.start_counting_btn)

        self.stop_counting_btn = QPushButton("Stop Counting")
        self.stop_counting_btn.clicked.connect(self.stop_counting)
        self.stop_counting_btn.setEnabled(False)
        button_layout.addWidget(self.stop_counting_btn)

        self.export_results_btn = QPushButton("Export Results")
        self.export_results_btn.clicked.connect(self.export_results)
        self.export_results_btn.setEnabled(False)
        button_layout.addWidget(self.export_results_btn)

        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.build_settings_group())

        self.preview_label = PreviewLabel(self.handle_preview_click)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "border: 1px solid black; background-color: lightgray;"
        )
        self.preview_label.setMinimumHeight(300)
        self.preview_label.setScaledContents(False)
        main_layout.addWidget(self.preview_label)

        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(100)
        self.status_text.setPlainText(
            "Welcome to Vehicle Counter! Select a video to begin."
        )
        main_layout.addWidget(self.status_text)

    def build_settings_group(self):
        settings_group = QGroupBox("Settings")
        settings_layout = QFormLayout(settings_group)

        self.confidence_spinbox = QDoubleSpinBox()
        self.confidence_spinbox.setRange(0.0, 1.0)
        self.confidence_spinbox.setDecimals(2)
        self.confidence_spinbox.setSingleStep(0.05)
        self.confidence_spinbox.setValue(config.DEFAULT_CONFIDENCE_THRESHOLD)
        settings_layout.addRow("Confidence Threshold", self.confidence_spinbox)

        self.frame_skip_spinbox = QSpinBox()
        self.frame_skip_spinbox.setRange(1, 30)
        self.frame_skip_spinbox.setValue(config.DEFAULT_FRAME_SKIP)
        self.frame_skip_spinbox.setToolTip("Higher values are faster, but may reduce accuracy.")
        settings_layout.addRow("Frame Skip", self.frame_skip_spinbox)

        self.model_size_combobox = QComboBox()
        self.model_size_combobox.addItems(config.MODEL_SIZE_OPTIONS)
        self.model_size_combobox.setCurrentText(config.DEFAULT_MODEL_SIZE)
        settings_layout.addRow("Model Size", self.model_size_combobox)

        class_filter_widget = QWidget()
        class_filter_layout = QHBoxLayout(class_filter_widget)
        class_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.class_checkboxes = {}
        for class_name in config.DEFAULT_ENABLED_CLASSES:
            checkbox = QCheckBox(class_name.title())
            checkbox.setChecked(True)
            self.class_checkboxes[class_name] = checkbox
            class_filter_layout.addWidget(checkbox)
        settings_layout.addRow("Class Filter", class_filter_widget)

        return settings_group

    def open_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv)",
        )

        if not file_path:
            self.set_status("No file selected.\nVideo selection was cancelled.")
            return

        capture, error_message = load_video(file_path)
        file_name = Path(file_path).name

        if error_message:
            self.clear_preview()
            self.set_status(f"Selected file: {file_name}\nStatus: {error_message}")
            return

        try:
            frame, error_message = read_first_frame(capture)
        finally:
            capture.release()

        if error_message:
            self.clear_preview()
            self.set_status(f"Selected file: {file_name}\nStatus: {error_message}")
            return

        self.preview_frame = frame
        self.detected_preview_frame = None
        self.selected_video_path = file_path
        self.count_results = None
        self.count_settings = None
        self.reset_line_state(clear_saved_line=True)
        self.direction_labels = self.default_direction_labels()
        self.update_preview()
        self.update_export_ui_state()
        self.set_status(
            f"Selected file: {file_name}\nStatus: Video loaded successfully."
        )

    def draw_count_line(self):
        if self.preview_frame is None:
            self.set_status(
                "Status: Load a video first before drawing a count line."
            )
            return

        self.count_line = None
        self.pending_line_start = None
        self.draw_mode_enabled = True
        self.update_preview()
        self.set_status(
            "Status: Draw mode enabled.\nClick the preview to choose the first point."
        )

    def detect_current_preview(self):
        if self.preview_frame is None:
            self.set_status("Status: Load a video first before running detection.")
            return

        self.set_status("Status: Running vehicle detection on the current preview...")
        settings = self.get_active_settings()
        if not settings:
            return

        detected_frame, summary, error_message = detect_vehicles(
            self.preview_frame,
            settings=settings,
        )

        if error_message:
            self.detected_preview_frame = None
            self.update_preview()
            self.set_status(f"Status: {error_message}")
            return

        self.detected_preview_frame = detected_frame
        self.update_preview()
        self.set_status(self.format_detection_status(summary))

    def start_counting(self):
        if not self.selected_video_path or self.preview_frame is None:
            self.set_status("Status: Load a video first before starting counting.")
            return

        if self.count_line is None:
            self.set_status("Status: Draw a count line before starting counting.")
            return

        self.count_results = None
        settings = self.get_active_settings()
        if not settings:
            return

        self.count_settings = settings
        self.set_status("Status: Processing started.\nReading video and tracking vehicles...")
        self.is_counting = True
        self.stop_requested = False
        self.update_counting_ui_state()
        self.start_counting_worker(settings)

    def export_results(self):
        if not self.count_results:
            self.set_status("Status: No counting results are available to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "",
            "CSV Files (*.csv);;Excel Files (*.xlsx)",
        )

        if not file_path:
            self.set_status("Status: Export cancelled.")
            return

        try:
            error_message = export_results_file(
                file_path=file_path,
                results=self.count_results,
                source_video_path=self.selected_video_path,
                direction_labels=self.direction_labels,
                settings=self.get_export_settings(),
            )
        except Exception as exc:
            self.set_status(f"Status: Export failed. {exc}")
            return

        if error_message:
            self.set_status(f"Status: {error_message}")
            return

        self.set_status(
            f"Status: Results exported successfully.\nSaved file: {Path(file_path).name}"
        )

    def stop_counting(self):
        if not self.is_counting:
            return

        self.stop_requested = True
        if self.counting_worker is not None:
            self.counting_worker.request_stop()
        self.set_status(
            "Status: Stop requested.\nThe app will stop after the current processing step."
        )

    def clear_count_line(self):
        if self.count_line is None and self.pending_line_start is None:
            self.set_status("Status: There is no count line to clear.")
            return

        self.reset_line_state(clear_saved_line=True)
        self.update_preview()
        self.set_status("Status: Count line cleared.")

    def set_direction_labels(self):
        first_label, ok = QInputDialog.getText(
            self,
            "Direction A Label",
            "Label for the first crossing direction:",
            text=self.direction_labels[DIRECTION_NEGATIVE_TO_POSITIVE],
        )
        if not ok:
            self.set_status("Status: Direction label update cancelled.")
            return

        second_label, ok = QInputDialog.getText(
            self,
            "Direction B Label",
            "Label for the second crossing direction:",
            text=self.direction_labels[DIRECTION_POSITIVE_TO_NEGATIVE],
        )
        if not ok:
            self.set_status("Status: Direction label update cancelled.")
            return

        self.direction_labels = {
            DIRECTION_NEGATIVE_TO_POSITIVE: first_label.strip() or "Direction A",
            DIRECTION_POSITIVE_TO_NEGATIVE: second_label.strip() or "Direction B",
        }
        self.set_status(
            "Status: Direction labels updated.\n"
            f"{self.format_direction_label_summary()}"
        )

    def set_status(self, message):
        self.status_text.setPlainText(message)

    def clear_preview(self):
        self.reset_line_state(clear_saved_line=True)
        self.preview_frame = None
        self.detected_preview_frame = None
        self.selected_video_path = None
        self.count_results = None
        self.count_settings = None
        self.is_counting = False
        self.stop_requested = False
        self.cleanup_counting_thread()
        self.update_counting_ui_state()
        self.update_export_ui_state()
        self.preview_label.clear()
        self.preview_label.setText("Preview Area - Video will appear here")

    def update_preview(self):
        current_frame = self.get_current_preview_frame()
        if current_frame is None:
            return

        display_pixmap = frame_to_pixmap(current_frame)
        if self.count_line is not None:
            display_pixmap = draw_line_overlay(
                display_pixmap,
                self.count_line[0],
                self.count_line[1],
            )
        elif self.pending_line_start is not None:
            display_pixmap = draw_line_overlay(
                display_pixmap,
                self.pending_line_start,
                self.pending_line_start,
            )

        scaled_pixmap = display_pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if isinstance(self.preview_label.pixmap(), QPixmap):
            self.update_preview()

    def handle_preview_click(self, event):
        if not self.draw_mode_enabled or self.preview_frame is None:
            return

        image_point = self.map_click_to_image(event)
        if image_point is None:
            return

        if self.pending_line_start is None:
            self.pending_line_start = image_point
            self.update_preview()
            self.set_status(
                "Status: First point selected.\nClick the preview again to finish the count line."
            )
            return

        self.count_line = (self.pending_line_start, image_point)
        self.pending_line_start = None
        self.draw_mode_enabled = False
        self.update_preview()
        self.set_status(
            "Status: Count line completed.\nStored coordinates: "
            f"({self.count_line[0].x()}, {self.count_line[0].y()}) -> "
            f"({self.count_line[1].x()}, {self.count_line[1].y()})\n"
            f"Direction labels: {self.format_direction_label_summary()}"
        )

    def map_click_to_image(self, event):
        displayed_rect = self.get_displayed_pixmap_rect()
        if displayed_rect is None or not displayed_rect.contains(event.position().toPoint()):
            return None

        click_point = event.position().toPoint()
        relative_x = click_point.x() - displayed_rect.x()
        relative_y = click_point.y() - displayed_rect.y()

        image_size = self.get_preview_image_size()
        if image_size is None:
            return None

        image_width, image_height = image_size
        displayed_width = displayed_rect.width()
        displayed_height = displayed_rect.height()

        image_x = round(relative_x * image_width / displayed_width)
        image_y = round(relative_y * image_height / displayed_height)

        image_x = max(0, min(image_x, image_width - 1))
        image_y = max(0, min(image_y, image_height - 1))
        return QPoint(image_x, image_y)

    def get_displayed_pixmap_rect(self):
        pixmap = self.preview_label.pixmap()
        if pixmap is None:
            return None

        label_rect = self.preview_label.contentsRect()
        x = label_rect.x() + (label_rect.width() - pixmap.width()) // 2
        y = label_rect.y() + (label_rect.height() - pixmap.height()) // 2
        return QRect(x, y, pixmap.width(), pixmap.height())

    def reset_line_state(self, clear_saved_line):
        self.draw_mode_enabled = False
        self.pending_line_start = None
        if clear_saved_line:
            self.count_line = None

    def get_current_preview_frame(self):
        if self.detected_preview_frame is not None:
            return self.detected_preview_frame
        return self.preview_frame

    def get_preview_image_size(self):
        current_frame = self.get_current_preview_frame()
        if current_frame is None:
            return None
        return current_frame.shape[1], current_frame.shape[0]

    def format_detection_status(self, summary):
        total_detected = summary["total"]
        counts_by_class = summary["counts"]

        if counts_by_class:
            counts_text = ", ".join(
                f"{class_name}: {count}"
                for class_name, count in sorted(counts_by_class.items())
            )
        else:
            counts_text = "None"

        return (
            "Status: Detection completed.\n"
            f"Total detected objects: {total_detected}\n"
            f"Counts by class: {counts_text}"
        )

    def update_processing_progress(
        self,
        processed_frames,
        total_frames,
        latest_frame,
        counts_snapshot,
    ):
        self.detected_preview_frame = latest_frame
        self.count_results = counts_snapshot
        self.update_preview()

        counts_text = self.format_counts_by_class(counts_snapshot["counts"])
        direction_text = self.format_direction_counts(counts_snapshot["direction_counts"])

        if total_frames:
            self.set_status(
                "Status: Processing video...\n"
                f"Progress: {processed_frames}/{total_frames} frames\n"
                f"Current total crossings: {counts_snapshot['total']}\n"
                f"Current counts by class: {counts_text}\n"
                f"Current direction counts: {direction_text}"
            )
        else:
            self.set_status(
                "Status: Processing video...\n"
                f"Frames processed: {processed_frames}\n"
                f"Current total crossings: {counts_snapshot['total']}\n"
                f"Current counts by class: {counts_text}\n"
                f"Current direction counts: {direction_text}"
            )

        self.update_export_ui_state()

    def format_counting_status(self, results):
        counts_text = self.format_counts_by_class(results["counts"])
        direction_text = self.format_direction_counts(results["direction_counts"])

        return (
            "Status: Processing completed.\n"
            f"Frames processed: {results['processed_frames']}\n"
            f"Total crossings: {results['total']}\n"
            f"Counts by class: {counts_text}\n"
            f"Direction counts: {direction_text}"
        )

    def format_cancelled_counting_status(self, results):
        if results is None:
            return "Status: Counting stopped by user."

        counts_text = self.format_counts_by_class(results["counts"])
        direction_text = self.format_direction_counts(results["direction_counts"])

        return (
            "Status: Counting stopped by user.\n"
            f"Partial frames processed: {results['processed_frames']}\n"
            f"Partial total crossings: {results['total']}\n"
            f"Partial counts by class: {counts_text}\n"
            f"Partial direction counts: {direction_text}"
        )

    def update_counting_ui_state(self):
        self.start_counting_btn.setEnabled(not self.is_counting)
        self.stop_counting_btn.setEnabled(self.is_counting)
        self.open_video_btn.setEnabled(not self.is_counting)
        self.draw_line_btn.setEnabled(not self.is_counting)
        self.clear_line_btn.setEnabled(not self.is_counting)
        self.direction_labels_btn.setEnabled(not self.is_counting)
        self.detect_btn.setEnabled(not self.is_counting)
        self.confidence_spinbox.setEnabled(not self.is_counting)
        self.frame_skip_spinbox.setEnabled(not self.is_counting)
        self.model_size_combobox.setEnabled(not self.is_counting)
        for checkbox in self.class_checkboxes.values():
            checkbox.setEnabled(not self.is_counting)
        self.update_export_ui_state()

    def is_stop_requested(self):
        return self.stop_requested

    def start_counting_worker(self, settings):
        self.counting_thread = QThread(self)
        self.counting_worker = CountingWorker(
            video_path=self.selected_video_path,
            line_points=self.count_line,
            settings=settings,
        )
        self.counting_worker.moveToThread(self.counting_thread)

        self.counting_thread.started.connect(self.counting_worker.run)
        self.counting_worker.progress.connect(self.update_processing_progress)
        self.counting_worker.finished.connect(self.handle_counting_finished)
        self.counting_worker.finished.connect(self.counting_thread.quit)
        self.counting_thread.finished.connect(self.counting_worker.deleteLater)
        self.counting_thread.finished.connect(self.handle_thread_finished)

        self.counting_thread.start()

    def handle_counting_finished(self, latest_frame, results, error_message):
        self.is_counting = False
        self.stop_requested = False
        self.update_counting_ui_state()

        if error_message == "cancelled":
            if latest_frame is not None:
                self.detected_preview_frame = latest_frame
                self.update_preview()
            self.count_results = results
            self.update_export_ui_state()
            self.set_status(self.format_cancelled_counting_status(results))
            return

        if error_message:
            self.update_export_ui_state()
            self.set_status(f"Status: {error_message}")
            return

        self.detected_preview_frame = latest_frame
        self.count_results = results
        self.update_preview()
        self.update_export_ui_state()
        self.set_status(self.format_counting_status(results))

    def handle_thread_finished(self):
        self.cleanup_counting_thread()

    def cleanup_counting_thread(self):
        if self.counting_thread is not None:
            self.counting_thread.deleteLater()
            self.counting_thread = None
        self.counting_worker = None

    def update_export_ui_state(self):
        has_results = self.count_results is not None
        self.export_results_btn.setEnabled(has_results and not self.is_counting)

    def format_direction_counts(self, direction_counts):
        direction_labels = {
            DIRECTION_NEGATIVE_TO_POSITIVE: self.direction_labels[
                DIRECTION_NEGATIVE_TO_POSITIVE
            ],
            DIRECTION_POSITIVE_TO_NEGATIVE: self.direction_labels[
                DIRECTION_POSITIVE_TO_NEGATIVE
            ],
        }

        parts = []
        for direction_key, direction_label in direction_labels.items():
            counts_text = ", ".join(
                f"{class_name}: {count}"
                for class_name, count in direction_counts[direction_key].items()
                if count > 0
            )
            if not counts_text:
                counts_text = "None"
            parts.append(f"{direction_label} [{counts_text}]")

        return "; ".join(parts)

    def format_counts_by_class(self, counts):
        counts_text = ", ".join(
            f"{class_name}: {count}"
            for class_name, count in counts.items()
            if count > 0
        )
        if not counts_text:
            return "None"
        return counts_text

    def default_direction_labels(self):
        return {
            DIRECTION_NEGATIVE_TO_POSITIVE: "Direction A",
            DIRECTION_POSITIVE_TO_NEGATIVE: "Direction B",
        }

    def format_direction_label_summary(self):
        return (
            f"{self.direction_labels[DIRECTION_NEGATIVE_TO_POSITIVE]} / "
            f"{self.direction_labels[DIRECTION_POSITIVE_TO_NEGATIVE]}"
        )

    def get_active_settings(self):
        enabled_classes = [
            class_name
            for class_name, checkbox in self.class_checkboxes.items()
            if checkbox.isChecked()
        ]
        if not enabled_classes:
            self.set_status("Status: Select at least one class in the settings area.")
            return None

        return normalize_settings(
            {
                "confidence_threshold": self.confidence_spinbox.value(),
                "frame_skip": self.frame_skip_spinbox.value(),
                "model_size": self.model_size_combobox.currentText(),
                "enabled_classes": enabled_classes,
            }
        )

    def get_export_settings(self):
        if self.count_settings is not None:
            return self.count_settings
        settings = self.get_active_settings()
        if settings is not None:
            return settings
        return normalize_settings(
            {
                "confidence_threshold": self.confidence_spinbox.value(),
                "frame_skip": self.frame_skip_spinbox.value(),
                "model_size": self.model_size_combobox.currentText(),
                "enabled_classes": list(self.class_checkboxes.keys()),
            }
        )
