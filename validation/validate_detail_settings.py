"""Independent numeric sweeps and minimum-size screenshots for detail editing.

Run with PYTHONPATH=src. This is a software regression check, not a claim
that the full KHCM chapter 8 operational procedure has been implemented.
"""
import json
import os
from itertools import product
from math import isclose
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from interchange_review.detail import LaneInput, RoadConditions, calculate_lane


OUT = Path(__file__).resolve().parent / "results_detail"


def validate_calculations():
    cases = 0
    for width, grade, hv, volume, green, phf in product(
        (2.5, 3.0, 3.5), (-5, 0, 5), (0, 20, 100), (50, 500, 1500), (10, 30, 70), (0.5, 0.8, 1)
    ):
        # Independent direct expression from KHCM table 8-4, equations 8-2–4.
        for kind, flow, equivalent in (("직진", "through", 1), ("좌회전", "left", 1.08), ("우회전", "right", 1.2)):
            lane = LaneInput(kind=kind, width_m=width, green=green,
                             **{flow: volume, "heavy_" + flow: hv})
            result = calculate_lane(lane, RoadConditions(grade_percent=grade), cycle=80, phf=phf)
            expected_s = 2200 * min(1, 1 - 0.012 * grade) * min(1, 1 - 0.35 * (3 - width)) / ((1 + hv / 100 * 0.8) * equivalent)
            expected_c = expected_s * (green - 0.3) / 80
            assert isclose(result.saturation, expected_s, rel_tol=1e-12)
            assert isclose(result.capacity, expected_c, rel_tol=1e-12)
            assert isclose(result.saturation_ratio, volume / phf / expected_c, rel_tol=1e-12)
            cases += 1
    return cases


def render_screens():
    from PySide6.QtWidgets import QApplication
    from interchange_review.app import CoefficientSettingsDialog, resource_path
    from interchange_review.screening import ApproachInput
    from interchange_review.theme import apply_application_theme, load_application_fonts
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    load_application_fonts(resource_path)
    traffic = [ApproachInput(c, 2, 100, 700, 200, 20) for c in ("SB", "SWB", "WB", "NB", "NEB", "EB")]
    screenshots = []
    for theme in ("light", "dark"):
        apply_application_theme(app, theme)
        d = CoefficientSettingsDialog([item.code for item in traffic], {}, {}, traffic=traffic)
        d.resize(680, 560)
        d.operating_cycle.setValue(100)
        d.show()
        for index, name in ((0, "mode"), (1, "road"), (2, "lane"), (3, "signal"), (4, "review")):
            if index == 1:
                d.scope.setCurrentIndex(1)
            if index == 2:
                panel = d.lanes["SB"]
                panel.enabled.setChecked(True)
                panel.constraints.setChecked(True)
                panel.count.setValue(3)
                for row, kind, movement, volume in zip(panel.rows, ("좌회전", "직진", "우회전"), ("left", "through", "right"), (100, 700, 200)):
                    row.kind.setCurrentIndex(row.kind.findData(kind))
                    row.flows[movement].setValue(volume)
                    row.saved["green"] = 30 if movement == "left" else 50
            d.tabs.setCurrentIndex(index)
            app.processEvents()
            if index == 4:
                assert d.review.horizontalScrollBar().maximum() == 0, "Review table overflows"
            path = OUT / f"{theme}_{name}_680x560.png"
            d.grab().save(str(path))
            screenshots.append(path.name)
            if index == 1:
                area = d.tabs.widget(index)
                area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
                app.processEvents()
                path = OUT / f"{theme}_road_bottom_680x560.png"
                d.grab().save(str(path))
                screenshots.append(path.name)
        # Twelve stop-line lanes at six approaches must scroll inside the dialog.
        d.lanes["SB"].count.setValue(12)
        d.tabs.setCurrentIndex(2)
        area = d.lane_stack.currentWidget()
        app.processEvents()
        area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
        app.processEvents()
        assert d.size().width() == 680 and d.size().height() == 560
        path = OUT / f"{theme}_12lanes_bottom_680x560.png"
        d.grab().save(str(path))
        screenshots.append(path.name)
        d.close()
    return screenshots


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"numeric_scenarios": validate_calculations(), "screenshots": render_screens(),
              "scope": "same-entry-signal lane capacity; not full chapter 8 delay/LOS"}
    (OUT / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
