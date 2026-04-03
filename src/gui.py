import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt
import config

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setGeometry(100, 100, config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
        self.setup_ui()

    def setup_ui(self):
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Button layout
        button_layout = QHBoxLayout()

        self.open_video_btn = QPushButton("Open Video")
        self.open_video_btn.clicked.connect(self.open_video)
        button_layout.addWidget(self.open_video_btn)

        self.draw_line_btn = QPushButton("Draw Count Line")
        self.draw_line_btn.clicked.connect(self.draw_count_line)
        button_layout.addWidget(self.draw_line_btn)

        self.start_counting_btn = QPushButton("Start Counting")
        self.start_counting_btn.clicked.connect(self.start_counting)
        button_layout.addWidget(self.start_counting_btn)

        self.export_results_btn = QPushButton("Export Results")
        self.export_results_btn.clicked.connect(self.export_results)
        button_layout.addWidget(self.export_results_btn)

        main_layout.addLayout(button_layout)

        # Preview area (placeholder)
        self.preview_label = QLabel("Preview Area - Video will appear here")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid black; background-color: lightgray;")
        self.preview_label.setMinimumHeight(300)
        main_layout.addWidget(self.preview_label)

        # Status/Message area
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(100)
        self.status_text.setPlainText("Welcome to Vehicle Counter! Select a video to begin.")
        main_layout.addWidget(self.status_text)

    # Placeholder button handlers
    def open_video(self):
        QMessageBox.information(self, "Open Video", "Open Video functionality not implemented yet.")

    def draw_count_line(self):
        QMessageBox.information(self, "Draw Count Line", "Draw Count Line functionality not implemented yet.")

    def start_counting(self):
        QMessageBox.information(self, "Start Counting", "Start Counting functionality not implemented yet.")

    def export_results(self):
        QMessageBox.information(self, "Export Results", "Export Results functionality not implemented yet.")