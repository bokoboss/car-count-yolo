import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook


def build_export_rows(results, source_details, direction_labels, settings):
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_details = source_details or {}
    source_display_name = source_details.get("display_name") or get_source_label(
        source_details.get("original_input")
    )
    source_kind = source_details.get("source_kind") or "unknown"

    rows = [
        ("source_display_name", source_display_name or "Unknown"),
        ("source_kind", source_kind),
        ("source_input", source_details.get("original_input") or ""),
        ("source_is_live", source_details.get("is_live", False)),
        ("source_stream_format", source_details.get("stream_format") or ""),
        ("exported_at", export_time),
        ("total_crossings", results["total"]),
        ("processed_frames", results.get("processed_frames", "")),
    ]

    for direction_key, direction_label in (direction_labels or {}).items():
        if isinstance(direction_label, str):
            rows.append((f"direction_label_{direction_key}", direction_label))

    for setting_name, setting_value in settings.items():
        if setting_name == "enabled_classes":
            setting_value = ", ".join(setting_value)
        rows.append((f"setting_{setting_name}", setting_value))

    for class_name, count in results["counts"].items():
        rows.append((f"class_{class_name}", count))

    for direction_name, direction_counts in results.get("direction_counts", {}).items():
        direction_label = {
            "negative_to_positive": "direction_a",
            "positive_to_negative": "direction_b",
        }.get(direction_name, direction_name)
        safe_direction_label = direction_label.lower().replace(" ", "_")
        for class_name, count in direction_counts.items():
            rows.append((f"direction_{safe_direction_label}_{class_name}", count))

    for line_key, line_result in results.get("line_results", {}).items():
        line_labels = (direction_labels or {}).get(line_key, {})
        rows.append((f"{line_key}_total_crossings", line_result.get("total", 0)))
        rows.append(
            (
                f"{line_key}_direction_a_label",
                line_labels.get("negative_to_positive", "A -> B"),
            )
        )
        rows.append(
            (
                f"{line_key}_direction_b_label",
                line_labels.get("positive_to_negative", "B -> A"),
            )
        )
        rows.append(
            (
                f"{line_key}_direction_a_total",
                sum(
                    line_result.get("direction_counts", {})
                    .get("negative_to_positive", {})
                    .values()
                ),
            )
        )
        rows.append(
            (
                f"{line_key}_direction_b_total",
                sum(
                    line_result.get("direction_counts", {})
                    .get("positive_to_negative", {})
                    .values()
                ),
            )
        )

        for class_name, count in line_result.get("counts", {}).items():
            rows.append((f"{line_key}_class_{class_name}", count))

        for class_name, count in (
            line_result.get("direction_counts", {})
            .get("negative_to_positive", {})
            .items()
        ):
            rows.append((f"{line_key}_direction_a_{class_name}", count))

        for class_name, count in (
            line_result.get("direction_counts", {})
            .get("positive_to_negative", {})
            .items()
        ):
            rows.append((f"{line_key}_direction_b_{class_name}", count))

    return rows


def export_results_file(file_path, results, source_details, direction_labels, settings):
    suffix = Path(file_path).suffix.lower()
    rows = build_export_rows(results, source_details, direction_labels, settings)

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


def get_source_label(source_input):
    if not source_input:
        return None

    parsed = urlparse(source_input)
    if parsed.scheme in {"http", "https"}:
        return source_input

    return Path(source_input).name
