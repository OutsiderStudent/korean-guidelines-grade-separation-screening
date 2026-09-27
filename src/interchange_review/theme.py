"""K-GSS 공통 디자인 토큰과 라이트·다크 테마."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


FONT_FAMILY = "NanumSquare"
THEME_SETTING = "ui/theme"
THEME_CHOICES = ("system", "light", "dark")

LIGHT = {
    "background": "#F2F2F2",
    "surface": "#FFFFFF",
    "surface_alt": "#F7F8FA",
    "input": "#F7F9FC",
    "text": "#172033",
    "muted": "#667085",
    "primary": "#0F3675",
    "primary_hover": "#18498F",
    "primary_pressed": "#0A2858",
    "accent": "#77A4ED",
    "accent_soft": "#E4EDFC",
    "hover": "#EDF3FC",
    "divider": "#E2E7EE",
    "focus": "#77A4ED",
    "disabled": "#E6E9EE",
    "disabled_text": "#98A2B3",
    "scroll": "#AEB8C7",
}

DARK = {
    "background": "#15191F",
    "surface": "#1D232C",
    "surface_alt": "#222A35",
    "input": "#252E3A",
    "text": "#F3F5F8",
    "muted": "#A8B2C2",
    "primary": "#315EAD",
    "primary_hover": "#3B6FC4",
    "primary_pressed": "#244B8C",
    "accent": "#77A4ED",
    "accent_soft": "#273B59",
    "hover": "#293548",
    "divider": "#343E4C",
    "focus": "#77A4ED",
    "disabled": "#2A3039",
    "disabled_text": "#727D8D",
    "scroll": "#667387",
}


def palette(theme: str | None = None) -> dict[str, str]:
    if theme is None:
        app = QApplication.instance()
        theme = str(app.property("kgssTheme") or "light") if app else "light"
    return DARK if theme == "dark" else LIGHT


def saved_theme_preference() -> str:
    value = str(QSettings().value(THEME_SETTING, "system"))
    return value if value in THEME_CHOICES else "system"


def resolve_theme(app: QApplication, preference: str) -> str:
    if preference in ("light", "dark"):
        return preference
    try:
        return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except (AttributeError, RuntimeError):
        return "light"


def load_application_fonts(resource_path: Callable[[str], Path]) -> None:
    for filename in (
        "NanumSquareL.ttf",
        "NanumSquareR.ttf",
        "NanumSquareB.ttf",
        "NanumSquareEB.ttf",
    ):
        path = resource_path(filename)
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def build_stylesheet(theme: str) -> str:
    c = palette(theme)
    values = {key.upper(): value for key, value in c.items()}
    values["FONT"] = FONT_FAMILY
    template = r"""
* { font-family: '@FONT@'; font-size: 10pt; color: @TEXT@; }
QMainWindow, QDialog, QWidget { background: @BACKGROUND@; }
QLabel { background: transparent; }
QToolTip { background: @SURFACE@; color: @TEXT@; border: 1px solid @DIVIDER@; border-radius: 6px; padding: 5px 8px; }
QMenuBar, QMenu, QStatusBar { background: @SURFACE@; color: @TEXT@; }
QMenuBar { padding: 3px 8px; }
QMenuBar::item, QMenu::item { background: transparent; padding: 7px 12px; border-radius: 6px; }
QMenuBar::item:selected, QMenu::item:selected { background: @HOVER@; color: @TEXT@; }
QMenu::separator { height: 1px; background: @DIVIDER@; margin: 5px 10px; }
QStatusBar { color: @MUTED@; border-top: 1px solid @DIVIDER@; }
QTabWidget::pane { border: 0; background: @BACKGROUND@; }
QTabBar { background: @SURFACE@; }
QTabBar::tab { background: transparent; padding: 10px 20px; color: @MUTED@; border: 0; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { color: @PRIMARY@; background: @HOVER@; }
QTabBar::tab:selected { color: @PRIMARY@; border-bottom: 3px solid @ACCENT@; font-weight: 700; }
QFrame#card, QGroupBox { background: @SURFACE@; border: 0; border-radius: 16px; padding: 6px; }
QFrame#actionBar { background: @SURFACE@; border-top: 1px solid @DIVIDER@; }
QLabel#pageTitle { font-size: 19pt; font-weight: 800; color: @TEXT@; }
QLabel#approachCode { font-size: 14pt; font-weight: 800; color: @PRIMARY@; }
QLabel#panelTitle { font-size: 12pt; font-weight: 700; color: @TEXT@; padding: 2px; }
QLabel#sectionTitle { font-weight: 700; color: @TEXT@; padding: 0; }
QLabel#inputHeader { color: @MUTED@; font-size: 9pt; font-weight: 700; }
QLabel#trafficSummary { background: @ACCENT_SOFT@; color: @PRIMARY@; border-radius: 12px; padding: 10px; font-size: 13pt; font-weight: 800; }
QLabel#grandTotal { font-size: 14pt; font-weight: 800; color: @TEXT@; }
QLabel#total { font-weight: 700; color: @PRIMARY@; }
QLabel#warning { background: #FFF4D8; color: #805400; padding: 7px 12px; border-radius: 10px; }
QLabel#warning[status="ok"] { background: #DFF4E9; color: #0A7246; }
QLabel#hint { background: @ACCENT_SOFT@; padding: 8px 14px; color: @PRIMARY@; font-weight: 700; border-radius: 10px; }
QLabel#hint[invalid="true"] { color: #C9363E; background: #FFF0F1; }
QFrame#stepProgress { background: @SURFACE@; border: 0; }
QFrame#progressStep { background: transparent; border: 0; border-radius: 10px; }
QFrame#progressStep[state="current"] { background: @ACCENT_SOFT@; }
QLabel#progressBadge { background: @SURFACE_ALT@; color: @MUTED@; border-radius: 11px; font-size: 9pt; font-weight: 700; }
QLabel#progressBadge[state="current"] { background: @PRIMARY@; color: #FFFFFF; }
QLabel#progressBadge[state="done"] { background: #DDF4E8; color: #128253; }
QLabel#progressText { color: @MUTED@; font-size: 9pt; font-weight: 400; }
QLabel#progressText[state="current"] { color: @PRIMARY@; font-weight: 700; }
QLabel#progressText[state="done"] { color: @TEXT@; font-weight: 700; }
QLabel#resultArea { font-size: 22pt; font-weight: 800; }
QLabel#criticalPair { color: @PRIMARY@; font-weight: 700; padding: 4px; }
QLabel#sideTitle { font-size: 11pt; font-weight: 700; color: @TEXT@; }
QLabel#pairDetail { font-size: 9pt; font-weight: 400; color: @MUTED@; }
QLabel#confirmOverview { font-size: 13pt; font-weight: 800; color: @TEXT@; padding: 4px; }
QLabel#unit { color: @MUTED@; font-size: 9pt; }
QFrame#resultHero { padding: 6px; border-radius: 18px; }
QFrame#approachRow { background: @SURFACE@; border-top: 1px solid @DIVIDER@; }
QFrame#approachRow[alternate="true"] { background: @SURFACE_ALT@; }
QPushButton { background: @SURFACE_ALT@; color: @TEXT@; border: 1px solid transparent; border-radius: 10px; padding: 8px 14px; font-weight: 700; min-height: 18px; }
QPushButton:hover { background: @HOVER@; color: @PRIMARY@; }
QPushButton:pressed { background: @ACCENT_SOFT@; border-color: @ACCENT@; }
QPushButton:checked, QPushButton#primary { background: @PRIMARY@; color: #FFFFFF; }
QPushButton#primary:hover { background: @PRIMARY_HOVER@; color: #FFFFFF; }
QPushButton#primary:pressed { background: @PRIMARY_PRESSED@; border-color: @ACCENT@; }
QPushButton#secondaryButton { background: @ACCENT_SOFT@; color: @PRIMARY@; }
QPushButton#tertiary { background: transparent; color: @MUTED@; }
QPushButton:focus { border: 1px solid @FOCUS@; }
QPushButton:disabled { background: @DISABLED@; color: @DISABLED_TEXT@; }
QPushButton#stepButton { padding: 0; min-width: 28px; max-width: 28px; font-size: 14pt; font-weight: 800; border-radius: 9px; }
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit { background: @INPUT@; color: @TEXT@; border: 1px solid transparent; border-radius: 8px; padding: 6px 8px; selection-background-color: @ACCENT@; }
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QLineEdit:hover { background: @HOVER@; }
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid @FOCUS@; background: @SURFACE@; }
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled { background: @DISABLED@; color: @DISABLED_TEXT@; }
QLineEdit#trafficEditor { min-width: 44px; }
QCheckBox { spacing: 7px; }
QListWidget, QTextBrowser, QScrollArea { background: @SURFACE@; color: @TEXT@; border: 0; border-radius: 14px; padding: 6px; }
QListWidget::item { padding: 10px 12px; border-radius: 8px; }
QListWidget::item:hover { background: @HOVER@; }
QListWidget::item:selected { background: @ACCENT_SOFT@; color: @PRIMARY@; font-weight: 700; }
QTableWidget { background: @SURFACE@; alternate-background-color: @SURFACE_ALT@; color: @TEXT@; border: 0; gridline-color: @DIVIDER@; border-radius: 12px; selection-background-color: @ACCENT_SOFT@; selection-color: @PRIMARY@; }
QHeaderView::section { background: @SURFACE_ALT@; color: @TEXT@; border: 0; border-bottom: 1px solid @DIVIDER@; padding: 8px; font-size: 10pt; font-weight: 700; }
QTableWidget::item { border-bottom: 1px solid @DIVIDER@; padding: 6px; font-weight: 400; }
QTableWidget::item:hover { background: @HOVER@; }
QTableWidget::item:selected { background: @ACCENT_SOFT@; color: @PRIMARY@; }
QScrollBar#autoFadeScrollBar:vertical { background: transparent; width: 10px; margin: 3px 2px; }
QScrollBar#autoFadeScrollBar::handle:vertical { background: @SCROLL@; min-height: 34px; border-radius: 4px; }
QScrollBar#autoFadeScrollBar::handle:vertical:hover { background: @ACCENT@; }
QScrollBar#autoFadeScrollBar::add-line:vertical, QScrollBar#autoFadeScrollBar::sub-line:vertical { height: 0; border: 0; }
QScrollBar#autoFadeScrollBar::add-page:vertical, QScrollBar#autoFadeScrollBar::sub-page:vertical { background: transparent; }
"""
    for key, value in values.items():
        template = template.replace(f"@{key}@", value)
    if theme == "dark":
        template += """
QLabel#warning { background: #40351F; color: #F2C96D; }
QLabel#warning[status="ok"] { background: #1E3A31; color: #73D9A8; }
QLabel#hint[invalid="true"] { color: #FF9DA4; background: #44272B; }
QLabel#progressBadge[state="done"] { background: #1E3A31; color: #73D9A8; }
QTabBar::tab:selected,
QLabel#approachCode,
QLabel#trafficSummary,
QLabel#total,
QLabel#hint,
QLabel#criticalPair,
QLabel#progressText[state="current"] { color: #77A4ED; }
QTableWidget::item:selected { color: #77A4ED; }
"""
    return template


def apply_application_theme(app: QApplication, preference: str, *, persist: bool = False) -> str:
    if preference not in THEME_CHOICES:
        preference = "system"
    if persist:
        QSettings().setValue(THEME_SETTING, preference)
    resolved = resolve_theme(app, preference)
    app.setProperty("kgssThemePreference", preference)
    app.setProperty("kgssTheme", resolved)
    app.setFont(QFont(FONT_FAMILY, 10))
    app.setStyleSheet(build_stylesheet(resolved))
    for widget in app.topLevelWidgets():
        widget.update()
    return resolved


STYLE = build_stylesheet("light")
DARK_STYLE = build_stylesheet("dark")
