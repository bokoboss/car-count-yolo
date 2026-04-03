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

This will install PyQt6 for the graphical user interface, OpenCV for video preview, Ultralytics YOLO for detection and tracking, and `openpyxl` for Excel export.

### 3. Run the Application

Still in the activated virtual environment, run this command from the project root:

```
python -m src.vehicle_counter
```

This runs the app as a Python package, which makes imports consistent and avoids errors like `ModuleNotFoundError: No module named 'config'`.

## Test The Video Preview

1. Start the app:
   ```
   python -m src.vehicle_counter
   ```
2. Click `Open Video`.
3. Choose a local `.mp4`, `.avi`, `.mov`, or `.mkv` file.
4. Confirm that the first frame appears in the preview area.
5. Check that the status area shows the selected file name and a success message.
6. Try cancelling the dialog or choosing an invalid file type to confirm the error handling messages appear.

## Test Single-Frame Detection

1. Start the app:
   ```
   python -m src.vehicle_counter
   ```
2. Click `Open Video` and choose a video file.
3. After the first frame appears, click `Detect Vehicles`.
4. Wait a moment while the YOLO model loads. On the first run, Ultralytics may download model weights automatically.
5. Check that bounding boxes appear on the current preview image.
6. Check that the status area shows the total detected objects and counts by class.

## What You Should See

- A window titled "Vehicle Counter" should open.
- The window should have seven buttons: "Open Video", "Draw Count Line", "Clear Count Line", "Detect Vehicles", "Start Counting", "Stop Counting", "Export Results".
- Below the buttons, there should be a gray preview area with text "Preview Area - Video will appear here".
- At the bottom, there should be a text area with the message "Welcome to Vehicle Counter! Select a video to begin."
- Clicking `Open Video` should let you choose a video file and show the first frame in the preview area.
- Clicking `Draw Count Line` should let you place one line on the preview image.
- Clicking `Detect Vehicles` should run detection on the current preview image only.
- Clicking `Export Results` should save the current in-memory counting results to `.csv` or `.xlsx` after results are available.

## Troubleshooting

- If you get an error about "python" not being recognized, make sure Python is installed and added to PATH.
- If PyQt6 installation fails, try updating pip first: `python -m pip install --upgrade pip`
- If `cv2` is missing, reinstall dependencies with `pip install -r requirements.txt`.
- If the YOLO model cannot load on first use, check that `ultralytics` installed correctly and that the machine can download model weights if they are not cached yet.
- If `.xlsx` export fails, check that `openpyxl` installed correctly with `pip install -r requirements.txt`.
- If the window doesn't open, check that you're in `C:\MyRD\car-count-yolo`, the virtual environment is activated, and you are using `python -m src.vehicle_counter`.

## Next Steps

This is still an early phase of the project. Future phases will add multi-frame processing, tracking, and counting logic.
