"""Synthetic peak-hour plans checked against a separately tabulated worksheet.

Each movement row gives the hand-calculated green time for the base traffic
volume. The four traffic levels scale those times in direct proportion.
"""

from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from interchange_review.phase_dialog import SignalPlanDialog, SignalResultPage
from interchange_review.phase_review import check_phase_plan
from interchange_review.screening import APPROACH_ORDER, ApproachInput


# approach, turn, exit leg, vehicles/hour, adjusted vehicles/green-hour,
# shared lane group, service phases, hand-calculated base green seconds
CASES = {
    "3지 T형 · 간선도로": (90, ((51, 4), (31, 4)), (
        ("WB", "through", "EB", 600, 1800, "1", (1,), 30),
        ("WB", "right", "SB", 150, 1500, "1", (1,), 9),
        ("EB", "through", "WB", 640, 1920, "", (1,), 30),
        ("SB", "left", "WB", 350, 1500, "1", (2,), 21),
        ("SB", "right", "EB", 100, 1500, "1", (2,), 6),
    ), (True, True, False, False)),
    "3지 Y형 · 분리 현시": (96, ((34, 4), (26, 4), (24, 4)), (
        ("SB", "left", "NWB", 400, 1600, "1", (1,), 24),
        ("SB", "right", "NEB", 125, 1500, "1", (1,), 8),
        ("NWB", "left", "NEB", 300, 1600, "", (2,), 18),
        ("NEB", "right", "NWB", 300, 1600, "", (3,), 18),
    ), (True, True, False, False)),
    "4지 · 간선과 사교차": (100, ((42, 4), (26, 4), (20, 4)), (
        ("SB", "through", "NB", 720, 1800, "", (1,), 40),
        ("NB", "through", "SB", 630, 1800, "", (1,), 35),
        ("SWB", "through", "EB", 396, 1800, "", (2,), 22),
        ("EB", "through", "SWB", 324, 1800, "", (3,), 18),
    ), (True, True, False, False)),
    "5지 · 양방 직진과 부도로": (120, ((47, 4), (27, 4), (18, 4), (12, 4)), (
        ("SB", "through", "NB", 630, 1800, "", (1,), 42),
        ("NB", "through", "SB", 600, 1800, "", (1,), 40),
        ("WB", "through", "EB", 360, 1800, "", (2,), 24),
        ("EB", "through", "WB", 300, 1800, "", (2,), 20),
        ("SWB", "right", "EB", 200, 1500, "", (3,), 16),
        ("NB", "left", "EB", 125, 1500, "", (4,), 10),
    ), (True, True, False, False)),
    "6지 · 세 도로축": (120, ((33, 4), (26, 4), (23, 4), (22, 4)), (
        ("SB", "through", "NB", 450, 1800, "", (1,), 30),
        ("NB", "through", "SB", 420, 1800, "", (1,), 28),
        ("WB", "through", "EB", 360, 1800, "", (2,), 24),
        ("EB", "through", "WB", 330, 1800, "", (2,), 22),
        ("SWB", "through", "NEB", 300, 1800, "", (3,), 20),
        ("NEB", "through", "SWB", 270, 1800, "", (3,), 18),
        ("SB", "left", "WB", 250, 1500, "", (4,), 20),
    ), (True, True, False, False)),
    "6지 · 우회전 두 현시": (120, ((30, 4), (27, 4), (25, 4), (22, 4)), (
        ("SB", "through", "NB", 420, 1800, "", (1,), 28),
        ("NB", "through", "SB", 390, 1800, "", (1,), 26),
        ("WB", "through", "EB", 360, 1800, "", (2,), 24),
        ("EB", "through", "WB", 330, 1800, "", (2,), 22),
        ("SWB", "through", "NEB", 330, 1800, "", (3,), 22),
        ("NEB", "through", "SWB", 300, 1800, "", (3,), 20),
        ("SB", "right", "EB", 550, 1500, "", (3, 4), 44),
    ), (True, True, False, False)),
}

LEVELS = (Fraction(4, 5), Fraction(1), Fraction(6, 5), Fraction(3, 2))


def worksheet(cycle, timings, rows, scale):
    totals = {}
    data_rows = []
    hand_rows = {}
    shared = {}
    for approach, turn, exit_leg, volume, saturation, group, phases, base_seconds in rows:
        count = int(volume * scale)
        # Several base counts are odd. Adjust the hand calculation by the
        # exact fractional vehicle discarded when entering an integer volume.
        needed = base_seconds * Fraction(count, volume)
        route = (approach, turn, exit_leg)
        key = (approach, group) if group else route
        shared[key] = shared.get(key, Fraction(0)) + needed
        green = sum(timings[phase - 1][0] for phase in phases)
        hand_rows[route] = (needed, green, key)
        totals.setdefault(approach, dict(left=0, through=0, right=0))[turn] += count
        data_rows.append(dict(approach=approach, turn=turn, exit_leg=exit_leg, demand=count,
                              saturation=saturation, lane_group=group, phases=list(phases)))
    legs = {code for row in rows for code in (row[0], row[2])}
    approaches = [ApproachInput(code, 2, heavy_percent=8, **totals.get(code, dict(left=0, through=0, right=0)))
                  for code in APPROACH_ORDER if code in legs]
    data = dict(codes=[item.code for item in approaches], cycle=cycle, confirmed=True,
                phases=[dict(green=green, other=other) for green, other in timings], movements=data_rows)
    expected = {
        route: (needed, green, shared[key], max(Fraction(0), shared[key] - green))
        for route, (needed, green, key) in hand_rows.items()
    }
    return approaches, data, expected


class RealisticPhaseScenarios(unittest.TestCase):
    def test_hand_calculations_against_engine_and_screen(self):
        app = QApplication.instance() or QApplication([])
        for name, (cycle, timings, rows, verdicts) in CASES.items():
            for scale, verdict in zip(LEVELS, verdicts):
                with self.subTest(site=name, traffic=str(scale)):
                    approaches, data, expected = worksheet(cycle, timings, rows, scale)
                    self.assertEqual(len(approaches), int(name[0]))
                    direct = check_phase_plan(approaches, data)
                    dialog = SignalPlanDialog(approaches, data)
                    dialog.accept()
                    self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted, dialog.error.text())
                    self.assertEqual(dialog.review_result, direct)
                    self.assertEqual(direct.feasible, verdict)
                    page = SignalResultPage()
                    page.set_result(direct)
                    for index, item in enumerate(direct.movements):
                        movement = item.movement
                        needed, green, total, shortage = expected[movement.approach, movement.turn, movement.exit_leg]
                        self.assertAlmostEqual(item.required_green, float(needed), places=9)
                        self.assertAlmostEqual(item.group_required_green, float(total), places=9)
                        self.assertAlmostEqual(item.available_green, float(green), places=9)
                        shown = Decimal(page.table.item(index, page.table.columnCount() - 1).text())
                        expected_display = (Decimal(shortage.numerator) / Decimal(shortage.denominator)).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_EVEN)
                        self.assertEqual(shown, expected_display)
                    dialog.close()
                    page.close()
                    dialog.deleteLater()
                    page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
