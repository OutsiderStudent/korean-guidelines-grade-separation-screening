import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox

from interchange_review.app import APP_VERSION, CoefficientSettingsDialog, ConfirmPage, InputPage, MainWindow, MotionButton, StepProgress
from interchange_review.screening import APPROACH_ORDER, ApproachInput
from interchange_review.theme import DARK_STYLE, FONT_FAMILY, LIGHT, STYLE, apply_application_theme
from interchange_review.updater import UpdateController


class UiRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_version(self) -> None:
        self.assertEqual(APP_VERSION, "5.0.1")

    def test_packaged_start_checks_and_offers_update_with_two_buttons(self) -> None:
        with patch("sys.frozen", True, create=True), patch.dict(os.environ, {"KGSS_DISABLE_UPDATE_CHECK": "0"}), patch.object(QTimer, "singleShot") as timer:
            window = MainWindow()
            timer.assert_any_call(2500, window.updater.check)

        next_release = {
            "tag_name": "v5.0.2",
            "body": "2026년 도로용량편람 반영",
            "assets": [{"name": "K-GSS_v5.0.2_windows-x64.exe"}],
        }
        from unittest.mock import Mock
        from PySide6.QtNetwork import QNetworkReply
        reply = Mock()
        reply.error.return_value = QNetworkReply.NetworkError.NoError
        reply.readAll.return_value = json.dumps(next_release).encode()
        controller = window.updater
        controller._reply = reply
        observed = []

        def cancel_offer():
            box = self.app.activeModalWidget()
            if isinstance(box, QMessageBox):
                observed.append((box.windowTitle(), {b.text() for b in box.buttons()}))
                box.escapeButton().click()

        with patch("interchange_review.updater.native_windows_architecture", return_value="x64"), patch.object(UpdateController, "_start_download") as download:
            QTimer.singleShot(0, cancel_offer)
            controller._check_finished()
            download.assert_not_called()
        self.assertEqual(observed, [("업데이트 확인", {"업데이트", "취소"})])
        window.close()

    def test_mixed_right_turn_requires_and_preserves_vehicle_percentage(self) -> None:
        page = InputPage()
        dialog = CoefficientSettingsDialog(["SB", "WB", "EB"], page.calculation_settings, {})
        dialog.right_mode.setCurrentIndex(dialog.right_mode.findData("mixed"))
        with patch.object(QMessageBox, "warning") as warning:
            dialog.accept()
            warning.assert_called_once()
        dialog.red_right_percent.setValue(30)
        settings, _ = dialog.values()
        page.apply_settings_data(settings)
        self.assertEqual(page.settings_data()["red_right_percent"], 30)
        self.assertAlmostEqual(page.assumptions().applied_right_equivalent, 1.44)
        reopened = CoefficientSettingsDialog(["SB", "WB", "EB"], page.settings_data(), {})
        self.assertEqual(reopened.right_mode.currentData(), "mixed")
        self.assertEqual(reopened.red_right_percent.value(), 30)

    def test_design_system_uses_required_light_tokens_and_font(self) -> None:
        self.assertEqual(FONT_FAMILY, "NanumSquare")
        self.assertEqual(LIGHT["primary"], "#0F3675")
        self.assertEqual(LIGHT["accent"], "#77A4ED")
        self.assertEqual(LIGHT["background"], "#F2F2F2")
        self.assertIn("font-family: 'NanumSquare'", STYLE)
        self.assertIn("#15191F", DARK_STYLE)

    def test_theme_menu_switches_light_and_dark_without_hiding_content(self) -> None:
        window = MainWindow()
        self.assertEqual(sorted(window.theme_actions), ["dark", "light", "system"])
        window.set_theme("dark", persist=False)
        self.assertEqual(self.app.property("kgssTheme"), "dark")
        self.assertTrue(window.theme_actions["dark"].isChecked())
        self.assertFalse(window.next.isHidden())
        window.set_theme("light", persist=False)
        self.assertEqual(self.app.property("kgssTheme"), "light")

    def test_saved_project_can_be_loaded_directly_from_a_path(self) -> None:
        source = MainWindow()
        source.input.set_codes(source.topology.selected_codes())
        source.input.cards["SB"].through.setValue(720)
        source.input.cards["WB"].left.setValue(130)
        data = source.project_data()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "한글 공백 교차로.igr3"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            loaded = MainWindow()
            self.assertTrue(loaded.load_project(path))
            self.assertEqual(loaded.project_path, path.resolve())
            self.assertEqual(loaded.input.cards["SB"].through.value(), 720)
            self.assertEqual(loaded.input.cards["WB"].left.value(), 130)
            self.assertIn(path.name, loaded.windowTitle())

    def test_input_cards_follow_clockwise_order(self) -> None:
        page = InputPage()
        page.set_codes(["NB", "EB", "SB", "SWB", "WB"])
        expected = [code for code in APPROACH_ORDER if code in {"NB", "EB", "SB", "SWB", "WB"}]
        self.assertEqual(list(page.cards), expected)

    def test_legacy_project_keeps_original_method_and_requires_save_as(self) -> None:
        window = MainWindow()
        data = window.project_data()
        data["schema"] = 2
        data["calculation_settings"].update(left_equivalent=2.25, right_equivalent=1.55)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "이전 프로젝트.igr3"
            original = json.dumps(data, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            self.assertTrue(window.load_project(path))
            self.assertTrue(window.input.assumptions().legacy)
            self.assertEqual(window.input.assumptions().left_equivalent, 2.25)
            self.assertIsNone(window.project_path)
            self.assertEqual(window.legacy_path, path.resolve())
            self.assertEqual(path.read_text(encoding="utf-8"), original)

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
        self.assertEqual(data["schema"], 3)
        self.assertEqual(data["calculation_basis"], "intersection-guideline-2025+manual")
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
            dialog.lane_width,
            dialog.grade,
            dialog.right_addition,
            dialog.cycle,
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

    def test_themed_buttonless_numeric_editor_has_room_for_values(self) -> None:
        apply_application_theme(self.app, "light")
        dialog = CoefficientSettingsDialog(["SB", "WB", "EB"], {}, {})
        dialog.show()
        self.app.processEvents()
        editor = dialog.cycle.lineEdit()
        self.assertGreater(editor.width(), editor.fontMetrics().horizontalAdvance(editor.text()))
        dialog.close()

    def test_direct_settings_switch_reset_and_ignore_wheel(self) -> None:
        dialog = CoefficientSettingsDialog(["SB", "WB", "EB"], {}, {"SB": (0.82, 0.86)})
        dialog.show()
        self.app.processEvents()
        auto_height = dialog.height()
        dialog.mode.setCurrentIndex(dialog.mode.findData("direct"))
        self.app.processEvents()
        self.assertLess(dialog.height(), auto_height)
        self.assertFalse(dialog.auto_panel.isVisible())
        spin, _ = dialog.direct_spins["SB"]
        spin.setFocus()
        for delta in (-120, 120):
            wheel = QWheelEvent(
                QPointF(10, 10), QPointF(spin.mapToGlobal(QPoint(10, 10))),
                QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
            )
            QApplication.sendEvent(spin.lineEdit(), wheel)
            self.assertEqual(spin.value(), 0.82)
        QTest.mouseClick(dialog.reset_direct, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.values()[1], dict.fromkeys(("SB", "WB", "EB"), (0.85, 0.85)))
        dialog.close()

    def test_progress_distinguishes_current_and_completed_steps(self) -> None:
        progress = StepProgress()
        progress.set_step(2)
        self.assertEqual([step.property("state") for step, _, _ in progress.steps], [
            "done", "done", "current", "pending",
        ])
        self.assertEqual(progress.steps[0][1].text(), "✓")

    def test_button_motion_reacts_to_mouse_and_keyboard_without_changing_click(self) -> None:
        button = MotionButton("다음")
        button.motion_enabled = True
        button.resize(100, 36)
        button.show()
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        self.assertEqual(button._animation.endValue(), 1.0)
        self.assertEqual(button._animation.duration(), 95)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        self.assertEqual(button._animation.endValue(), 0.0)
        self.assertEqual(button._animation.duration(), 260)
        QTest.keyPress(button, Qt.Key.Key_Space)
        self.assertEqual(button._animation.endValue(), 1.0)
        QTest.keyRelease(button, Qt.Key.Key_Space)
        self.assertEqual(button._animation.endValue(), 0.0)
        self.assertEqual(len(clicks), 2)
        self.assertIsNone(button.graphicsEffect())
        QTest.qWait(300)
        self.assertAlmostEqual(button._get_press_progress(), 0.0, places=3)
        self.assertGreater(button.grab().toImage().pixelColor(50, 18).alpha(), 0)
        button.close()

    def test_button_motion_can_be_disabled(self) -> None:
        button = MotionButton("이전")
        button.motion_enabled = False
        button._animate_pressed(True)
        self.assertEqual(button._get_press_progress(), 0.0)
        self.assertIsNone(button.graphicsEffect())

    def test_button_remains_visible_after_repeated_clicks(self) -> None:
        button = MotionButton("PNG 다운로드")
        button.motion_enabled = True
        button.resize(180, 38)
        button.show()
        for _ in range(20):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.qWait(300)
        image = button.grab().toImage()
        self.assertTrue(button.isVisible())
        self.assertGreater(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 0)

    def test_input_feedback_and_accessible_names(self) -> None:
        page = InputPage()
        page.set_codes(["SB", "WB", "NB"])
        self.assertEqual(page.warning.property("status"), "warning")
        self.assertIn("SB 좌회전", page.cards["SB"].left.accessibleName())
        page.cards["SB"].through.setValue(100)
        page.cards["WB"].through.setValue(100)
        page.cards["NB"].through.setValue(100)
        self.assertEqual(page.warning.property("status"), "ok")

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
