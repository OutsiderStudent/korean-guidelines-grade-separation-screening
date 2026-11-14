import unittest
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from interchange_review.phase_review import check_phase_plan
from interchange_review.screening import ApproachInput, uses_guideline_diagram


def y_plan():
    codes = ("SB", "SWB", "SEB")
    approaches = [ApproachInput(code, 1, 600, 0, 0, 0) for code in codes]
    rows = [dict(approach=code, turn="left", exit_leg=codes[(i + 1) % 3], demand=600,
                 saturation=1400, lane_group="", phases=[i + 1]) for i, code in enumerate(codes)]
    return approaches, dict(codes=list(codes), cycle=90, confirmed=True,
                            phases=[dict(green=27, other=3) for _ in codes], movements=rows)


class PhaseReviewTests(unittest.TestCase):
    def test_two_opposing_axes_required(self):
        self.assertFalse(uses_guideline_diagram(["SB", "SWB", "NB", "EB"]))
        self.assertTrue(uses_guideline_diagram(["SB", "WB", "NB", "EB"]))
        self.assertTrue(uses_guideline_diagram(["NWB", "NEB", "SWB", "SEB"]))

    def test_y_intersection_needs_more_time_than_available_in_three_phases(self):
        approaches, data = y_plan()
        result = check_phase_plan(approaches, data)
        self.assertFalse(result.feasible)
        self.assertAlmostEqual(result.movements[0].required_green, 90 * 600 / 1400)
        changed = deepcopy(data)
        for row in changed["movements"]:
            row["saturation"] = 2000
        self.assertTrue(check_phase_plan(approaches, changed).feasible)

    def test_crossing_movements_rejected_in_same_phase(self):
        approaches = [ApproachInput(code, 1, 0, demand, 0, 0)
                      for code, demand in (("SB", 200), ("WB", 300), ("NB", 0), ("EB", 0))]
        data = dict(cycle=80, confirmed=True, phases=[dict(green=70, other=10)], movements=[
            dict(approach=code, turn="through", exit_leg=exit_leg, demand=demand,
                 saturation=1800, lane_group="", phases=[1])
            for code, exit_leg, demand in (("SB", "NB", 200), ("WB", "EB", 300))])
        with self.assertRaisesRegex(ValueError, "교차합니다"):
            check_phase_plan(approaches, data)

    def test_shared_lane_adds_work_and_separate_lanes_can_discharge_together(self):
        approaches = [ApproachInput("SB", 2, 400, 0, 400, 0), ApproachInput("WB", 1, 0, 0, 0, 0),
                      ApproachInput("EB", 1, 0, 0, 0, 0)]
        data = dict(cycle=60, confirmed=True, phases=[dict(green=40, other=20)], movements=[
            dict(approach="SB", turn=turn, exit_leg=exit_leg, demand=400,
                 saturation=1000, lane_group="1", phases=[1])
            for turn, exit_leg in (("left", "WB"), ("right", "EB"))])
        result = check_phase_plan(approaches, data)
        self.assertFalse(result.feasible)
        self.assertEqual(result.movements[0].group_required_green, 48)
        data["movements"][1]["lane_group"] = "2"
        self.assertTrue(check_phase_plan(approaches, data).feasible)

    def test_cycle_and_movement_totals_are_checked(self):
        approaches, data = y_plan()
        data["cycle"] = 91
        with self.assertRaisesRegex(ValueError, "신호주기와 일치"):
            check_phase_plan(approaches, data)
        data["cycle"] = 90
        data["movements"][0]["demand"] -= 1
        with self.assertRaisesRegex(ValueError, "교통량 합계"):
            check_phase_plan(approaches, data)

    def test_saved_plan_dialog_and_result_page(self):
        from PySide6.QtWidgets import QApplication, QDialog
        from interchange_review.phase_dialog import SignalPlanDialog, SignalResultPage
        app = QApplication.instance() or QApplication([])
        approaches, data = y_plan()
        dialog = SignalPlanDialog(approaches, data)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        page = SignalResultPage()
        page.set_result(dialog.review_result)
        self.assertEqual(page.table.rowCount(), 3)
        self.assertIn("부족", page.summary.text())
        app.processEvents()

    def test_nonstandard_result_reopens_from_project(self):
        from PySide6.QtWidgets import QApplication
        from interchange_review.app import MainWindow
        app = QApplication.instance() or QApplication([])
        approaches, data = y_plan()
        source = MainWindow()
        source.topology.set_codes(data["codes"])
        source.input.set_codes(data["codes"])
        for item in approaches:
            source.input.cards[item.code].left.setValue(item.left)
        source.signal_plan = data
        source._show_signal_result(check_phase_plan(source.input.values(), data))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Y형.igr3"
            path.write_text(json.dumps(source.project_data()), encoding="utf-8")
            restored = MainWindow()
            self.assertTrue(restored.load_project(path))
            self.assertIs(restored.result_pages.currentWidget(), restored.signal_results)
            self.assertFalse(restored.signal_result.feasible)
        app.processEvents()

    def test_five_and_six_legs_check_total_required_time(self):
        for codes in (("SB", "SWB", "WB", "NB", "EB"), ("SB", "SWB", "WB", "NWB", "NB", "EB")):
            with self.subTest(codes=codes):
                approaches = [ApproachInput(code, 1, 0, 0, 325, 0) for code in codes]
                data = dict(cycle=20 * len(codes), confirmed=True,
                            phases=[dict(green=17, other=3) for _ in codes], movements=[
                                dict(approach=code, turn="right", exit_leg=codes[(i+1) % len(codes)],
                                     demand=325, saturation=2000, lane_group="", phases=[i+1])
                                for i, code in enumerate(codes)])
                self.assertEqual(check_phase_plan(approaches, data).feasible, len(codes) == 5)
