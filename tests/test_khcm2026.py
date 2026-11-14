import unittest

from interchange_review.khcm2026 import (
    BASE_SATURATION_FLOW,
    automatic_factors,
    grade_adjustment_factor,
    heavy_vehicle_adjustment_factor,
    lane_capacity,
    lane_saturation_flow,
    lane_width_adjustment_factor,
    movement_adjustment_factor,
    permissive_left_equivalent,
    protected_left_equivalent,
    right_turn_equivalent,
)


class Khcm2026FactorTest(unittest.TestCase):
    def test_base_conditions(self) -> None:
        factors = automatic_factors(
            left_proportion=0,
            through_proportion=1,
            right_proportion=0,
            heavy_proportion=0,
        )
        self.assertEqual(factors.total, 1.0)
        self.assertEqual(lane_saturation_flow(factors), BASE_SATURATION_FLOW)

    def test_table_8_4_factors(self) -> None:
        self.assertAlmostEqual(grade_adjustment_factor(3), 0.964)
        self.assertAlmostEqual(lane_width_adjustment_factor(2.8), 0.93)
        self.assertAlmostEqual(heavy_vehicle_adjustment_factor(0.2), 1 / 1.16)

    def test_movement_factor_uses_weighted_equivalents(self) -> None:
        value = movement_adjustment_factor(
            0.2,
            0.6,
            0.2,
            left_equivalent_value=1.08,
            right_equivalent_value=1.2,
        )
        self.assertAlmostEqual(value, 1 / (0.2 * 1.08 + 0.6 + 0.2 * 1.2))

    def test_table_8_13_and_8_14_values(self) -> None:
        self.assertEqual(protected_left_equivalent(radius_m=13), 1.11)
        self.assertEqual(protected_left_equivalent(radius_m=16), 1.08)
        self.assertEqual(protected_left_equivalent(radius_m=19), 1.05)
        self.assertEqual(protected_left_equivalent(radius_m=20), 1.0)
        self.assertEqual(right_turn_equivalent("green"), 1.2)
        self.assertEqual(right_turn_equivalent("red"), 2.0)
        self.assertEqual(permissive_left_equivalent(0), 1.53)

    def test_lane_capacity_equation_8_2(self) -> None:
        self.assertEqual(lane_capacity(2_200, 36, 80), 990)


if __name__ == "__main__":
    unittest.main()
