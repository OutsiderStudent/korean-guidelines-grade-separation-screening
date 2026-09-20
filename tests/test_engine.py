import unittest
from dataclasses import replace

from interchange_review import (
    Area,
    CorrectionFactors,
    DirectionInput,
    SignalAssumptions,
    calculate_direction,
    classify_capacity_area,
    round_to_hundred,
)


class GuidelineExampleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.signal = SignalAssumptions(
            cycle_seconds=80,
            effective_green_seconds=36,
            left_turn_vehicles_per_cycle=2,
            added_right_turn_capacity=600,
            utilization_factor=0.9,
        )
        self.direction_1 = calculate_direction(
            DirectionInput(
                name="① 방향",
                daily_traffic=44_000,
                peak_hour_factor_k=0.1,
                directional_factor=0.5,
                total_lanes=4,
                left_turn_percent=10,
                right_turn_percent=20,
                heavy_vehicle_percent=20,
                correction_factors=CorrectionFactors(0.910, 0.905, 0.850),
            ),
            self.signal,
        )
        self.direction_2 = calculate_direction(
            DirectionInput(
                name="② 방향",
                daily_traffic=36_000,
                peak_hour_factor_k=0.1,
                directional_factor=0.5,
                total_lanes=4,
                left_turn_percent=20,
                right_turn_percent=20,
                heavy_vehicle_percent=20,
                correction_factors=CorrectionFactors(0.820, 0.905, 0.850),
            ),
            self.signal,
        )

    def test_reproduces_guideline_example_values(self) -> None:
        self.assertEqual(self.direction_1.hourly_design_traffic_q, 2_200)
        self.assertEqual(self.direction_2.hourly_design_traffic_q, 1_800)
        self.assertEqual(self.direction_1.segment_capacity_c, 3_600)
        self.assertEqual(self.direction_2.segment_capacity_c, 3_600)
        self.assertAlmostEqual(self.direction_1.no_turn_lane_capacity_p_raw, 2_268.0567)
        self.assertAlmostEqual(self.direction_2.no_turn_lane_capacity_p_raw, 2_043.7434)
        self.assertEqual(self.direction_1.no_turn_lane_capacity_p_display, 2_300)
        self.assertEqual(self.direction_2.no_turn_lane_capacity_p_display, 2_000)
        self.assertEqual(self.direction_1.with_turn_lane_capacity_p_prime_raw, 3_980)
        self.assertEqual(self.direction_2.with_turn_lane_capacity_p_prime_raw, 3_980)
        self.assertEqual(self.direction_1.with_turn_lane_capacity_p_prime_display, 4_000)

    def test_uses_raw_value_and_reproduces_area_c(self) -> None:
        result = classify_capacity_area(self.direction_1, self.direction_2)
        self.assertEqual(result.area, Area.C)
        self.assertGreater(result.b_utilization, 1.0)

    def test_area_a(self) -> None:
        low_1 = replace(self.direction_1, hourly_design_traffic_q=500)
        low_2 = replace(self.direction_2, hourly_design_traffic_q=500)
        result = classify_capacity_area(low_1, low_2)
        self.assertEqual(result.area, Area.A)
        self.assertLess(result.a_utilization, 1.0)

    def test_area_b(self) -> None:
        medium_1 = replace(self.direction_1, hourly_design_traffic_q=1_500)
        medium_2 = replace(self.direction_2, hourly_design_traffic_q=1_000)
        result = classify_capacity_area(medium_1, medium_2)
        self.assertEqual(result.area, Area.B)
        self.assertGreater(result.a_utilization, 1.0)
        self.assertLess(result.b_utilization, 1.0)

    def test_segment_capacity_cap_precedes_area_b(self) -> None:
        over_capacity = replace(self.direction_1, hourly_design_traffic_q=3_700)
        low_other = replace(self.direction_2, hourly_design_traffic_q=0)
        result = classify_capacity_area(over_capacity, low_other)
        self.assertEqual(result.area, Area.D)
        self.assertTrue(result.exceeds_segment_capacity)


class RoundingTest(unittest.TestCase):
    def test_guideline_style_rounding(self) -> None:
        self.assertEqual(round_to_hundred(2_268), 2_300)
        self.assertEqual(round_to_hundred(2_043), 2_000)
        self.assertEqual(round_to_hundred(3_980), 4_000)


if __name__ == "__main__":
    unittest.main()
