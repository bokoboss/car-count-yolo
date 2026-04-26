from pathlib import Path
import math

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import config
from .detection import detect_vehicles, normalize_settings
from .exporter import export_results_file
from .sources import (
    SOURCE_KIND_DIRECT_STREAM,
    SOURCE_KIND_LOCAL_FILE,
    SOURCE_KIND_YOUTUBE_URL,
    STREAM_FORMAT_HLS,
    STREAM_FORMAT_MJPEG,
    STREAM_FORMAT_RTSP,
    resolve_direct_stream_source,
    resolve_local_file_source,
    resolve_youtube_source,
)
from .tracking import (
    DEFAULT_LINE_KEYS,
    DIRECTION_NEGATIVE_TO_POSITIVE,
    DIRECTION_POSITIVE_TO_NEGATIVE,
    PROCESSING_STATUS_CANCELLED,
    PROCESSING_STATUS_ERROR,
    PROCESSING_STATUS_STREAM_STOPPED,
    track_vehicles,
)
from .utils import draw_line_overlay, frame_to_pixmap, load_video, read_first_frame


LINE_DISPLAY_NAMES = {
    "line_1": "Line 1",
    "line_2": "Line 2",
    "line_3": "Line 3",
}
LINE_SHORT_NAMES = {
    "line_1": "L1",
    "line_2": "L2",
    "line_3": "L3",
}
LINE_COLORS = {
    "line_1": "#ff3b30",
    "line_2": "#0a84ff",
    "line_3": "#34c759",
}
MODEL_OPTION_LABELS = {
    "nano": "Nano - Fastest / Lightest",
    "small": "Small - Balanced",
    "medium": "Medium - Slower / More Accurate",
}
TRACK_LABEL_MODE_OFF = "off"
TRACK_LABEL_MODE_CLASS_ONLY = "class_only"
TRACK_LABEL_MODE_ID_CLASS = "id_class"


class PreviewLabel(QLabel):
    def __init__(
        self,
        press_handler=None,
        move_handler=None,
        release_handler=None,
        parent=None,
    ):
        super().__init__(parent)
        self.press_handler = press_handler
        self.move_handler = move_handler
        self.release_handler = release_handler
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.press_handler:
            self.press_handler(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.move_handler:
            self.move_handler(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.release_handler:
            self.release_handler(event)
        super().mouseReleaseEvent(event)


class CountingWorker(QObject):
    progress = pyqtSignal(int, int, object, object)
    finished = pyqtSignal(object, object, object)

    def __init__(
        self,
        video_source,
        line_points,
        settings,
        track_label_mode=TRACK_LABEL_MODE_OFF,
        annotated_video_options=None,
    ):
        super().__init__()
        self.video_source = video_source
        self.line_points = line_points
        self.settings = settings
        self.track_label_mode = track_label_mode
        self.annotated_video_options = annotated_video_options
        self.stop_requested = False

    @pyqtSlot()
    def run(self):
        latest_frame, results, processing_status = track_vehicles(
            video_source=self.video_source,
            line_points=self.line_points,
            settings=self.settings,
            track_label_mode=self.track_label_mode,
            annotated_video_options=self.annotated_video_options,
            progress_callback=self.emit_progress,
            should_cancel=self.is_stop_requested,
        )
        self.finished.emit(latest_frame, results, processing_status)

    def emit_progress(self, processed_frames, total_frames, latest_frame, counts_snapshot):
        self.progress.emit(processed_frames, total_frames, latest_frame, counts_snapshot)

    def request_stop(self):
        self.stop_requested = True

    def is_stop_requested(self):
        return self.stop_requested


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.status_text = None
        self.latest_status_message = (
            "Welcome to Vehicle Counter! Select a video source to begin."
        )
        self.dashboard_widgets_ready = False
        self.summary_value_labels = {}
        self.line_overview_widgets = {}
        self.overall_class_chip_labels = {}
        self.line_class_overview_widgets = {}
        self.active_line_detail_labels = {}
        self.direction_section_widgets = {}
        self.overall_count_labels = {}
        self.run_settings_value_labels = {}
        self.preview_frame = None
        self.detected_preview_frame = None
        self.selected_source = None
        self.count_results = None
        self.count_settings = None
        self.is_counting = False
        self.stop_requested = False
        self.counting_thread = None
        self.counting_worker = None
        self.draw_mode_enabled = False
        self.pending_line_start = None
        self.count_lines = {line_key: None for line_key in DEFAULT_LINE_KEYS}
        self.active_line_key = DEFAULT_LINE_KEYS[0]
        self.line_drag_mode = None
        self.line_drag_last_point = None
        self.line_hover_target = None
        self.initial_splitter_applied = False
        self.applying_preset = False
        self.low_latency_manually_overridden = False
        self.active_preset_name = "Custom"
        self.direction_labels_by_line = self.build_default_direction_labels_by_line()
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setGeometry(100, 100, config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
        self.setMinimumSize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_panel = self.build_left_panel()
        self.right_panel = self.build_right_panel()
        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.right_panel)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setSizes([1040, 480])
        main_layout.addWidget(self.main_splitter)

    def build_left_panel(self):
        left_panel = QWidget()
        left_panel.setMinimumWidth(config.LEFT_PANEL_MIN_WIDTH)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.build_source_group())
        button_layout = QHBoxLayout()
        button_layout.setSpacing(6)

        active_line_label = QLabel("Active Line")
        button_layout.addWidget(active_line_label)

        self.active_line_combobox = QComboBox()
        for line_key in DEFAULT_LINE_KEYS:
            self.active_line_combobox.addItem(LINE_DISPLAY_NAMES[line_key], line_key)
        self.active_line_combobox.currentIndexChanged.connect(self.handle_active_line_changed)
        button_layout.addWidget(self.active_line_combobox)

        self.draw_line_btn = QPushButton("Place / Edit Line")
        self.draw_line_btn.clicked.connect(self.draw_count_line)
        button_layout.addWidget(self.draw_line_btn)

        self.clear_line_btn = QPushButton("Clear Line")
        self.clear_line_btn.clicked.connect(self.clear_count_line)
        button_layout.addWidget(self.clear_line_btn)

        self.direction_labels_btn = QPushButton("Name Directions")
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

        left_layout.addLayout(button_layout)

        self.preview_label = PreviewLabel(
            press_handler=self.handle_preview_press,
            move_handler=self.handle_preview_move,
            release_handler=self.handle_preview_release,
        )
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "border: 1px solid #444444; background-color: #d8d8d8;"
        )
        self.preview_label.setMinimumHeight(300)
        self.preview_label.setScaledContents(False)
        self.preview_label.setText("Preview Area - Video will appear here")
        left_layout.addWidget(self.preview_label, 1)

        preview_options_layout = QHBoxLayout()
        preview_options_layout.setSpacing(10)
        preview_options_label = QLabel("Preview Overlays")
        preview_options_label.setProperty("role", "panelHint")
        preview_options_layout.addWidget(preview_options_label)

        track_mode_label = QLabel("Tracks")
        track_mode_label.setProperty("role", "panelHint")
        preview_options_layout.addWidget(track_mode_label)

        self.track_label_mode_combobox = QComboBox()
        self.track_label_mode_combobox.addItem("Off", TRACK_LABEL_MODE_OFF)
        self.track_label_mode_combobox.addItem("Class Only", TRACK_LABEL_MODE_CLASS_ONLY)
        self.track_label_mode_combobox.addItem("ID + Class", TRACK_LABEL_MODE_ID_CLASS)
        self.track_label_mode_combobox.setCurrentIndex(1)
        self.track_label_mode_combobox.currentIndexChanged.connect(
            self.handle_preview_overlay_option_changed
        )
        preview_options_layout.addWidget(self.track_label_mode_combobox)

        self.show_line_labels_checkbox = QCheckBox("Line Tags")
        self.show_line_labels_checkbox.setChecked(True)
        self.show_line_labels_checkbox.toggled.connect(self.handle_preview_overlay_option_changed)
        preview_options_layout.addWidget(self.show_line_labels_checkbox)

        self.show_direction_legend_checkbox = QCheckBox("Direction Legend")
        self.show_direction_legend_checkbox.setChecked(False)
        self.show_direction_legend_checkbox.toggled.connect(self.handle_preview_overlay_option_changed)
        preview_options_layout.addWidget(self.show_direction_legend_checkbox)
        preview_options_layout.addStretch(1)
        left_layout.addLayout(preview_options_layout)

        return left_panel

    def build_right_panel(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setMinimumWidth(config.RIGHT_PANEL_MIN_WIDTH)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.build_settings_group())
        right_layout.addWidget(self.build_all_lines_overview_group())
        right_layout.addWidget(self.build_active_line_details_group())
        right_layout.addWidget(self.build_overall_summary_group())
        right_layout.addWidget(self.build_run_settings_group())

        event_log_group = QGroupBox("Event Log")
        event_log_layout = QVBoxLayout(event_log_group)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setPlainText(self.latest_status_message)
        self.status_text.setMinimumHeight(96)
        self.status_text.setMaximumHeight(120)
        event_log_layout.addWidget(self.status_text)
        right_layout.addWidget(event_log_group)
        right_layout.addStretch(1)

        right_panel.setStyleSheet(
            """
            QGroupBox {
                font-weight: 600;
                margin-top: 8px;
                padding-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px 0 4px;
            }
            QFormLayout QLabel {
                min-width: 86px;
            }
            QLabel[role="panelHint"] {
                color: #5b5b5b;
                font-size: 11px;
            }
            QLabel[role="summaryPrimaryLabel"] {
                color: #555555;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel[role="summaryPrimaryValue"] {
                font-size: 30px;
                font-weight: 700;
                color: #111111;
            }
            QLabel[role="summaryStatusValue"] {
                font-size: 15px;
                font-weight: 700;
                color: #0f4c81;
                background: #eaf4ff;
                border: 1px solid #bdd8f2;
                border-radius: 8px;
                padding: 5px 8px;
            }
            QLabel[role="summarySecondaryLabel"] {
                color: #666666;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel[role="summarySecondaryValue"] {
                color: #222222;
                font-size: 12px;
            }
            QLabel[role="metricValue"] {
                font-weight: 600;
                min-width: 28px;
            }
            QLabel[role="metricLabel"] {
                color: #4a4a4a;
            }
            QLabel[role="tableHeader"] {
                color: #5f6771;
                font-size: 11px;
                font-weight: 700;
                background: #eef2f6;
                border: 1px solid #d7dde5;
                border-radius: 6px;
                padding: 4px 6px;
            }
            QLabel[role="tableCell"] {
                padding: 3px 6px;
                border-radius: 5px;
            }
            QLabel[role="selectedCell"] {
                padding: 3px 6px;
                border-radius: 5px;
                background: #e7f1ff;
                color: #0f4c81;
                font-weight: 700;
            }
            QLabel[role="detailMetaLabel"] {
                color: #666666;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel[role="detailMetaValue"] {
                color: #1b1b1b;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel[role="classChipLabel"] {
                color: #5c6570;
                font-size: 10px;
                font-weight: 700;
            }
            QLabel[role="classChipValue"] {
                color: #111111;
                font-size: 18px;
                font-weight: 700;
            }
            QFrame[role="classChip"] {
                background: #f6f8fb;
                border: 1px solid #d9e0e7;
                border-radius: 8px;
            }
            """
        )

        scroll_area.setWidget(right_panel)
        self.dashboard_widgets_ready = True
        self.refresh_dashboard()
        return scroll_area

    def build_settings_group(self):
        settings_group = QGroupBox("Settings")
        settings_group.setCheckable(True)
        settings_group.setChecked(True)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(0)
        settings_group.toggled.connect(self.handle_settings_group_toggled)

        self.settings_content = QWidget()
        form_layout = QFormLayout(self.settings_content)
        form_layout.setContentsMargins(8, 4, 8, 6)
        form_layout.setVerticalSpacing(3)
        form_layout.setHorizontalSpacing(8)
        settings_layout.addWidget(self.settings_content)

        self.preset_combobox = QComboBox()
        self.preset_combobox.addItem("Custom", config.PRESET_CUSTOM)
        self.preset_combobox.addItem(
            "Live Low Latency", config.PRESET_LIVE_LOW_LATENCY
        )
        self.preset_combobox.addItem(
            "Balanced Counting", config.PRESET_BALANCED_COUNTING
        )
        self.preset_combobox.addItem(
            "Motorcycle Focus", config.PRESET_MOTORCYCLE_FOCUS
        )
        self.preset_combobox.setToolTip(
            "Balanced Counting is the best starting point for most normal use."
        )
        self.preset_combobox.currentIndexChanged.connect(self.handle_preset_changed)
        form_layout.addRow("Preset", self.preset_combobox)

        self.confidence_spinbox = QDoubleSpinBox()
        self.confidence_spinbox.setRange(0.0, 1.0)
        self.confidence_spinbox.setDecimals(2)
        self.confidence_spinbox.setSingleStep(0.05)
        self.confidence_spinbox.setValue(config.DEFAULT_CONFIDENCE_THRESHOLD)
        form_layout.addRow("Confidence", self.confidence_spinbox)

        self.frame_skip_spinbox = QSpinBox()
        self.frame_skip_spinbox.setRange(1, 30)
        self.frame_skip_spinbox.setValue(config.DEFAULT_FRAME_SKIP)
        self.frame_skip_spinbox.setToolTip("Higher values are faster, but may reduce accuracy.")
        form_layout.addRow("Frame Skip", self.frame_skip_spinbox)

        self.model_size_combobox = QComboBox()
        for model_key in config.MODEL_SIZE_OPTIONS:
            self.model_size_combobox.addItem(
                MODEL_OPTION_LABELS.get(model_key, model_key.title()),
                model_key,
            )
        self.set_model_combobox_value(config.DEFAULT_MODEL_SIZE)
        self.model_size_combobox.setToolTip(
            "Nano = fastest and lightest, Small = balanced, Medium = slower but more accurate."
        )
        form_layout.addRow("Model", self.model_size_combobox)

        self.low_latency_live_checkbox = QCheckBox(
            "Prioritize low latency for live streams"
        )
        self.low_latency_live_checkbox.setChecked(False)
        self.low_latency_live_checkbox.setToolTip(
            "Recommended for live sources. Usually keep this off for local video files."
        )
        form_layout.addRow("Low Latency", self.low_latency_live_checkbox)

        annotated_video_widget = QWidget()
        annotated_video_layout = QGridLayout(annotated_video_widget)
        annotated_video_layout.setContentsMargins(0, 0, 0, 0)
        annotated_video_layout.setHorizontalSpacing(6)
        annotated_video_layout.setVerticalSpacing(3)
        self.save_annotated_video_checkbox = QCheckBox("Save annotated review video")
        self.save_annotated_video_checkbox.toggled.connect(
            self.handle_save_annotated_video_toggled
        )
        annotated_video_layout.addWidget(self.save_annotated_video_checkbox, 0, 0, 1, 2)

        self.annotated_video_path_input = QLineEdit()
        self.annotated_video_path_input.setPlaceholderText("Choose output .mp4 or .avi file")
        self.annotated_video_path_input.setEnabled(False)
        annotated_video_layout.addWidget(self.annotated_video_path_input, 1, 0)

        self.browse_annotated_video_btn = QPushButton("Browse...")
        self.browse_annotated_video_btn.setEnabled(False)
        self.browse_annotated_video_btn.clicked.connect(self.browse_annotated_video_output)
        annotated_video_layout.addWidget(self.browse_annotated_video_btn, 1, 1)
        form_layout.addRow("Annotated Video", annotated_video_widget)

        class_filter_widget = QWidget()
        class_filter_layout = QGridLayout(class_filter_widget)
        class_filter_layout.setContentsMargins(0, 0, 0, 0)
        class_filter_layout.setHorizontalSpacing(10)
        class_filter_layout.setVerticalSpacing(2)
        self.class_checkboxes = {}
        for index, class_name in enumerate(config.DEFAULT_ENABLED_CLASSES):
            checkbox = QCheckBox(class_name.title())
            checkbox.setChecked(True)
            self.class_checkboxes[class_name] = checkbox
            class_filter_layout.addWidget(checkbox, index // 2, index % 2)
        form_layout.addRow("Classes", class_filter_widget)

        self.active_preset_label = QLabel("Active preset: Custom")
        self.active_preset_label.setProperty("role", "panelHint")
        form_layout.addRow("", self.active_preset_label)

        self.connect_manual_setting_change_handlers()
        self.set_preset_combobox_value(config.DEFAULT_PRESET)
        self.handle_preset_changed()

        return settings_group

    def build_all_lines_overview_group(self):
        overview_group = QGroupBox("All Lines Overview")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(8, 8, 8, 8)
        overview_layout.setSpacing(6)
        self.summary_value_labels = {}
        self.line_overview_widgets = {}

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(8)
        summary_grid.setVerticalSpacing(3)

        total_label = QLabel("Total Crossings")
        total_label.setProperty("role", "summaryPrimaryLabel")
        total_value = QLabel("0")
        total_value.setProperty("role", "summaryPrimaryValue")
        status_label = QLabel("Current Status")
        status_label.setProperty("role", "summaryPrimaryLabel")
        status_value = QLabel("Waiting")
        status_value.setProperty("role", "summaryStatusValue")
        source_label = QLabel("Source")
        source_label.setProperty("role", "summarySecondaryLabel")
        source_value = QLabel("-")
        source_value.setWordWrap(True)
        source_value.setProperty("role", "summarySecondaryValue")
        frames_label = QLabel("Processed Frames")
        frames_label.setProperty("role", "summarySecondaryLabel")
        frames_value = QLabel("0")
        frames_value.setProperty("role", "summarySecondaryValue")

        summary_grid.addWidget(total_label, 0, 0)
        summary_grid.addWidget(status_label, 0, 1)
        summary_grid.addWidget(total_value, 1, 0)
        summary_grid.addWidget(status_value, 1, 1)

        source_frame = QFrame()
        source_layout = QVBoxLayout(source_frame)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(2)
        source_layout.addWidget(source_label)
        source_layout.addWidget(source_value)

        frames_frame = QFrame()
        frames_layout = QVBoxLayout(frames_frame)
        frames_layout.setContentsMargins(0, 0, 0, 0)
        frames_layout.setSpacing(2)
        frames_layout.addWidget(frames_label)
        frames_layout.addWidget(frames_value)

        summary_grid.addWidget(source_frame, 2, 0)
        summary_grid.addWidget(frames_frame, 2, 1)
        overview_layout.addLayout(summary_grid)

        class_chip_grid = QGridLayout()
        class_chip_grid.setHorizontalSpacing(6)
        class_chip_grid.setVerticalSpacing(6)
        self.overall_class_chip_labels = {}
        class_chip_order = ("total",) + config.DEFAULT_ENABLED_CLASSES
        class_chip_titles = {
            "total": "Total",
            "car": "Car",
            "motorcycle": "Motorcycle",
            "bus": "Bus",
            "truck": "Truck",
            "bicycle": "Bicycle",
        }
        for index, metric_key in enumerate(class_chip_order):
            chip = QFrame()
            chip.setProperty("role", "classChip")
            chip_layout = QVBoxLayout(chip)
            chip_layout.setContentsMargins(8, 6, 8, 6)
            chip_layout.setSpacing(1)
            title = QLabel(class_chip_titles[metric_key])
            title.setProperty("role", "classChipLabel")
            value = QLabel("0")
            value.setProperty("role", "classChipValue")
            chip_layout.addWidget(title)
            chip_layout.addWidget(value)
            class_chip_grid.addWidget(chip, index // 3, index % 3)
            self.overall_class_chip_labels[metric_key] = value

        overview_layout.addLayout(class_chip_grid)

        overview_grid = QGridLayout()
        overview_grid.setHorizontalSpacing(6)
        overview_grid.setVerticalSpacing(4)
        overview_headers = ("Line", "Name", "Total", "A", "B")
        for column, header_text in enumerate(overview_headers):
            header = QLabel(header_text)
            header.setProperty("role", "tableHeader")
            alignment = Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignRight
            header.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
            overview_grid.addWidget(header, 0, column)

        for row, line_key in enumerate(DEFAULT_LINE_KEYS, start=1):
            line_key_label = QLabel(LINE_SHORT_NAMES[line_key])
            line_key_label.setProperty("role", "tableCell")
            line_name_label = QLabel(LINE_DISPLAY_NAMES[line_key])
            line_name_label.setProperty("role", "tableCell")
            total_line_value = QLabel("0")
            total_line_value.setProperty("role", "tableCell")
            direction_a_value = QLabel("0")
            direction_a_value.setProperty("role", "tableCell")
            direction_b_value = QLabel("0")
            direction_b_value.setProperty("role", "tableCell")
            for column, widget in enumerate(
                (line_key_label, line_name_label, total_line_value, direction_a_value, direction_b_value)
            ):
                if column > 1:
                    widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                overview_grid.addWidget(widget, row, column)

            self.line_overview_widgets[line_key] = {
                "line": line_key_label,
                "name": line_name_label,
                "total": total_line_value,
                "direction_a": direction_a_value,
                "direction_b": direction_b_value,
            }

        overview_layout.addLayout(overview_grid)

        class_overview_grid = QGridLayout()
        class_overview_grid.setHorizontalSpacing(4)
        class_overview_grid.setVerticalSpacing(4)
        class_overview_headers = ("Line", "Total", "Car", "Moto", "Bus", "Truck", "Bike")
        for column, header_text in enumerate(class_overview_headers):
            header = QLabel(header_text)
            header.setProperty("role", "tableHeader")
            alignment = Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignRight
            header.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
            class_overview_grid.addWidget(header, 0, column)

        self.line_class_overview_widgets = {}
        for row, line_key in enumerate(DEFAULT_LINE_KEYS, start=1):
            widgets = {}
            for column, metric_key in enumerate(
                ("line", "total", "car", "motorcycle", "bus", "truck", "bicycle")
            ):
                label = QLabel(LINE_SHORT_NAMES[line_key] if metric_key == "line" else "0")
                label.setProperty("role", "tableCell")
                alignment = Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignRight
                label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
                class_overview_grid.addWidget(label, row, column)
                widgets[metric_key] = label
            self.line_class_overview_widgets[line_key] = widgets

        overview_layout.addLayout(class_overview_grid)

        self.summary_value_labels["total_crossings"] = total_value
        self.summary_value_labels["status"] = status_value
        self.summary_value_labels["source"] = source_value
        self.summary_value_labels["processed_frames"] = frames_value

        return overview_group

    def build_active_line_details_group(self):
        directions_group = QGroupBox("Active Line Details")
        directions_layout = QVBoxLayout(directions_group)
        directions_layout.setContentsMargins(8, 8, 8, 8)
        directions_layout.setSpacing(6)

        detail_meta_grid = QGridLayout()
        detail_meta_grid.setHorizontalSpacing(10)
        detail_meta_grid.setVerticalSpacing(3)
        self.active_line_detail_labels = {}
        for row, (key, label_text) in enumerate((
            ("selected_line", "Selected Line"),
            ("direction_a_label", "A -> B"),
            ("direction_b_label", "B -> A"),
        )):
            label = QLabel(label_text)
            label.setProperty("role", "detailMetaLabel")
            value = QLabel("-")
            value.setProperty("role", "detailMetaValue")
            detail_meta_grid.addWidget(label, row, 0)
            detail_meta_grid.addWidget(value, row, 1)
            self.active_line_detail_labels[key] = value
        directions_layout.addLayout(detail_meta_grid)

        detail_hint = QLabel("Preview markers show which side is A and which side is B for the selected line.")
        detail_hint.setProperty("role", "panelHint")
        directions_layout.addWidget(detail_hint)

        directions_grid = QGridLayout()
        directions_grid.setHorizontalSpacing(8)
        directions_grid.setVerticalSpacing(6)
        self.direction_section_widgets = {}

        for column, direction_key in enumerate((
            DIRECTION_NEGATIVE_TO_POSITIVE,
            DIRECTION_POSITIVE_TO_NEGATIVE,
        )):
            section_group = QGroupBox("")
            section_layout = QGridLayout(section_group)
            section_layout.setContentsMargins(6, 6, 6, 6)
            section_layout.setVerticalSpacing(2)
            section_layout.setHorizontalSpacing(8)
            value_labels = {}
            for row, (metric_key, metric_label) in enumerate(self.get_dashboard_metric_labels()):
                metric_widget = QLabel(metric_label)
                metric_widget.setProperty("role", "metricLabel")
                value_label = QLabel("0")
                value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                value_label.setProperty("role", "metricValue")
                section_layout.addWidget(metric_widget, row, 0)
                section_layout.addWidget(value_label, row, 1)
                value_labels[metric_key] = value_label
            directions_grid.addWidget(section_group, 0, column)
            self.direction_section_widgets[direction_key] = {
                "group": section_group,
                "labels": value_labels,
            }

        directions_layout.addLayout(directions_grid)
        return directions_group

    def build_overall_summary_group(self):
        overall_group = QGroupBox("Overall By Class")
        overall_layout = QGridLayout(overall_group)
        overall_layout.setContentsMargins(8, 8, 8, 8)
        overall_layout.setVerticalSpacing(2)
        overall_layout.setHorizontalSpacing(10)
        self.overall_count_labels = {}
        for index, class_name in enumerate(config.DEFAULT_ENABLED_CLASSES):
            label = QLabel(class_name.title())
            label.setProperty("role", "metricLabel")
            value_label = QLabel("0")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setProperty("role", "metricValue")
            row = index // 2
            column = (index % 2) * 2
            overall_layout.addWidget(label, row, column)
            overall_layout.addWidget(value_label, row, column + 1)
            self.overall_count_labels[class_name] = value_label
        return overall_group

    def build_run_settings_group(self):
        run_settings_group = QGroupBox("Run Settings")
        run_settings_layout = QGridLayout(run_settings_group)
        run_settings_layout.setContentsMargins(8, 8, 8, 8)
        run_settings_layout.setVerticalSpacing(2)
        run_settings_layout.setHorizontalSpacing(10)
        self.run_settings_value_labels = {}

        for row, (key, label_text) in enumerate((
            ("preset_name", "Preset"),
            ("model_size", "Model"),
            ("confidence_threshold", "Confidence"),
            ("frame_skip", "Frame Skip"),
            ("low_latency", "Low Latency"),
            ("annotated_video", "Annotated Video"),
        )):
            label = QLabel(label_text)
            label.setProperty("role", "metricLabel")
            value_label = QLabel("-")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            run_settings_layout.addWidget(label, row, 0)
            run_settings_layout.addWidget(value_label, row, 1)
            self.run_settings_value_labels[key] = value_label

        return run_settings_group

    def build_source_group(self):
        source_group = QGroupBox("Video Source")
        source_layout = QFormLayout(source_group)

        self.source_type_combobox = QComboBox()
        self.source_type_combobox.addItem("Local Video File", SOURCE_KIND_LOCAL_FILE)
        self.source_type_combobox.addItem("YouTube URL", SOURCE_KIND_YOUTUBE_URL)
        self.source_type_combobox.addItem("Direct Camera Stream URL", SOURCE_KIND_DIRECT_STREAM)
        self.source_type_combobox.currentIndexChanged.connect(self.handle_source_type_changed)
        source_layout.addRow("Source Type", self.source_type_combobox)

        self.source_input_stack = QStackedWidget()
        self.source_input_stack.addWidget(self.build_local_source_widget())
        self.source_input_stack.addWidget(self.build_youtube_source_widget())
        self.source_input_stack.addWidget(self.build_direct_stream_widget())
        source_layout.addRow("Source", self.source_input_stack)

        self.load_source_btn = QPushButton("Load Source Preview")
        self.load_source_btn.clicked.connect(self.load_selected_source)
        source_layout.addRow("", self.load_source_btn)

        return source_group

    def build_local_source_widget(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.local_file_input = QLineEdit()
        self.local_file_input.setReadOnly(True)
        self.local_file_input.setPlaceholderText("Choose a local video file")
        layout.addWidget(self.local_file_input)

        self.browse_video_btn = QPushButton("Browse...")
        self.browse_video_btn.clicked.connect(self.browse_local_video)
        layout.addWidget(self.browse_video_btn)
        return widget

    def build_youtube_source_widget(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.youtube_url_input = QLineEdit()
        self.youtube_url_input.setPlaceholderText(
            "Paste a YouTube watch or live URL"
        )
        self.youtube_url_input.returnPressed.connect(self.load_selected_source)
        layout.addWidget(self.youtube_url_input)
        return widget

    def build_direct_stream_widget(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.direct_stream_url_input = QLineEdit()
        self.direct_stream_url_input.setPlaceholderText(
            "Paste an MJPEG, HLS (.m3u8), or RTSP stream URL"
        )
        self.direct_stream_url_input.returnPressed.connect(self.load_selected_source)
        layout.addWidget(self.direct_stream_url_input)
        return widget

    def browse_local_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv)",
        )

        if not file_path:
            self.set_status("No file selected.\nVideo selection was cancelled.")
            return

        self.local_file_input.setText(file_path)
        self.load_selected_source()

    def load_selected_source(self):
        source, error_message = self.resolve_selected_source()
        if error_message:
            self.set_status(f"Status: {error_message}")
            return

        capture, error_message = load_video(
            source.playable_input,
            is_live=source.is_live,
            prioritize_low_latency=self.low_latency_live_checkbox.isChecked(),
        )

        if error_message:
            self.set_status(f"Status: {error_message}")
            return

        try:
            frame, error_message = read_first_frame(capture)
        finally:
            capture.release()

        if error_message:
            self.set_status(f"Status: {error_message}")
            return

        self.preview_frame = frame
        self.detected_preview_frame = None
        self.selected_source = source
        self.count_results = None
        self.count_settings = None
        self.reset_line_state(clear_saved_line=True)
        self.count_lines = {line_key: None for line_key in DEFAULT_LINE_KEYS}
        self.direction_labels_by_line = self.build_default_direction_labels_by_line()
        self.active_line_key = DEFAULT_LINE_KEYS[0]
        self.active_line_combobox.setCurrentIndex(0)
        self.refresh_line_action_button_text()
        if not self.annotated_video_path_input.text().strip():
            self.annotated_video_path_input.setText(self.build_default_annotated_video_path(source))
        self.update_preview()
        self.update_export_ui_state()
        self.refresh_dashboard(status_override="Preview loaded")
        self.set_status(self.format_source_loaded_status(source))
        self.refresh_line_action_button_text()

    def resolve_selected_source(self):
        source_kind = self.source_type_combobox.currentData()
        if source_kind == SOURCE_KIND_YOUTUBE_URL:
            return resolve_youtube_source(self.youtube_url_input.text())
        if source_kind == SOURCE_KIND_DIRECT_STREAM:
            return resolve_direct_stream_source(self.direct_stream_url_input.text())
        return resolve_local_file_source(self.local_file_input.text())

    def handle_source_type_changed(self):
        self.source_input_stack.setCurrentIndex(self.source_type_combobox.currentIndex())
        self.apply_source_aware_low_latency_default()
        self.update_counting_ui_state()
        self.refresh_dashboard()
        if self.source_type_combobox.currentData() == SOURCE_KIND_YOUTUBE_URL:
            self.set_status(
                "Status: Paste a YouTube watch or live URL, then click Load Source Preview.\n"
                "Tip: Low latency is recommended by default for live-like sources, but you can switch it off."
            )
        elif self.source_type_combobox.currentData() == SOURCE_KIND_DIRECT_STREAM:
            self.set_status(
                "Status: Paste an MJPEG, HLS (.m3u8), or RTSP camera stream URL, then click Load Source Preview.\n"
                "Tip: Low latency is recommended by default for live-like sources, but you can switch it off."
            )
        else:
            self.set_status(
                "Status: Choose a local video file, then load its preview.\n"
                "Tip: Low latency stays off by default for local files, but you can turn it on if you want."
            )

    def handle_active_line_changed(self):
        selected_line_key = self.active_line_combobox.currentData()
        if not selected_line_key:
            return
        self.active_line_key = selected_line_key
        self.line_drag_mode = None
        self.line_drag_last_point = None
        self.line_hover_target = None
        self.update_preview()
        self.refresh_dashboard()
        self.refresh_line_action_button_text()
        if self.is_counting:
            self.set_status(
                "Status: Active line focus changed.\n"
                f"{self.get_active_line_name()} is now highlighted for preview and detail viewing.\n"
                "Counting continues unchanged in the background."
            )
            return
        self.set_status(
            "Status: Active line changed.\n"
            f"{self.get_active_line_name()} selected.\n"
            "Drag the line to adjust it, review it, rename its directions, or start counting when ready."
        )

    def handle_preview_overlay_option_changed(self):
        self.update_preview()

    def handle_save_annotated_video_toggled(self, checked):
        self.annotated_video_path_input.setEnabled(checked and not self.is_counting)
        self.browse_annotated_video_btn.setEnabled(checked and not self.is_counting)
        if checked and not self.annotated_video_path_input.text().strip():
            self.annotated_video_path_input.setText(self.build_default_annotated_video_path())
        if checked:
            self.set_status(
                "Status: Annotated video saving enabled.\n"
                "The next counting run will save a clean review video if the output path is valid."
            )
        else:
            self.set_status("Status: Annotated video saving disabled.")

    def browse_annotated_video_output(self):
        default_path = self.annotated_video_path_input.text().strip() or self.build_default_annotated_video_path()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Annotated Video",
            default_path,
            "MP4 Video (*.mp4);;AVI Video (*.avi)",
        )
        if not file_path:
            self.set_status("Status: Annotated video output selection cancelled.")
            return
        self.annotated_video_path_input.setText(file_path)
        self.set_status(
            "Status: Annotated video output selected.\n"
            f"Saved file: {Path(file_path).name}"
        )

    def handle_settings_group_toggled(self, checked):
        self.settings_content.setVisible(checked)
        if checked:
            self.set_status("Status: Settings expanded.")
        else:
            self.set_status("Status: Settings collapsed.")

    def connect_manual_setting_change_handlers(self):
        self.confidence_spinbox.valueChanged.connect(self.handle_manual_setting_changed)
        self.frame_skip_spinbox.valueChanged.connect(self.handle_manual_setting_changed)
        self.model_size_combobox.currentIndexChanged.connect(self.handle_manual_setting_changed)
        self.low_latency_live_checkbox.stateChanged.connect(self.handle_low_latency_changed)
        for checkbox in self.class_checkboxes.values():
            checkbox.stateChanged.connect(self.handle_manual_setting_changed)

    def handle_preset_changed(self):
        if self.applying_preset:
            return

        preset_key = self.preset_combobox.currentData()
        if preset_key == config.PRESET_CUSTOM:
            self.set_active_preset_name("Custom")
            return

        preset_settings = self.get_preset_settings(preset_key)
        if preset_settings is None:
            return

        self.apply_preset_settings(preset_key, preset_settings)

    def handle_manual_setting_changed(self):
        if self.applying_preset:
            return
        self.set_preset_combobox_value(config.PRESET_CUSTOM)
        self.set_active_preset_name("Custom")
        self.refresh_dashboard()

    def handle_low_latency_changed(self):
        if self.applying_preset:
            return
        self.low_latency_manually_overridden = True
        self.handle_manual_setting_changed()

    def apply_preset_settings(self, preset_key, preset_settings):
        self.applying_preset = True
        try:
            self.confidence_spinbox.setValue(preset_settings["confidence_threshold"])
            self.frame_skip_spinbox.setValue(preset_settings["frame_skip"])
            self.set_model_combobox_value(preset_settings["model_size"])
            self.low_latency_live_checkbox.setChecked(
                preset_settings["prioritize_low_latency_live_streams"]
            )
            enabled_classes = set(preset_settings["enabled_classes"])
            for class_name, checkbox in self.class_checkboxes.items():
                checkbox.setChecked(class_name in enabled_classes)
            track_label_mode = preset_settings.get("track_label_mode")
            if track_label_mode:
                self.set_track_label_mode(track_label_mode)
        finally:
            self.applying_preset = False
        self.low_latency_manually_overridden = False
        self.apply_source_aware_low_latency_default(force=True)

        self.set_active_preset_name(self.preset_combobox.currentText())
        self.set_status(
            "Status: Preset applied.\n"
            f"Active preset: {self.active_preset_name}"
        )
        self.refresh_dashboard()

    def set_preset_combobox_value(self, preset_key):
        index = self.preset_combobox.findData(preset_key)
        if index >= 0 and self.preset_combobox.currentIndex() != index:
            self.preset_combobox.setCurrentIndex(index)

    def set_model_combobox_value(self, model_key):
        index = self.model_size_combobox.findData(model_key)
        if index >= 0:
            self.model_size_combobox.setCurrentIndex(index)

    def set_active_preset_name(self, preset_name):
        self.active_preset_name = preset_name
        self.active_preset_label.setText(f"Active preset: {preset_name}")

    def get_preset_settings(self, preset_key):
        preset_map = {
            config.PRESET_LIVE_LOW_LATENCY: {
                "confidence_threshold": 0.35,
                "frame_skip": 3,
                "model_size": "nano",
                "enabled_classes": ["car", "motorcycle", "bus", "truck"],
                "prioritize_low_latency_live_streams": True,
            },
            config.PRESET_BALANCED_COUNTING: {
                "confidence_threshold": config.DEFAULT_CONFIDENCE_THRESHOLD,
                "frame_skip": 1,
                "model_size": "small",
                "enabled_classes": list(config.DEFAULT_ENABLED_CLASSES),
                "prioritize_low_latency_live_streams": False,
            },
            config.PRESET_MOTORCYCLE_FOCUS: {
                "confidence_threshold": 0.20,
                "frame_skip": 1,
                "model_size": "medium",
                "enabled_classes": ["car", "motorcycle", "bus", "truck", "bicycle"],
                "prioritize_low_latency_live_streams": False,
                "track_label_mode": TRACK_LABEL_MODE_ID_CLASS,
            },
        }
        return preset_map.get(preset_key)

    def draw_count_line(self):
        if self.preview_frame is None:
            self.set_status(
                "Status: Load a video source first before drawing a count line."
            )
            return

        self.pending_line_start = None
        self.draw_mode_enabled = True
        self.line_drag_mode = None
        self.line_drag_last_point = None
        self.line_hover_target = None
        self.update_preview()
        if self.get_active_line_points() is None:
            self.set_status(
                "Status: Draw mode enabled.\n"
                f"Click the preview twice to place {self.get_active_line_name()}.\n"
                "Tip: After placing a line, you can drag it directly to fine-tune it."
            )
            return

        self.set_status(
            "Status: Line edit mode ready.\n"
            f"You can drag {self.get_active_line_name()} directly to adjust it, or click twice to place it again."
        )

    def detect_current_preview(self):
        if self.preview_frame is None:
            self.set_status("Status: Load a video source first before running detection.")
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
        if not self.selected_source or self.preview_frame is None:
            self.set_status(
                "Status: Load a source preview first.\nNext step: choose a source and click Load Source Preview."
            )
            return

        if not self.has_any_defined_lines():
            self.set_status(
                "Status: Add at least one count line before starting.\n"
                "Next step: pick a line from Active Line, then click Place Line."
            )
            return

        self.count_results = None
        settings = self.get_active_settings()
        if not settings:
            return
        annotated_video_options = self.get_annotated_video_options()
        if annotated_video_options is None:
            return

        self.count_settings = settings
        self.refresh_dashboard(status_override="Starting")
        status_message = "Status: Processing started.\nReading video and tracking vehicles..."
        if annotated_video_options.get("enabled"):
            status_message += (
                f"\nAnnotated video saving started: "
                f"{Path(annotated_video_options['output_path']).name}"
            )
        self.set_status(status_message)
        self.is_counting = True
        self.stop_requested = False
        self.update_counting_ui_state()
        self.refresh_dashboard(status_override="Processing")
        self.start_counting_worker(settings, annotated_video_options)

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
            export_result = export_results_file(
                file_path=file_path,
                results=self.count_results,
                source_details=self.get_export_source_details(),
                direction_labels=self.direction_labels_by_line,
                settings=self.get_export_settings(),
            )
        except Exception as exc:
            self.set_status(f"Status: Export failed. {exc}")
            return

        if export_result and export_result.get("error"):
            self.set_status(f"Status: {export_result['error']}")
            return

        created_files = (export_result or {}).get("created_files") or [str(Path(file_path))]
        saved_names = ", ".join(Path(path).name for path in created_files)
        self.set_status(
            "Status: Results exported successfully.\n"
            f"Created: {saved_names}"
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
        if self.get_active_line_points() is None and self.pending_line_start is None:
            self.set_status(
                f"Status: {self.get_active_line_name()} does not have a saved line to clear."
            )
            return

        self.reset_line_state(clear_saved_line=True)
        self.update_preview()
        self.set_status(f"Status: {self.get_active_line_name()} cleared.")

    def set_direction_labels(self):
        current_labels = self.get_active_direction_labels()
        first_label, ok = QInputDialog.getText(
            self,
            "A To B Label",
            f"Name the movement from A to B on {self.get_active_line_name()}:",
            text=current_labels[DIRECTION_NEGATIVE_TO_POSITIVE],
        )
        if not ok:
            self.set_status("Status: Direction label update cancelled.")
            return

        second_label, ok = QInputDialog.getText(
            self,
            "B To A Label",
            f"Name the movement from B to A on {self.get_active_line_name()}:",
            text=current_labels[DIRECTION_POSITIVE_TO_NEGATIVE],
        )
        if not ok:
            self.set_status("Status: Direction label update cancelled.")
            return

        self.direction_labels_by_line[self.active_line_key] = {
            DIRECTION_NEGATIVE_TO_POSITIVE: first_label.strip() or "A -> B",
            DIRECTION_POSITIVE_TO_NEGATIVE: second_label.strip() or "B -> A",
        }
        self.refresh_dashboard()
        self.update_preview()
        self.set_status(
            "Status: Direction labels updated.\n"
            f"{self.get_active_line_name()}: {self.format_direction_label_summary(self.active_line_key)}\n"
            "A and B markers on the preview show which side each direction refers to."
        )

    def set_status(self, message):
        self.latest_status_message = message
        if self.status_text is not None:
            self.status_text.setPlainText(message)

    def clear_preview(self):
        self.reset_line_state(clear_saved_line=True)
        self.count_lines = {line_key: None for line_key in DEFAULT_LINE_KEYS}
        self.preview_frame = None
        self.detected_preview_frame = None
        self.selected_source = None
        self.count_results = None
        self.count_settings = None
        self.is_counting = False
        self.stop_requested = False
        self.direction_labels_by_line = self.build_default_direction_labels_by_line()
        self.active_line_key = DEFAULT_LINE_KEYS[0]
        self.active_line_combobox.setCurrentIndex(0)
        self.refresh_line_action_button_text()
        self.cleanup_counting_thread()
        self.update_counting_ui_state()
        self.update_export_ui_state()
        self.preview_label.clear()
        self.preview_label.setText("Preview Area - Video will appear here")
        self.refresh_dashboard()

    def update_preview(self):
        current_frame = self.get_current_preview_frame()
        if current_frame is None:
            return

        display_pixmap = frame_to_pixmap(current_frame)
        for line_key in DEFAULT_LINE_KEYS:
            line_points = self.count_lines.get(line_key)
            if line_points is None:
                continue
            display_pixmap = draw_line_overlay(
                display_pixmap,
                line_points[0],
                line_points[1],
                direction_labels=self.direction_labels_by_line[line_key],
                line_color=LINE_COLORS[line_key],
                line_label=LINE_SHORT_NAMES[line_key],
                is_selected=(line_key == self.active_line_key),
                show_direction_legend=(
                    line_key == self.active_line_key
                    and self.show_direction_legend_checkbox.isChecked()
                ),
                show_line_label=self.show_line_labels_checkbox.isChecked(),
                active_handle=self.get_active_line_handle() if line_key == self.active_line_key else None,
            )
        if self.pending_line_start is not None:
            display_pixmap = draw_line_overlay(
                display_pixmap,
                self.pending_line_start,
                self.pending_line_start,
                line_color=LINE_COLORS[self.active_line_key],
                line_label=LINE_SHORT_NAMES[self.active_line_key],
                is_selected=True,
                show_line_label=self.show_line_labels_checkbox.isChecked(),
                show_handles=True,
            )

        scaled_pixmap = display_pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled_pixmap)

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_initial_splitter_sizes()
        self.update_preview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.initial_splitter_applied:
            self.apply_initial_splitter_sizes()
        if isinstance(self.preview_label.pixmap(), QPixmap):
            self.update_preview()

    def handle_preview_press(self, event):
        if self.preview_frame is None or self.is_counting:
            return

        image_point = self.map_event_to_image(event)
        if image_point is None:
            return

        if self.draw_mode_enabled:
            self.handle_draw_mode_press(image_point)
            return

        active_line = self.get_active_line_points()
        if active_line is None:
            return

        drag_target = self.get_line_hit_target(image_point)
        if drag_target is None:
            return

        self.line_drag_mode = drag_target
        self.line_drag_last_point = image_point
        self.line_hover_target = drag_target
        self.update_preview()
        self.update_preview_cursor(drag_target, dragging=True)

    def handle_preview_move(self, event):
        if self.preview_frame is None or self.is_counting:
            return

        image_point = self.map_event_to_image(event)
        if self.line_drag_mode is None:
            if self.get_active_line_points() is None:
                self.clear_line_hover_target()
                return
            hover_target = self.get_line_hit_target(image_point) if image_point is not None else None
            if hover_target != self.line_hover_target:
                self.line_hover_target = hover_target
                self.update_preview()
            self.update_preview_cursor(hover_target)
            return

        active_line = self.get_active_line_points()
        if image_point is None or active_line is None:
            return

        start_point, end_point = active_line
        if self.line_drag_mode == "start":
            self.set_active_line_points((self.clamp_point_to_image(image_point), end_point))
        elif self.line_drag_mode == "end":
            self.set_active_line_points((start_point, self.clamp_point_to_image(image_point)))
        else:
            delta_x = image_point.x() - self.line_drag_last_point.x()
            delta_y = image_point.y() - self.line_drag_last_point.y()
            delta_x, delta_y = self.clamp_line_delta(delta_x, delta_y)
            self.set_active_line_points((
                QPoint(start_point.x() + delta_x, start_point.y() + delta_y),
                QPoint(end_point.x() + delta_x, end_point.y() + delta_y),
            ))
            self.line_drag_last_point = QPoint(
                self.line_drag_last_point.x() + delta_x,
                self.line_drag_last_point.y() + delta_y,
            )

        if self.line_drag_mode in {"start", "end"}:
            self.line_drag_last_point = self.clamp_point_to_image(image_point)

        self.update_preview()

    def handle_preview_release(self, event):
        if self.line_drag_mode is None:
            return

        released_mode = self.line_drag_mode
        self.line_drag_mode = None
        self.line_drag_last_point = None
        release_point = self.map_event_to_image(event)
        self.line_hover_target = (
            self.get_line_hit_target(release_point)
            if release_point is not None and self.get_active_line_points() is not None
            else None
        )
        self.update_preview_cursor(self.line_hover_target)
        self.update_preview()
        active_line = self.get_active_line_points()
        if active_line is not None:
            self.set_status(
                f"Status: {self.get_active_line_name()} updated.\n"
                f"Edited by dragging the {'line body' if released_mode == 'line' else released_mode + ' endpoint'}.\n"
                f"{self.get_active_line_name()} coordinates: ({active_line[0].x()}, {active_line[0].y()}) -> "
                f"({active_line[1].x()}, {active_line[1].y()})\n"
                f"{self.format_direction_label_summary(self.active_line_key)}"
            )

    def handle_draw_mode_press(self, image_point):
        if self.pending_line_start is None:
            self.pending_line_start = image_point
            self.update_preview()
            self.set_status(
                "Status: First point selected.\nClick the preview again to finish the count line."
            )
            return

        self.set_active_line_points((self.pending_line_start, image_point))
        self.pending_line_start = None
        self.draw_mode_enabled = False
        self.line_hover_target = None
        completed_line_key = self.active_line_key
        completed_line_name = self.get_active_line_name()
        self.update_preview()
        active_line = self.count_lines[completed_line_key]
        self.set_status(
            f"Status: {completed_line_name} completed.\nStored coordinates: "
            f"({active_line[0].x()}, {active_line[0].y()}) -> "
            f"({active_line[1].x()}, {active_line[1].y()})\n"
            f"{completed_line_name}: {self.format_direction_label_summary(completed_line_key)}\n"
            "Preview markers show side A, side B, and the movement direction between them.\n"
            f"Next: {self.get_next_step_hint()}"
        )

    def map_event_to_image(self, event):
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
        self.line_drag_mode = None
        self.line_drag_last_point = None
        self.line_hover_target = None
        self.preview_label.unsetCursor()
        if clear_saved_line:
            self.count_lines[self.active_line_key] = None

    def build_default_direction_labels_by_line(self):
        return {
            line_key: self.default_direction_labels()
            for line_key in DEFAULT_LINE_KEYS
        }

    def get_active_line_name(self):
        return LINE_DISPLAY_NAMES[self.active_line_key]

    def get_active_line_points(self):
        return self.count_lines.get(self.active_line_key)

    def set_active_line_points(self, line_points):
        self.count_lines[self.active_line_key] = line_points
        self.refresh_line_action_button_text()

    def get_active_direction_labels(self):
        return self.direction_labels_by_line[self.active_line_key]

    def has_any_defined_lines(self):
        return any(line_points is not None for line_points in self.count_lines.values())

    def refresh_line_action_button_text(self):
        self.draw_line_btn.setText("Place / Edit Line")
        self.clear_line_btn.setText("Clear Line")

    def get_next_step_hint(self):
        if any(self.count_lines.get(line_key) is None for line_key in DEFAULT_LINE_KEYS):
            return "adjust this line, name its directions, or switch to another line when ready"
        return "drag a line to fine-tune it or start counting"

    def build_default_annotated_video_path(self, source=None):
        source = source or self.selected_source
        source_name = "counting_run"
        if source is not None:
            source_name = Path(source.display_name).stem or "counting_run"
        safe_name = "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in source_name
        ).strip("_") or "counting_run"
        output_dir = Path.cwd() / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / f"{safe_name}_annotated.mp4")

    def get_annotated_video_options(self):
        if not self.save_annotated_video_checkbox.isChecked():
            return {"enabled": False}

        output_path = self.annotated_video_path_input.text().strip()
        if not output_path:
            self.set_status(
                "Status: Choose an output path for the annotated video, or disable annotated video saving."
            )
            return None

        output_suffix = Path(output_path).suffix.lower()
        if output_suffix not in {".mp4", ".avi"}:
            self.set_status("Status: Annotated video output must use .mp4 or .avi.")
            return None

        return {
            "enabled": True,
            "output_path": output_path,
            "direction_labels_by_line": self.direction_labels_by_line,
            "line_colors": LINE_COLORS,
            "line_short_names": LINE_SHORT_NAMES,
        }

    def get_track_label_mode(self):
        return self.track_label_mode_combobox.currentData() or TRACK_LABEL_MODE_OFF

    def set_track_label_mode(self, track_label_mode):
        index = self.track_label_mode_combobox.findData(track_label_mode)
        if index >= 0:
            self.track_label_mode_combobox.setCurrentIndex(index)

    def apply_source_aware_low_latency_default(self, force=False):
        if self.low_latency_manually_overridden and not force:
            return

        source_kind = self.source_type_combobox.currentData()
        should_enable = source_kind in {
            SOURCE_KIND_YOUTUBE_URL,
            SOURCE_KIND_DIRECT_STREAM,
        }
        self.applying_preset = True
        try:
            self.low_latency_live_checkbox.setChecked(should_enable)
        finally:
            self.applying_preset = False

    def get_model_size_key(self):
        return self.model_size_combobox.currentData() or config.DEFAULT_MODEL_SIZE

    def get_model_display_label(self):
        return self.model_size_combobox.currentText()

    def apply_initial_splitter_sizes(self):
        if self.initial_splitter_applied:
            return

        available_width = max(
            self.main_splitter.size().width(),
            self.width() - 24,
            config.WINDOW_MIN_WIDTH - 24,
        )
        right_width = max(
            config.RIGHT_PANEL_MIN_WIDTH,
            round(available_width * (1.0 - config.INITIAL_SPLITTER_LEFT_RATIO)),
        )
        left_width = max(config.LEFT_PANEL_MIN_WIDTH, available_width - right_width)
        self.main_splitter.setSizes([left_width, right_width])
        self.initial_splitter_applied = True

    def get_active_line_handle(self):
        if self.line_drag_mode in {"start", "end"}:
            return self.line_drag_mode
        if self.line_hover_target in {"start", "end"}:
            return self.line_hover_target
        return None

    def get_line_hit_target(self, image_point):
        active_line = self.get_active_line_points()
        if image_point is None or active_line is None:
            return None

        start_point, end_point = active_line
        if self.distance_between_points(image_point, start_point) <= 16:
            return "start"
        if self.distance_between_points(image_point, end_point) <= 16:
            return "end"
        if self.distance_to_line_segment(image_point, start_point, end_point) <= 10:
            return "line"
        return None

    def clear_line_hover_target(self):
        if self.line_hover_target is not None:
            self.line_hover_target = None
            self.update_preview()
        self.preview_label.unsetCursor()

    def update_preview_cursor(self, target, dragging=False):
        if target in {"start", "end"}:
            self.preview_label.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        if target == "line":
            self.preview_label.setCursor(
                Qt.CursorShape.ClosedHandCursor if dragging else Qt.CursorShape.OpenHandCursor
            )
            return
        self.preview_label.unsetCursor()

    def clamp_point_to_image(self, point):
        image_size = self.get_preview_image_size()
        if image_size is None:
            return QPoint(point)
        image_width, image_height = image_size
        return QPoint(
            max(0, min(point.x(), image_width - 1)),
            max(0, min(point.y(), image_height - 1)),
        )

    def clamp_line_delta(self, delta_x, delta_y):
        active_line = self.get_active_line_points()
        if active_line is None:
            return 0, 0

        image_size = self.get_preview_image_size()
        if image_size is None:
            return 0, 0

        image_width, image_height = image_size
        start_point, end_point = active_line
        min_delta_x = -min(start_point.x(), end_point.x())
        max_delta_x = (image_width - 1) - max(start_point.x(), end_point.x())
        min_delta_y = -min(start_point.y(), end_point.y())
        max_delta_y = (image_height - 1) - max(start_point.y(), end_point.y())
        clamped_delta_x = max(min_delta_x, min(delta_x, max_delta_x))
        clamped_delta_y = max(min_delta_y, min(delta_y, max_delta_y))
        return clamped_delta_x, clamped_delta_y

    def distance_between_points(self, first_point, second_point):
        return math.hypot(
            first_point.x() - second_point.x(),
            first_point.y() - second_point.y(),
        )

    def distance_to_line_segment(self, point, line_start, line_end):
        line_dx = line_end.x() - line_start.x()
        line_dy = line_end.y() - line_start.y()
        segment_length_squared = (line_dx * line_dx) + (line_dy * line_dy)
        if segment_length_squared == 0:
            return self.distance_between_points(point, line_start)

        projection = (
            ((point.x() - line_start.x()) * line_dx)
            + ((point.y() - line_start.y()) * line_dy)
        ) / segment_length_squared
        projection = max(0.0, min(1.0, projection))
        closest_x = line_start.x() + projection * line_dx
        closest_y = line_start.y() + projection * line_dy
        return math.hypot(point.x() - closest_x, point.y() - closest_y)

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
        self.refresh_dashboard(results=counts_snapshot, status_override="Processing")

        counts_text = self.format_counts_by_class(counts_snapshot["counts"])
        direction_text = self.format_all_lines_overview_text(counts_snapshot)
        source_name = self.selected_source.display_name if self.selected_source else "video source"
        stream_message = counts_snapshot.get("stream_message")

        if total_frames:
            self.set_status(
                f"Status: Processing {source_name}...\n"
                f"Progress: {processed_frames}/{total_frames} frames\n"
                f"{self.format_optional_stream_message(stream_message)}"
                f"Current total crossings: {counts_snapshot['total']}\n"
                f"Current counts by class: {counts_text}\n"
                f"Current line overview: {direction_text}"
            )
        else:
            self.set_status(
                f"Status: Processing {source_name}...\n"
                f"Frames processed: {processed_frames}\n"
                f"{self.format_optional_stream_message(stream_message)}"
                f"Current total crossings: {counts_snapshot['total']}\n"
                f"Current counts by class: {counts_text}\n"
                f"Current line overview: {direction_text}"
            )

        self.update_export_ui_state()

    def format_counting_status(self, results):
        counts_text = self.format_counts_by_class(results["counts"])
        direction_text = self.format_all_lines_overview_text(results)

        message = (
            "Status: Processing completed.\n"
            f"Frames processed: {results['processed_frames']}\n"
            f"Total crossings: {results['total']}\n"
            f"Counts by class: {counts_text}\n"
            f"Line overview: {direction_text}"
        )
        return self.append_annotated_video_status(message, results)

    def format_cancelled_counting_status(self, results):
        if results is None:
            return "Status: Counting stopped by user."

        counts_text = self.format_counts_by_class(results["counts"])
        direction_text = self.format_all_lines_overview_text(results)

        message = (
            "Status: Counting stopped by user.\n"
            f"Partial frames processed: {results['processed_frames']}\n"
            f"Partial total crossings: {results['total']}\n"
            f"Partial counts by class: {counts_text}\n"
            f"Partial line overview: {direction_text}"
        )
        return self.append_annotated_video_status(message, results)

    def update_counting_ui_state(self):
        self.start_counting_btn.setEnabled(not self.is_counting)
        self.stop_counting_btn.setEnabled(self.is_counting)
        self.source_type_combobox.setEnabled(not self.is_counting)
        self.source_input_stack.setEnabled(not self.is_counting)
        self.load_source_btn.setEnabled(not self.is_counting)
        self.browse_video_btn.setEnabled(
            not self.is_counting
            and self.source_type_combobox.currentData() == SOURCE_KIND_LOCAL_FILE
        )
        self.annotated_video_path_input.setEnabled(
            not self.is_counting and self.save_annotated_video_checkbox.isChecked()
        )
        self.browse_annotated_video_btn.setEnabled(
            not self.is_counting and self.save_annotated_video_checkbox.isChecked()
        )
        self.save_annotated_video_checkbox.setEnabled(not self.is_counting)
        self.active_line_combobox.setEnabled(True)
        self.draw_line_btn.setEnabled(not self.is_counting)
        self.clear_line_btn.setEnabled(not self.is_counting)
        self.direction_labels_btn.setEnabled(not self.is_counting)
        self.detect_btn.setEnabled(not self.is_counting)
        self.track_label_mode_combobox.setEnabled(not self.is_counting)
        self.show_line_labels_checkbox.setEnabled(not self.is_counting)
        self.show_direction_legend_checkbox.setEnabled(not self.is_counting)
        self.preset_combobox.setEnabled(not self.is_counting)
        self.confidence_spinbox.setEnabled(not self.is_counting)
        self.frame_skip_spinbox.setEnabled(not self.is_counting)
        self.model_size_combobox.setEnabled(not self.is_counting)
        self.low_latency_live_checkbox.setEnabled(not self.is_counting)
        for checkbox in self.class_checkboxes.values():
            checkbox.setEnabled(not self.is_counting)
        self.update_export_ui_state()

    def is_stop_requested(self):
        return self.stop_requested

    def start_counting_worker(self, settings, annotated_video_options):
        self.counting_thread = QThread(self)
        self.counting_worker = CountingWorker(
            video_source=self.selected_source,
            line_points=self.count_lines,
            settings=settings,
            track_label_mode=self.get_track_label_mode(),
            annotated_video_options=annotated_video_options,
        )
        self.counting_worker.moveToThread(self.counting_thread)

        self.counting_thread.started.connect(self.counting_worker.run)
        self.counting_worker.progress.connect(self.update_processing_progress)
        self.counting_worker.finished.connect(self.handle_counting_finished)
        self.counting_worker.finished.connect(self.counting_thread.quit)
        self.counting_thread.finished.connect(self.counting_worker.deleteLater)
        self.counting_thread.finished.connect(self.handle_thread_finished)

        self.counting_thread.start()

    def handle_counting_finished(self, latest_frame, results, processing_status):
        self.is_counting = False
        self.stop_requested = False
        self.update_counting_ui_state()

        if not isinstance(processing_status, dict):
            processing_status = {
                "code": PROCESSING_STATUS_ERROR,
                "message": str(processing_status) if processing_status else "Counting failed.",
            }

        status_code = (processing_status or {}).get("code", PROCESSING_STATUS_ERROR)
        status_message = (processing_status or {}).get("message")

        if status_code == PROCESSING_STATUS_CANCELLED:
            if latest_frame is not None:
                self.detected_preview_frame = latest_frame
                self.update_preview()
            self.count_results = results
            self.update_export_ui_state()
            self.refresh_dashboard(results=results, status_override="Stopped")
            self.set_status(self.format_cancelled_counting_status(results))
            return

        if status_code == PROCESSING_STATUS_ERROR:
            self.update_export_ui_state()
            self.refresh_dashboard(results=results, status_override="Error")
            self.set_status(f"Status: {status_message or 'Counting failed.'}")
            return

        self.detected_preview_frame = latest_frame
        self.count_results = results
        self.update_preview()
        self.update_export_ui_state()

        if status_code == PROCESSING_STATUS_STREAM_STOPPED:
            self.refresh_dashboard(results=results, status_override="Stream stopped")
            self.set_status(self.format_stream_stopped_status(results, status_message))
            return

        self.refresh_dashboard(results=results, status_override="Completed")
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

    def format_direction_counts(self, direction_counts, line_key=None):
        direction_labels = self.direction_labels_by_line.get(
            line_key or self.active_line_key,
            self.default_direction_labels(),
        )
        parts = []
        for direction_key, direction_label in direction_labels.items():
            counts_text = ", ".join(
                f"{class_name}: {count}"
                for class_name, count in direction_counts.get(direction_key, {}).items()
                if count > 0
            )
            if not counts_text:
                counts_text = "None"
            parts.append(f"{self.get_direction_panel_title(direction_key, line_key)} [{counts_text}]")

        return "; ".join(parts)

    def get_dashboard_metric_labels(self):
        return (
            ("total", "Total"),
            ("car", "Car"),
            ("motorcycle", "Motorcycle"),
            ("bus", "Bus"),
            ("truck", "Truck"),
            ("bicycle", "Bicycle"),
        )

    def format_counts_by_class(self, counts):
        counts_text = ", ".join(
            f"{class_name}: {count}"
            for class_name, count in counts.items()
            if count > 0
        )
        if not counts_text:
            return "None"
        return counts_text

    def format_all_lines_overview_text(self, results):
        parts = []
        for line_key in DEFAULT_LINE_KEYS:
            line_result = results.get("line_results", {}).get(line_key)
            if line_result is None:
                continue
            direction_a_total = sum(
                line_result.get("direction_counts", {})
                .get(DIRECTION_NEGATIVE_TO_POSITIVE, {})
                .values()
            )
            direction_b_total = sum(
                line_result.get("direction_counts", {})
                .get(DIRECTION_POSITIVE_TO_NEGATIVE, {})
                .values()
            )
            parts.append(
                f"{LINE_DISPLAY_NAMES[line_key]} total {line_result.get('total', 0)} "
                f"(A {direction_a_total}, B {direction_b_total})"
            )
        return "; ".join(parts) if parts else "No lines defined"

    def format_line_label_overview(self, line_key):
        direction_labels = self.direction_labels_by_line.get(
            line_key,
            self.default_direction_labels(),
        )
        return (
            f"{direction_labels[DIRECTION_NEGATIVE_TO_POSITIVE]} | "
            f"{direction_labels[DIRECTION_POSITIVE_TO_NEGATIVE]}"
        )

    def apply_line_overview_row_style(self, line_key):
        is_selected = line_key == self.active_line_key
        role = "selectedCell" if is_selected else "tableCell"
        for widget in self.line_overview_widgets[line_key].values():
            widget.setProperty("role", role)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        for widget in self.line_class_overview_widgets[line_key].values():
            widget.setProperty("role", role)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def refresh_dashboard(self, results=None, status_override=None):
        if not self.dashboard_widgets_ready:
            return

        dashboard_results = results or self.count_results or self.build_empty_dashboard_results()
        source_text = (
            self.selected_source.display_name if self.selected_source is not None else "No source loaded"
        )
        current_status = status_override or self.get_dashboard_status_text()

        self.summary_value_labels["source"].setText(source_text)
        self.summary_value_labels["status"].setText(current_status)
        self.summary_value_labels["processed_frames"].setText(
            str(dashboard_results.get("processed_frames", 0))
        )
        self.summary_value_labels["total_crossings"].setText(
            str(dashboard_results.get("total", 0))
        )
        self.overall_class_chip_labels["total"].setText(str(dashboard_results.get("total", 0)))
        overall_counts = dashboard_results.get("counts", {})
        for class_name in config.DEFAULT_ENABLED_CLASSES:
            self.overall_class_chip_labels[class_name].setText(
                str(overall_counts.get(class_name, 0))
            )

        active_line_result = dashboard_results.get("line_results", {}).get(
            self.active_line_key,
            self.build_empty_line_dashboard_result(self.active_line_key),
        )
        active_direction_counts = active_line_result.get("direction_counts", {})
        active_direction_labels = self.direction_labels_by_line[self.active_line_key]
        self.active_line_detail_labels["selected_line"].setText(self.get_active_line_name())
        self.active_line_detail_labels["direction_a_label"].setText(
            active_direction_labels[DIRECTION_NEGATIVE_TO_POSITIVE]
        )
        self.active_line_detail_labels["direction_b_label"].setText(
            active_direction_labels[DIRECTION_POSITIVE_TO_NEGATIVE]
        )
        for direction_key, section in self.direction_section_widgets.items():
            section["group"].setTitle(self.get_direction_panel_title(direction_key, self.active_line_key))
            section_counts = active_direction_counts.get(direction_key, {})
            section["labels"]["total"].setText(
                str(sum(section_counts.get(class_name, 0) for class_name in config.DEFAULT_ENABLED_CLASSES))
            )
            for class_name in config.DEFAULT_ENABLED_CLASSES:
                section["labels"][class_name].setText(str(section_counts.get(class_name, 0)))

        for line_key, widgets in self.line_overview_widgets.items():
            line_result = dashboard_results.get("line_results", {}).get(
                line_key,
                self.build_empty_line_dashboard_result(line_key),
            )
            widgets["line"].setText(LINE_SHORT_NAMES[line_key])
            widgets["name"].setText(self.format_line_label_overview(line_key))
            widgets["total"].setText(str(line_result.get("total", 0)))
            widgets["direction_a"].setText(
                str(
                    sum(
                        line_result.get("direction_counts", {})
                        .get(DIRECTION_NEGATIVE_TO_POSITIVE, {})
                        .values()
                    )
                )
            )
            self.apply_line_overview_row_style(line_key)
            widgets["direction_b"].setText(
                str(
                    sum(
                        line_result.get("direction_counts", {})
                        .get(DIRECTION_POSITIVE_TO_NEGATIVE, {})
                        .values()
                    )
                )
            )
            self.line_class_overview_widgets[line_key]["line"].setText(LINE_SHORT_NAMES[line_key])
            self.line_class_overview_widgets[line_key]["total"].setText(
                str(line_result.get("total", 0))
            )
            for class_name in config.DEFAULT_ENABLED_CLASSES:
                self.line_class_overview_widgets[line_key][class_name].setText(
                    str(line_result.get("counts", {}).get(class_name, 0))
                )

        for class_name, value_label in self.overall_count_labels.items():
            value_label.setText(str(overall_counts.get(class_name, 0)))

        active_settings = self.count_settings or self.get_dashboard_settings_snapshot()
        self.run_settings_value_labels["preset_name"].setText(
            str(active_settings.get("preset_name", self.active_preset_name))
        )
        self.run_settings_value_labels["model_size"].setText(
            str(active_settings.get("model_size_label", self.get_model_display_label()))
        )
        self.run_settings_value_labels["confidence_threshold"].setText(
            f"{float(active_settings.get('confidence_threshold', self.confidence_spinbox.value())):.2f}"
        )
        self.run_settings_value_labels["frame_skip"].setText(
            str(active_settings.get("frame_skip", self.frame_skip_spinbox.value()))
        )
        self.run_settings_value_labels["low_latency"].setText(
            "On"
            if active_settings.get(
                "prioritize_low_latency_live_streams",
                self.low_latency_live_checkbox.isChecked(),
            )
            else "Off"
        )
        self.run_settings_value_labels["annotated_video"].setText(
            "On" if active_settings.get("annotated_video_enabled") else "Off"
        )

    def build_empty_dashboard_results(self):
        return {
            "total": 0,
            "counts": {class_name: 0 for class_name in config.DEFAULT_ENABLED_CLASSES},
            "direction_counts": {
                DIRECTION_NEGATIVE_TO_POSITIVE: {
                    class_name: 0 for class_name in config.DEFAULT_ENABLED_CLASSES
                },
                DIRECTION_POSITIVE_TO_NEGATIVE: {
                    class_name: 0 for class_name in config.DEFAULT_ENABLED_CLASSES
                },
            },
            "line_results": {
                line_key: self.build_empty_line_dashboard_result(line_key)
                for line_key in DEFAULT_LINE_KEYS
            },
            "processed_frames": 0,
        }

    def build_empty_line_dashboard_result(self, line_key):
        return {
            "line_key": line_key,
            "total": 0,
            "counts": {class_name: 0 for class_name in config.DEFAULT_ENABLED_CLASSES},
            "direction_counts": {
                DIRECTION_NEGATIVE_TO_POSITIVE: {
                    class_name: 0 for class_name in config.DEFAULT_ENABLED_CLASSES
                },
                DIRECTION_POSITIVE_TO_NEGATIVE: {
                    class_name: 0 for class_name in config.DEFAULT_ENABLED_CLASSES
                },
            },
        }

    def get_dashboard_status_text(self):
        if self.is_counting:
            return "Processing"
        if self.count_results is not None:
            return "Ready"
        if self.selected_source is not None:
            return "Preview loaded"
        return "Waiting"

    def get_dashboard_settings_snapshot(self):
        return {
            "preset_name": self.active_preset_name,
            "model_size": self.get_model_size_key(),
            "model_size_label": self.get_model_display_label(),
            "confidence_threshold": self.confidence_spinbox.value(),
            "frame_skip": self.frame_skip_spinbox.value(),
            "prioritize_low_latency_live_streams": self.low_latency_live_checkbox.isChecked(),
            "annotated_video_enabled": self.save_annotated_video_checkbox.isChecked(),
        }

    def default_direction_labels(self):
        return {
            DIRECTION_NEGATIVE_TO_POSITIVE: "A -> B",
            DIRECTION_POSITIVE_TO_NEGATIVE: "B -> A",
        }

    def format_direction_label_summary(self, line_key=None):
        direction_labels = self.direction_labels_by_line.get(
            line_key or self.active_line_key,
            self.default_direction_labels(),
        )
        return (
            f"{direction_labels[DIRECTION_NEGATIVE_TO_POSITIVE]} (A to B); "
            f"{direction_labels[DIRECTION_POSITIVE_TO_NEGATIVE]} (B to A)"
        )

    def get_direction_panel_title(self, direction_key, line_key=None):
        orientation_text = (
            "A -> B"
            if direction_key == DIRECTION_NEGATIVE_TO_POSITIVE
            else "B -> A"
        )
        direction_labels = self.direction_labels_by_line.get(
            line_key or self.active_line_key,
            self.default_direction_labels(),
        )
        label_text = direction_labels[direction_key]
        if label_text == orientation_text:
            return orientation_text
        return f"{label_text} ({orientation_text})"

    def format_source_loaded_status(self, source):
        source_kind_label = self.get_source_type_label(source)
        live_mode_text = ""
        if source.is_live:
            mode_label = (
                "Low Latency"
                if self.low_latency_live_checkbox.isChecked()
                else "Higher Accuracy"
            )
            live_mode_text = f"\nLive mode: {mode_label}\n"
        return (
            f"Selected source: {source.display_name}\n"
            f"Source type: {source_kind_label}\n"
            f"Active preset: {self.active_preset_name}\n"
            f"Model: {self.get_model_display_label()}\n"
            f"{live_mode_text}"
            "Status: Preview loaded successfully.\n"
            "Next: place a count line, then start counting."
        )

    def format_stream_stopped_status(self, results, status_message):
        if results is None:
            return f"Status: {status_message or 'The stream stopped.'}"

        counts_text = self.format_counts_by_class(results["counts"])
        direction_text = self.format_all_lines_overview_text(results)

        message = (
            f"Status: {status_message or 'The stream stopped.'}\n"
            f"Frames processed: {results['processed_frames']}\n"
            f"Total crossings so far: {results['total']}\n"
            f"Counts by class: {counts_text}\n"
            f"Line overview: {direction_text}"
        )
        return self.append_annotated_video_status(message, results)

    def format_optional_stream_message(self, stream_message):
        if not stream_message:
            return ""
        return f"{stream_message}\n"

    def append_annotated_video_status(self, message, results):
        annotated_video = (results or {}).get("annotated_video")
        if not annotated_video or not annotated_video.get("enabled"):
            return message
        status_prefix = (
            "Annotated video save failed"
            if annotated_video.get("failed")
            else "Annotated video save completed"
        )
        return f"{message}\n{status_prefix}: {annotated_video.get('message', '')}"

    def get_export_source_details(self):
        if self.selected_source is None:
            return {}

        return {
            "source_kind": self.selected_source.source_kind,
            "display_name": self.selected_source.display_name,
            "original_input": self.selected_source.original_input,
            "playable_input": self.selected_source.playable_input,
            "is_live": self.selected_source.is_live,
            "stream_format": self.selected_source.stream_format,
        }

    def build_settings_payload(self, enabled_classes):
        settings = normalize_settings(
            {
                "confidence_threshold": self.confidence_spinbox.value(),
                "frame_skip": self.frame_skip_spinbox.value(),
                "model_size": self.get_model_size_key(),
                "enabled_classes": enabled_classes,
                "prioritize_low_latency_live_streams": self.low_latency_live_checkbox.isChecked(),
                "motorcycle_tracking": self.active_preset_name == "Motorcycle Focus",
            }
        )
        settings["preset_name"] = self.active_preset_name
        settings["model_size_label"] = self.get_model_display_label()
        settings["annotated_video_enabled"] = self.save_annotated_video_checkbox.isChecked()
        return settings

    def get_source_type_label(self, source):
        if source.source_kind == SOURCE_KIND_YOUTUBE_URL and source.is_live:
            return "YouTube live stream"
        if source.source_kind == SOURCE_KIND_YOUTUBE_URL:
            return "YouTube video"
        if source.source_kind == SOURCE_KIND_DIRECT_STREAM:
            stream_labels = {
                STREAM_FORMAT_MJPEG: "Direct MJPEG stream",
                STREAM_FORMAT_HLS: "Direct HLS stream",
                STREAM_FORMAT_RTSP: "Direct RTSP stream",
            }
            return stream_labels.get(source.stream_format, "Direct camera stream")
        return "Local video file"

    def get_active_settings(self):
        enabled_classes = [
            class_name
            for class_name, checkbox in self.class_checkboxes.items()
            if checkbox.isChecked()
        ]
        if not enabled_classes:
            self.set_status("Status: Select at least one class in the settings area.")
            return None

        return self.build_settings_payload(enabled_classes)

    def get_export_settings(self):
        if self.count_settings is not None:
            return self.count_settings
        settings = self.get_active_settings()
        if settings is not None:
            return settings
        return self.build_settings_payload(list(self.class_checkboxes.keys()))
