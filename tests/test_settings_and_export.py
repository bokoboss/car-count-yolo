import unittest

import _path  # noqa: F401

from vehicle_counter import config
from vehicle_counter.detection import normalize_settings
from vehicle_counter.exporter import build_export_tables
from vehicle_counter.tracking import (
    DIRECTION_NEGATIVE_TO_POSITIVE,
    build_empty_counts,
    is_duplicate_recent_crossing,
    remember_recent_crossing,
)


class SettingsNormalizationTest(unittest.TestCase):
    def test_people_mode_falls_back_to_person_only(self):
        settings = normalize_settings(
            {
                "counting_mode": config.COUNTING_MODE_PEOPLE,
                "enabled_classes": ["car"],
            }
        )

        self.assertEqual(settings["counting_mode"], config.COUNTING_MODE_PEOPLE)
        self.assertEqual(settings["enabled_classes"], ["person"])

    def test_vehicle_mode_filters_out_person(self):
        settings = normalize_settings(
            {
                "counting_mode": config.COUNTING_MODE_VEHICLE,
                "enabled_classes": ["person", "car"],
            }
        )

        self.assertEqual(settings["enabled_classes"], ["car"])

    def test_performance_options_are_normalized(self):
        settings = normalize_settings(
            {
                "imgsz": 2000,
                "device": "cpu",
                "half": "yes",
                "preview_render_mode": config.PREVIEW_RENDER_RAW,
            }
        )

        self.assertEqual(settings["imgsz"], 1280)
        self.assertEqual(settings["device"], "cpu")
        self.assertTrue(settings["half"])
        self.assertEqual(settings["preview_render_mode"], config.PREVIEW_RENDER_RAW)


class DuplicateCrossingGuardTest(unittest.TestCase):
    def test_recent_same_class_direction_and_position_is_duplicate(self):
        counts = build_empty_counts(line_keys=("line_1",))
        remember_recent_crossing(
            counts=counts,
            line_key="line_1",
            class_name="person",
            direction=DIRECTION_NEGATIVE_TO_POSITIVE,
            crossing_point=(100.0, 200.0),
            frame_index=10,
        )

        self.assertTrue(
            is_duplicate_recent_crossing(
                counts=counts,
                line_key="line_1",
                class_name="person",
                direction=DIRECTION_NEGATIVE_TO_POSITIVE,
                crossing_point=(108.0, 207.0),
                frame_index=14,
            )
        )

    def test_far_crossing_is_not_duplicate(self):
        counts = build_empty_counts(line_keys=("line_1",))
        remember_recent_crossing(
            counts=counts,
            line_key="line_1",
            class_name="person",
            direction=DIRECTION_NEGATIVE_TO_POSITIVE,
            crossing_point=(100.0, 200.0),
            frame_index=10,
        )

        self.assertFalse(
            is_duplicate_recent_crossing(
                counts=counts,
                line_key="line_1",
                class_name="person",
                direction=DIRECTION_NEGATIVE_TO_POSITIVE,
                crossing_point=(220.0, 200.0),
                frame_index=14,
            )
        )


class ExportSchemaTest(unittest.TestCase):
    def test_event_export_prefers_count_class_and_keeps_person(self):
        export_data = build_export_tables(
            results={
                "counts": {"person": 1},
                "processed_frames": 12,
                "total": 1,
                "line_results": {},
                "events": [
                    {
                        "event_id": "EVT-000001",
                        "line_id": "line_1",
                        "direction": DIRECTION_NEGATIVE_TO_POSITIVE,
                        "count_class": "person",
                        "vehicle_class": "car",
                        "track_id": 7,
                        "frame_index": 12,
                        "elapsed_seconds": 1.1,
                        "event_timecode": "00:00:01.100",
                    }
                ],
            },
            source_details={"display_name": "sample"},
            direction_labels={},
            settings={"counting_mode": config.COUNTING_MODE_PEOPLE},
        )

        self.assertEqual(export_data["events"][0]["count_class"], "person")
        self.assertEqual(export_data["summary"][0]["overall_person"], 1)


if __name__ == "__main__":
    unittest.main()
