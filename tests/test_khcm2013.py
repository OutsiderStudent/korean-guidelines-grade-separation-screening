import unittest

from interchange_review.khcm2013 import (
    SaturationFlowInputs,
    combined_turn_adjustment_factor,
    grade_adjustment_factor,
    heavy_vehicle_adjustment_factor,
    lane_width_adjustment_factor,
    left_turn_equivalent,
    left_turn_radius_equivalent,
    saturation_flow,
    turn_adjustment_factor,
    u_turn_equivalent,
)


class Khcm2013FactorTest(unittest.TestCase):
    def test_heavy_vehicle_equation_8_39(self) -> None:
        self.assertAlmostEqual(heavy_vehicle_adjustment_factor(0.20), 1 / 1.16)

    def test_turn_equation_8_26(self) -> None:
        self.assertAlmostEqual(turn_adjustment_factor(0.10, 2.0), 1 / 1.10)

    def test_combined_turn_equation_8_26(self) -> None:
        expected = 1 / (1 + 0.10 * (2.0 - 1) + 0.20 * (1.5 - 1))
        self.assertAlmostEqual(
            combined_turn_adjustment_factor(0.10, 2.0, 0.20, 1.5),
            expected,
        )

    def test_lane_width_table_8_15(self) -> None:
        self.assertEqual(lane_width_adjustment_factor(2.6), 0.88)
        self.assertEqual(lane_width_adjustment_factor(2.8), 0.94)
        self.assertEqual(lane_width_adjustment_factor(3.0), 1.00)

    def test_grade_table_8_16_interpolation(self) -> None:
        self.assertEqual(grade_adjustment_factor(0), 1.00)
        self.assertEqual(grade_adjustment_factor(3), 0.96)
        self.assertAlmostEqual(grade_adjustment_factor(4.5), 0.945)
        self.assertEqual(grade_adjustment_factor(6), 0.93)

    def test_left_turn_tables_and_equation_8_6(self) -> None:
        radius = left_turn_radius_equivalent(12)
        u_turn = u_turn_equivalent(15, 1)
        self.assertEqual(radius, 1.11)
        self.assertAlmostEqual(u_turn, 1.30)
        self.assertAlmostEqual(left_turn_equivalent(1.0, radius, u_turn), 1.443)

    def test_saturation_flow_equation_8_28(self) -> None:
        inputs = SaturationFlowInputs(
            lane_count=2,
            turn_factor=0.90,
            lane_width_factor=1.00,
            grade_factor=0.96,
            heavy_vehicle_factor=heavy_vehicle_adjustment_factor(0.20),
        )
        expected = 2_200 * 2 * 0.90 * 1.00 * 0.96 * (1 / 1.16)
        self.assertAlmostEqual(saturation_flow(inputs), expected)


if __name__ == "__main__":
    unittest.main()
