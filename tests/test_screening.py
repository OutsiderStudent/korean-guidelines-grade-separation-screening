import unittest

from interchange_review import Area
from interchange_review.screening import (
    ApproachInput,
    CoefficientAssumptions,
    analyze_intersection,
    calculate_approach,
    conflict_pairs,
)


class ScreeningModelTest(unittest.TestCase):
    def test_four_leg_produces_exactly_four_graph_pairs(self) -> None:
        pairs = conflict_pairs(["SB", "NB", "WB", "EB"])
        self.assertEqual(pairs, [("SB", "WB"), ("SB", "EB"), ("WB", "NB"), ("NB", "EB")])

    def test_approach_uses_hourly_movement_sum_and_one_way_lanes(self) -> None:
        result = calculate_approach(ApproachInput("SB", 2, 100, 700, 200, 20))
        self.assertEqual(result.direction.hourly_design_traffic_q, 1_000)
        self.assertEqual(result.direction.segment_capacity_c, 3_600)
        self.assertEqual(result.direction.one_direction_lanes, 2)
        self.assertAlmostEqual(result.heavy_factor, 1 / 1.16)
        self.assertAlmostEqual(result.turn_factor, 1 / (1 + 0.1 + 0.1))

    def test_combined_turn_factor_is_not_product_of_separate_factors(self) -> None:
        result = calculate_approach(ApproachInput("SB", 2, 200, 600, 200, 20))
        combined = 1 / (1 + 0.2 * (2.0 - 1) + 0.2 * (1.5 - 1))
        separate_product = (1 / 1.2) * (1 / 1.1)
        self.assertAlmostEqual(result.turn_factor, combined)
        self.assertNotAlmostEqual(result.turn_factor, separate_product)

    def test_direct_factors_reproduce_guideline_values(self) -> None:
        value = ApproachInput("SB", 2, 220, 1_540, 440, 20, 0.910 * 0.905, 0.850)
        result = calculate_approach(value)
        self.assertEqual(result.factor_mode, "직접 입력")
        self.assertAlmostEqual(result.direction.no_turn_lane_capacity_p_raw, 2_268.0567)

    def test_direct_factors_reproduce_guideline_area_c(self) -> None:
        approaches = [
            ApproachInput("SB", 2, 220, 1_540, 440, 20, 0.910 * 0.905, 0.850),
            ApproachInput("WB", 2, 360, 1_080, 360, 20, 0.820 * 0.905, 0.850),
            ApproachInput("EB", 2, 1, 1, 1, 20, 1.0, 1.0),
        ]
        result = analyze_intersection(approaches)
        pair = next(item for item in result.pairs if item.name == "SB–WB")
        self.assertAlmostEqual(pair.first.direction.no_turn_lane_capacity_p_raw, 2_268.0567)
        self.assertAlmostEqual(pair.second.direction.no_turn_lane_capacity_p_raw, 2_043.7434)
        self.assertEqual(pair.classification.area, Area.C)

    def test_p_prime_uses_fixed_guideline_right_turn_addition(self) -> None:
        one_lane = calculate_approach(ApproachInput("SB", 1, 100, 700, 200, 20))
        three_lane = calculate_approach(ApproachInput("SB", 3, 100, 700, 200, 20))
        self.assertAlmostEqual(one_lane.direction.with_turn_lane_capacity_p_prime_raw, 2_360)
        self.assertAlmostEqual(three_lane.direction.with_turn_lane_capacity_p_prime_raw, 5_600)

    def test_intersection_uses_worst_pair(self) -> None:
        approaches = [
            ApproachInput("SB", 1, 400, 2_200, 200, 20),
            ApproachInput("NB", 2, 20, 300, 20, 5),
            ApproachInput("WB", 1, 300, 2_100, 200, 20),
            ApproachInput("EB", 2, 20, 300, 20, 5),
        ]
        result = analyze_intersection(approaches)
        self.assertEqual(len(result.pairs), 4)
        self.assertEqual(result.area, Area.D)
        self.assertEqual(result.critical_pair.classification.area, result.area)

    def test_six_leg_is_marked_as_extension(self) -> None:
        codes = ["SB", "NB", "WB", "EB", "SEB", "NWB"]
        result = analyze_intersection([ApproachInput(code, 2, 50, 500, 50, 10) for code in codes])
        self.assertTrue(result.is_extended_method)
        self.assertGreater(len(result.pairs), 4)


if __name__ == "__main__":
    unittest.main()
