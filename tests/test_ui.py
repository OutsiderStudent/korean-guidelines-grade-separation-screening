import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox

from interchange_review.app import APP_VERSION, CoefficientSettingsDialog, ConfirmPage, InputPage, MainWindow
from interchange_review.screening import APPROACH_ORDER, ApproachInput


class UiRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_version(self) -> None:
        self.assertEqual(APP_VERSION, "3.6.0")

    def test_input_cards_follow_clockwise_order(self) -> None:
        page = InputPage()
        page.set_codes(["NB", "EB", "SB", "SWB", "WB"])
        expected = [code for code in APPROACH_ORDER if code in {"NB", "EB", "SB", "SWB", "WB"}]
        self.assertEqual(list(page.cards), expected)

    def test_traffic_limit_and_heavy_spinner_buttons(self) -> None:
        page = InputPage()
        page.set_codes(["SB", "WB", "EB"])
        row = page.cards["SB"]
        row.left.setValue(100_000)
        self.assertEqual(row.left.value(), 99_999)
        self.assertEqual(
            row.heavy.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.assertEqual(
            page.global_heavy.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.NoButtons
        )

    def test_confirmation_table_populates_every_column(self) -> None:
        page = ConfirmPage()
        value = ApproachInput("SB", 2, 100, 700, 150, 20)
        page.set_values(3, [value])
        self.assertEqual(
            [page.table.item(0, column).text() for column in range(7)],
            ["SB", "2", "100", "700", "150", "950", "20.0%"],
        )

    def test_direct_factor_settings_are_applied_per_approach(self) -> None:
        page = InputPage()
        page.set_codes(["SB", "WB", "NB"])
        page.calculation_settings["mode"] = "direct"
        page.direct_factors = {"SB": (0.81, 0.85), "WB": (0.72, 0.90), "NB": (0.95, 0.88)}
        values = {value.code: value for value in page.values()}
        self.assertEqual(values["SB"].direct_turn_factor, 0.81)
        self.assertEqual(values["WB"].direct_heavy_factor, 0.90)

    def test_project_data_preserves_calculation_settings(self) -> None:
        window = MainWindow()
        window.input.calculation_settings["right_addition"] = 750.0
        window.input.calculation_settings["mode"] = "direct"
        window.input.direct_factors = {"SB": (0.82, 0.86)}
        data = window.project_data()
        self.assertEqual(data["schema"], 2)
        self.assertEqual(data["calculation_settings"]["right_addition"], 750.0)
        self.assertEqual(data["calculation_settings"]["direct_factors"]["SB"]["turn"], 0.82)

    def test_detail_settings_hide_all_spin_buttons(self) -> None:
        page = InputPage()
        page.set_codes(["SB", "WB", "EB"])
        dialog = CoefficientSettingsDialog(list(page.cards), page.calculation_settings, {}, page)
        spins = [
            dialog.left_equivalent,
            dialog.right_equivalent,
            dialog.heavy_equivalent,
            dialog.right_addition,
            dialog.effective_green,
            dialog.left_per_cycle,
            dialog.utilization,
        ]
        spins.extend(spin for pair in dialog.direct_spins.values() for spin in pair)
        self.assertTrue(all(spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons for spin in spins))
        self.assertTrue(all(spin.minimumHeight() >= 32 for spin in spins))

    def test_main_window_minimum_design_size(self) -> None:
        window = MainWindow()
        self.assertGreaterEqual(window.minimumWidth(), 1_050)
        self.assertGreaterEqual(window.minimumHeight(), 750)

    def test_return_to_start_can_be_cancelled_or_discarded(self) -> None:
        window = MainWindow()
        window.pages.setCurrentIndex(3)
        window.is_dirty = True
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            window._return_to_start()
        self.assertEqual(window.pages.currentIndex(), 3)
        self.assertTrue(window.is_dirty)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Discard):
            window._return_to_start()
        self.assertEqual(window.pages.currentIndex(), 0)
        self.assertFalse(window.is_dirty)


if __name__ == "__main__":
    unittest.main()
