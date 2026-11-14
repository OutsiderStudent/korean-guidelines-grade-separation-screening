import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from interchange_review.detail import LaneInput, RoadConditions, calculate_lane, validate_lane_totals
from interchange_review.screening import ApproachInput, CoefficientAssumptions, calculate_approach


class DetailCalculationTest(unittest.TestCase):
    def test_table_8_14_radius_and_angle_boundaries(self):
        for radius, expected in ((13, 1.11), (13.01, 1.08), (16, 1.08), (16.01, 1.05), (19, 1.05), (19.01, 1)):
            with self.subTest(radius=radius):
                road = RoadConditions(left_geometry="radius", radius_m=radius)
                self.assertEqual(road.left_equivalent, expected)
                self.assertEqual(replace(road, left_angle=120).left_equivalent, 1)
        self.assertEqual(RoadConditions(opposing_lanes=2, lane_order=2).left_equivalent, 1.05)

    def test_equations_8_2_to_8_4_independent_hand_calculation(self):
        # g = 36 - 2.3 + 2 = 35.7; pure passenger-car through lane.
        lane = LaneInput(through=500, heavy_through=0, green=36)
        result = calculate_lane(lane, RoadConditions(), cycle=80)
        self.assertAlmostEqual(result.saturation, 2200)
        self.assertAlmostEqual(result.effective_green, 35.7)
        self.assertAlmostEqual(result.capacity, 981.75)
        self.assertAlmostEqual(result.saturation_ratio, 500 / 981.75)

    def test_movement_weights_are_pce_not_raw_vehicle_counts(self):
        lane = LaneInput(kind="직좌", left=100, through=100, heavy_left=50,
                         heavy_through=0, green=40)
        result = calculate_lane(lane, RoadConditions(), cycle=100)
        # 140 PCU left + 100 PCU through; total vehicle flow = 200.
        self.assertAlmostEqual(result.heavy_factor, 200 / 240)
        self.assertAlmostEqual(result.movement_factor, 240 / (140 * 1.08 + 100))
        self.assertAlmostEqual(result.saturation, 2200 * 200 / (140 * 1.08 + 100))

    def test_phf_changes_demand_only(self):
        lane = LaneInput(through=500, green=36)
        a = calculate_lane(lane, RoadConditions(), cycle=80)
        b = calculate_lane(lane, RoadConditions(), cycle=80, phf=0.8)
        self.assertEqual(a.capacity, b.capacity)
        self.assertEqual(b.demand, 625)
        self.assertAlmostEqual(b.saturation_ratio, a.saturation_ratio / 0.8)

    def test_published_example_1_single_signal_lanes(self):
        # KHCM 2026, example 1, printed pp.459,461–466:
        # EB left: 150 cars +25 HV; through:250 cars +50 HV; C=100.
        road = RoadConditions()
        left = calculate_lane(LaneInput(kind="좌회전", left=175, heavy_left=25/175*100, green=17), road, cycle=100)
        through = calculate_lane(LaneInput(through=300, heavy_through=50/300*100, green=27), road, cycle=100)
        self.assertAlmostEqual(left.capacity / left.heavy_factor, 340.2, delta=0.05)
        self.assertAlmostEqual(through.capacity / through.heavy_factor, 587.4, delta=0.05)
        self.assertAlmostEqual(left.saturation_ratio, 0.57, delta=0.005)
        self.assertAlmostEqual(through.saturation_ratio, 0.58, delta=0.005)
        # SB shared L/T: PCU demands 195 +340; g=21.7.
        shared = calculate_lane(LaneInput(kind="직좌", left=175, through=300,
                                         heavy_left=25/175*100, heavy_through=50/300*100, green=22), road, cycle=100)
        pcu_capacity = shared.capacity / shared.heavy_factor
        self.assertAlmostEqual(pcu_capacity *195/535, 169.1, delta=0.05)
        self.assertAlmostEqual(pcu_capacity *340/535, 294.8, delta=0.05)
        self.assertAlmostEqual(shared.saturation_ratio, 1.15, delta=0.005)

    def test_lane_specific_radius_overrides_approach(self):
        lane = LaneInput(kind="좌회전", left=100, green=20, radius_m=12)
        result = calculate_lane(lane, RoadConditions(left_geometry="radius", radius_m=50), cycle=100)
        self.assertEqual(result.left_equivalent, 1.11)

    def test_unsupported_operations_do_not_emit_capacity(self):
        for mode in ("red", "mixed"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "적색 우회전"):
                calculate_lane(LaneInput(kind="우회전", right=100, green=36),
                               RoadConditions(right_turn_mode=mode, red_right_percent=30), cycle=80)
        with self.assertRaisesRegex(ValueError, "전용차로"):
            calculate_lane(LaneInput(kind="직우", through=200, right=100, green=36),
                           RoadConditions(right_turn_mode="right_signal"), cycle=80)

    def test_invalid_demand_signals_and_nonfinite_inputs(self):
        with self.assertRaises(ValueError):
            LaneInput(kind="직진", left=10)
        with self.assertRaises(ValueError):
            LaneInput(through=float("nan"))
        for lane in (LaneInput(through=100), LaneInput(through=100, green=100),
                     LaneInput(through=100, green=2, start_loss=10)):
            with self.assertRaises(ValueError):
                calculate_lane(lane, RoadConditions(), cycle=100)
        with self.assertRaises(ValueError):
            RoadConditions(right_turn_mode="mixed")

    def test_lane_sums_conserve_movement_totals(self):
        lanes = [LaneInput(kind="좌회전", left=100), LaneInput(through=200)]
        validate_lane_totals(lanes, dict(left=100, through=200, right=0))
        with self.assertRaisesRegex(ValueError, "직진"):
            validate_lane_totals(lanes, dict(left=100, through=201, right=0))

    def test_screening_is_isolated_from_actual_signal_lane_capacity(self):
        value = ApproachInput("SB", 2, 100, 700, 200, 20)
        before = calculate_approach(value)
        road = RoadConditions(lane_width_m=2.8, grade_percent=3)
        after = calculate_approach(value, CoefficientAssumptions(approach_conditions={"SB": asdict(road)}))
        self.assertAlmostEqual(after.turn_factor, before.turn_factor * 0.93 * 0.964)
        self.assertEqual(before.direction.segment_capacity_c, after.direction.segment_capacity_c)
        self.assertEqual(before.direction.with_turn_lane_capacity_p_prime_raw,
                         after.direction.with_turn_lane_capacity_p_prime_raw)
        other = calculate_approach(replace(value, code="WB"), CoefficientAssumptions(approach_conditions={"SB": asdict(road)}))
        self.assertEqual(before.turn_factor, other.turn_factor)

    def test_legacy_and_external_coefficients_take_precedence(self):
        assumptions = CoefficientAssumptions(legacy=True, left_equivalent=2.0,
                                            approach_conditions={"SB": {"invalid": True}})
        value = ApproachInput("SB", 2, 100, 700, 200, 20)
        calculate_approach(value, assumptions)  # ignored new settings must not break old projects
        manual = calculate_approach(replace(value, direct_turn_factor=0.7, direct_heavy_factor=0.8), assumptions)
        self.assertEqual(manual.turn_factor, 0.7)
        self.assertEqual(manual.heavy_factor, 0.8)


class DetailUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_dialog(self, settings=None):
        from interchange_review.app import CoefficientSettingsDialog
        traffic = [ApproachInput(c, 2, 100, 700, 200, 20) for c in ("SB", "WB", "NB", "EB")]
        return CoefficientSettingsDialog(["EB", "NB", "WB", "SB"], settings or {}, {}, traffic=traffic)

    def test_minimum_window_mode_switch_is_stable_and_buttons_stay_visible(self):
        d = self.make_dialog()
        d.resize(680, 560)
        d.show()
        self.app.processEvents()
        height = d.height()
        for mode in ("direct", "auto", "direct", "auto"):
            d.mode.setCurrentIndex(d.mode.findData(mode))
            self.app.processEvents()
            self.assertEqual(d.height(), height)
        self.assertEqual(d.codes, ["SB", "WB", "NB", "EB"])
        d.close()

    def test_per_approach_fields_and_review_are_connected(self):
        d = self.make_dialog()
        d.scope.setCurrentIndex(1)
        d.roads["SB"].width.setValue(2.8)
        d.roads["SB"].grade.setValue(3)
        d.tabs.setCurrentIndex(4)
        text = d.review.toPlainText()
        self.assertIn("접근로별 보정", text)
        settings, _ = d.values()
        self.assertEqual(settings["approach_conditions"]["SB"]["lane_width_m"], 2.8)
        self.assertEqual(settings["approach_conditions"]["WB"]["lane_width_m"], 3)
        d.close()

    def test_missing_external_values_are_not_silently_defaulted(self):
        d = self.make_dialog()
        d.mode.setCurrentIndex(d.mode.findData("direct"))
        d.accept()
        self.assertEqual(d.result(), 0)
        self.assertIn("계수", d.error_label.text())
        d.reset_direct.click()
        self.assertGreater(d.direct_spins["SB"][0].value(), 0)
        d.accept()
        self.assertEqual(d.result(), 1)
        d.close()

    def test_lane_inputs_missing_green_and_traffic_mismatch_block_apply(self):
        d = self.make_dialog()
        panel = d.lanes["SB"]
        d.operating_cycle.setValue(100)
        panel.enabled.setChecked(True)
        panel.constraints.setChecked(True)
        d.accept()
        self.assertEqual(d.result(), 0)
        self.assertIn("기본 입력", d.error_label.text())
        panel.rows[0].kind.setCurrentIndex(panel.rows[0].kind.findData("좌직우"))
        for movement, flow in (("left", 100), ("through", 700), ("right", 200)):
            panel.rows[0].flows[movement].setValue(flow)
        d.accept()
        self.assertIn("진입신호시간", d.error_label.text())
        self.assertEqual(d.tabs.currentIndex(), 3)
        d.signal_fields[("SB", 0)][0].setValue(40)
        d.accept()
        self.assertEqual(d.result(), 1)
        self.assertIn("차로 신호 용량", d.review.toPlainText())
        d.close()

    def test_switching_approach_preserves_signal_and_cancel_does_not_mutate(self):
        settings = {"approach_conditions": {"SB": asdict(RoadConditions())}}
        original = json.dumps(settings, sort_keys=True)
        d = self.make_dialog(settings)
        d.lanes["SB"].enabled.setChecked(True)
        d.tabs.setCurrentIndex(3)
        d.signal_fields[("SB", 0)][0].setValue(42)
        d.approach.setCurrentIndex(1)
        d.approach.setCurrentIndex(0)
        self.assertEqual(d.signal_fields[("SB", 0)][0].value(), 42)
        d.roads["SB"].width.setValue(2.7)
        d.reject()
        self.assertEqual(json.dumps(settings, sort_keys=True), original)
        d.close()

    def test_new_settings_and_result_survive_project_roundtrip(self):
        from interchange_review.app import MainWindow
        w = MainWindow()
        w.input.set_codes(["SB", "WB", "NB", "EB"])
        w.input.calculation_settings.update(detail_scope="approach", approach_conditions={"SB": asdict(RoadConditions(grade_percent=4))},
                                           operating_cycle=120, lane_analysis={"SB": {"enabled": False, "lanes": [asdict(LaneInput(through=700))]}})
        data = w.project_data()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "detail.igr3"
            path.write_text(json.dumps(data), encoding="utf-8")
            other = MainWindow()
            self.assertTrue(other.load_project(path))
            self.assertEqual(other.input.settings_data(), w.input.settings_data())
            other.close()
        w.close()

    def test_fill_traffic_does_not_invent_multiple_lane_splits(self):
        d = self.make_dialog()
        panel = d.lanes["SB"]
        panel.enabled.setChecked(True)
        panel.count.setValue(2)
        panel.rows[0].flows["through"].setValue(30)
        panel.fill_traffic()
        self.assertEqual(panel.rows[0].flows["through"].value(), 30)
        self.assertEqual(panel.rows[1].flows["through"].value(), 0)
        self.assertIn("배분값", panel.fill_message.text())
        panel.rows[0].kind.setCurrentIndex(panel.rows[0].kind.findData("직좌"))
        panel.fill_traffic()
        self.assertEqual(panel.rows[0].flows["left"].value(), 100)
        d.close()


if __name__ == "__main__":
    unittest.main()
