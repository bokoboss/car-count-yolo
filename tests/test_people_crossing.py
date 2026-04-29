import unittest

import _path  # noqa: F401

from vehicle_counter.tracking import did_cross_for_class, did_cross_line


LINE_START = (0.0, 0.0)
LINE_END = (10.0, 0.0)


class PeopleCrossingTest(unittest.TestCase):
    def test_person_touching_line_is_not_a_crossing(self):
        self.assertFalse(
            did_cross_for_class(
                "person",
                (5.0, -8.0),
                (5.0, 0.0),
                LINE_START,
                LINE_END,
            )
        )

    def test_person_hovering_near_line_is_not_a_crossing(self):
        self.assertFalse(
            did_cross_for_class(
                "person",
                (5.0, -1.0),
                (5.0, 1.0),
                LINE_START,
                LINE_END,
            )
        )

    def test_person_must_move_clearly_to_opposite_side(self):
        self.assertTrue(
            did_cross_for_class(
                "person",
                (5.0, -3.0),
                (5.0, 3.0),
                LINE_START,
                LINE_END,
            )
        )

    def test_vehicle_crossing_behavior_still_counts_line_touch(self):
        self.assertTrue(
            did_cross_line(
                (5.0, -8.0),
                (5.0, 0.0),
                LINE_START,
                LINE_END,
            )
        )


if __name__ == "__main__":
    unittest.main()
