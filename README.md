# Vehicle Counter

A simple desktop application for counting vehicles in videos using YOLO object detection.

## Prerequisites

You need Python installed on your Windows computer. If you don't have it, download and install Python 3.10 or later from the official website: https://www.python.org/downloads/

During installation, make sure to check the box "Add Python to PATH".

## Setup Instructions

### 1. Create a Virtual Environment

A virtual environment keeps this project's dependencies separate from your system Python.

1. Open Command Prompt or PowerShell (search for "cmd" or "powershell" in Windows search).
2. Navigate to your project folder:
   ```
   cd C:\MyRD\car-count-yolo
   ```
3. Create a virtual environment:
   ```
   python -m venv venv
   ```
4. Activate the virtual environment:
   ```
   venv\Scripts\activate
   ```
   You should see `(venv)` at the beginning of your command prompt.

### 2. Install Dependencies

With the virtual environment activated, install the required packages:

```
pip install -r requirements.txt
```

This will install PyQt6, which is needed for the graphical user interface.

### 3. Run the Application

Still in the activated virtual environment, run:

```
python src/main.py
```

## What You Should See

- A window titled "Vehicle Counter" should open.
- The window should have four buttons: "Open Video", "Draw Count Line", "Start Counting", "Export Results".
- Below the buttons, there should be a gray preview area with text "Preview Area - Video will appear here".
- At the bottom, there should be a text area with the message "Welcome to Vehicle Counter! Select a video to begin."
- Clicking any button should show a message box saying the functionality is not implemented yet.

## Troubleshooting

- If you get an error about "python" not being recognized, make sure Python is installed and added to PATH.
- If PyQt6 installation fails, try updating pip first: `python -m pip install --upgrade pip`
- If the window doesn't open, check that you're running from the correct directory and virtual environment is activated.

## Next Steps

This is Phase 1 of the project. Future phases will add video processing, YOLO detection, and counting functionality.