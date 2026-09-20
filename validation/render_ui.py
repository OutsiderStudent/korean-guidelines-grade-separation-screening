"""현재 버전의 주요 화면을 오프스크린으로 렌더링해 시각 회귀 검토한다."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from interchange_review.app import CoefficientSettingsDialog, MainWindow, STYLE, resource_path
from interchange_review.screening import analyze_intersection


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "validation" / "results_current"


def save_widget(widget, name: str) -> None:
    widget.show()
    QApplication.processEvents()
    widget.grab().save(str(OUT / name), "PNG", 100)


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(str(resource_path("NotoSansKR.ttf")))
    app.setFont(QFont("Noto Sans KR", 10))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.resize(1050, 750)
    codes = ["SB", "SWB", "WB", "NB", "EB"]
    window.topology.set_codes(codes)
    window.input.set_codes(codes, preserve=False)
    volumes = {
        "SB": (260, 1_150, 180, 12),
        "SWB": (90, 480, 120, 8),
        "WB": (210, 920, 160, 18),
        "NB": (240, 1_060, 190, 15),
        "EB": (180, 840, 150, 10),
    }
    for code, (left, through, right, heavy) in volumes.items():
        row = window.input.cards[code]
        row.left.setValue(left)
        row.through.setValue(through)
        row.right.setValue(right)
        row.heavy.setValue(heavy)
    window.pages.setCurrentIndex(1)
    save_widget(window, "ui_input_1050x750.png")

    dialog = CoefficientSettingsDialog(codes, window.input.calculation_settings, {}, window)
    dialog.mode.setCurrentIndex(1)
    save_widget(dialog, "ui_advanced_settings.png")
    dialog.close()

    window.confirm.set_values(
        len(codes), window.input.values(), window.input.assumptions(), window.input.signal_assumptions()
    )
    window.pages.setCurrentIndex(2)
    save_widget(window, "ui_confirm_1050x750.png")

    result = analyze_intersection(
        window.input.values(), window.input.assumptions(), window.input.signal_assumptions()
    )
    window.results.set_result(result)
    window.pages.setCurrentIndex(3)
    save_widget(window, "ui_result_1050x750.png")
    window.close()


if __name__ == "__main__":
    run()
