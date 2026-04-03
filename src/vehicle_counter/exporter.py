import csv
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook


def build_export_rows(results, source_video_path, direction_labels, settings):
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_video_name = Path(source_video_path).name if source_video_path else "Unknown"

    rows = [
        ("source_video_file", source_video_name),
        ("exported_at", export_time),
        ("total_crossings", results["total"]),
        ("processed_frames", results.get("processed_frames", "")),
    ]

    for direction_key, direction_label in direction_labels.items():
        rows.append((f"direction_label_{direction_key}", direction_label))

    for setting_name, setting_value in settings.items():
        if setting_name == "enabled_classes":
            setting_value = ", ".join(setting_value)
        rows.append((f"setting_{setting_name}", setting_value))

    for class_name, count in results["counts"].items():
        rows.append((f"class_{class_name}", count))

    for direction_name, direction_counts in results.get("direction_counts", {}).items():
        direction_label = direction_labels.get(direction_name, direction_name)
        safe_direction_label = direction_label.lower().replace(" ", "_")
        for class_name, count in direction_counts.items():
            rows.append((f"direction_{safe_direction_label}_{class_name}", count))

    return rows


def export_results_file(file_path, results, source_video_path, direction_labels, settings):
    suffix = Path(file_path).suffix.lower()
    rows = build_export_rows(results, source_video_path, direction_labels, settings)

    if suffix == ".csv":
        write_csv(file_path, rows)
        return None

    if suffix == ".xlsx":
        write_xlsx(file_path, rows)
        return None

    return "Unsupported export format. Please choose a .csv or .xlsx file."


def write_csv(file_path, rows):
    with open(file_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["field", "value"])
        writer.writerows(rows)


def write_xlsx(file_path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(["field", "value"])

    for row in rows:
        sheet.append(list(row))

    workbook.save(file_path)
