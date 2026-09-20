"""입체화검토 v3.6.0 PySide6 데스크톱 GUI."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontDatabase, QIcon, QIntValidator,
    QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .chart import CapacityChart, render_pair_chart, save_pair_chart
from .screening import (
    APPROACH_ORDER,
    ApproachInput,
    CoefficientAssumptions,
    IntersectionResult,
    analyze_intersection,
)
from .engine import SignalAssumptions
from .updater import UpdateController


APP_NAME = "입체화검토"
APP_VERSION = "3.6.0"
APP_AUTHOR = "made by NYH"
PROJECT_FILTER = "입체화검토 프로젝트 (*.igr3)"
AREA_STYLE = {
    "A": ("#E8F8F0", "#15935B", "회전차로 부가 없이 신호처리가 가능합니다."),
    "B": ("#EAF2FF", "#2375E8", "회전차로를 부가하면 평면 신호처리가 가능합니다."),
    "C": ("#FFF1DE", "#D97706", "직진 부가차로 설치 또는 입체교차 처리가 필요합니다."),
    "D": ("#FFE9EC", "#D9363E", "단로부 확폭 또는 추가 도로계획이 필요합니다."),
}


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


class AutoFadeScrollBar(QScrollBar):
    """공간은 유지하면서 사용 후 부드럽게 사라지는 원통형 스크롤바."""

    def __init__(self, orientation: Qt.Orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setObjectName("autoFadeScrollBar")
        self.setFixedWidth(10 if orientation == Qt.Orientation.Vertical else self.sizeHint().width())
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(280)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1_400)
        self._timer.timeout.connect(self._fade)
        self.valueChanged.connect(self.reveal)
        self.rangeChanged.connect(self._range_changed)
        self.sliderPressed.connect(self.reveal)
        self.sliderReleased.connect(self._schedule_fade)
        self._effect.setOpacity(0.0)

    def _range_changed(self, minimum: int, maximum: int) -> None:
        if maximum <= minimum:
            self._animation.stop()
            self._effect.setOpacity(0.0)

    def reveal(self, *args) -> None:
        if self.maximum() <= self.minimum():
            return
        self._animation.stop()
        self._effect.setOpacity(1.0)
        self._timer.start()

    def _schedule_fade(self) -> None:
        self._timer.start()

    def _fade(self) -> None:
        if self.isSliderDown():
            return
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.reveal()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._schedule_fade()
        super().leaveEvent(event)


def install_auto_scrollbar(widget) -> None:
    widget.setVerticalScrollBar(AutoFadeScrollBar(Qt.Orientation.Vertical, widget))


class IntersectionPreview(QWidget):
    """접근로 선택과 실제 차선 수를 보여주는 클릭형 평면도."""

    selectionChanged = Signal()
    selectionRejected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.codes: list[str] = ["SB", "NB", "WB", "EB"]
        self.available_codes: list[str] = list(self.codes)
        self.lanes: dict[str, int] = {}
        self.highlight_codes: set[str] = set()
        self.selectable = False
        self.setMinimumSize(300, 300)

    def set_data(self, codes: list[str], lanes: dict[str, int] | None = None) -> None:
        self.codes = [code for code in APPROACH_ORDER if code in codes]
        if not self.selectable:
            self.available_codes = list(self.codes)
        self.lanes = lanes or {}
        self.update()

    def set_selectable(self, enabled: bool) -> None:
        self.selectable = enabled
        self.available_codes = list(APPROACH_ORDER) if enabled else list(self.codes)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_highlight(self, codes: list[str] | tuple[str, ...] | set[str]) -> None:
        self.highlight_codes = set(codes)
        self.update()

    @staticmethod
    def _vectors() -> dict[str, QPointF]:
        return {
            "SB": QPointF(0, -1), "NB": QPointF(0, 1),
            "WB": QPointF(1, 0), "EB": QPointF(-1, 0),
            "SEB": QPointF(-.707, -.707), "SWB": QPointF(.707, -.707),
            "NWB": QPointF(.707, .707), "NEB": QPointF(-.707, .707),
        }

    def _geometry(self) -> tuple[QPointF, float]:
        # 좁은 미리보기에서도 접근로 코드가 잘리지 않도록 사방 여백을 확보한다.
        margin = 70 if min(self.width(), self.height()) < 240 else 90
        radius = max(30.0, min((self.width() - margin) / 2, (self.height() - margin) / 2))
        return QPointF(self.width() / 2, self.height() / 2), radius

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.selectable or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        center, radius = self._geometry()
        point = event.position()
        best_code, best_distance = None, float("inf")
        for code, vector in self._vectors().items():
            dx, dy = point.x() - center.x(), point.y() - center.y()
            projection = max(30.0, min(radius + 28.0, dx * vector.x() + dy * vector.y()))
            nearest = center + QPointF(vector.x() * projection, vector.y() * projection)
            distance = ((point.x() - nearest.x()) ** 2 + (point.y() - nearest.y()) ** 2) ** .5
            if distance < best_distance:
                best_code, best_distance = code, distance
        if best_code is None or best_distance > 34:
            return
        selected = set(self.codes)
        if best_code in selected:
            if len(selected) <= 3:
                self.selectionRejected.emit("교차로는 최소 3개 접근로가 필요합니다.")
                return
            selected.remove(best_code)
        else:
            if len(selected) >= 6:
                self.selectionRejected.emit("최대 6개 접근로까지 선택할 수 있습니다.")
                return
            selected.add(best_code)
        self.codes = [code for code in APPROACH_ORDER if code in selected]
        self.selectionChanged.emit()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 부모 화면과 같은 배경색을 사용해 평면도 위젯의 사각 경계를 없앤다.
        p.fillRect(self.rect(), QColor("#F5F7FA"))
        center, radius = self._geometry()
        vectors = self._vectors()
        p.setFont(QFont("Noto Sans KR", 10, QFont.Weight.Bold))
        for code in self.available_codes:
            v = vectors[code]
            outer = center + QPointF(v.x() * radius, v.y() * radius)
            lane_count = max(1, self.lanes.get(code, 2))
            active = code in self.codes
            highlighted = not self.highlight_codes or code in self.highlight_codes
            width_cap = max(24.0, min(70.0, radius * .80))
            schematic_lanes = min(lane_count, 6)
            width = min(max(22.0, schematic_lanes * 7.0), width_cap)
            if self.highlight_codes and not highlighted:
                width = min(width, 18.0)
            road_color = QColor("#344054") if active and highlighted else QColor("#D9DFE8")
            label_color = QColor("#1769D2") if active and highlighted else QColor("#AAB3C1")
            p.setPen(QPen(road_color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawLine(center, outer)
            perpendicular = QPointF(-v.y(), v.x())
            displayed_lanes = schematic_lanes if highlighted else 1
            for lane_index in range(1, displayed_lanes):
                offset = -width / 2 + width * lane_index / displayed_lanes
                start = center + QPointF(perpendicular.x() * offset, perpendicular.y() * offset)
                end = outer + QPointF(perpendicular.x() * offset, perpendicular.y() * offset)
                marking = QColor("#FFFFFF") if active and highlighted else QColor("#F4F6F9")
                p.setPen(QPen(marking, 1.5, Qt.PenStyle.DashLine))
                p.drawLine(start, end)
            label_gap = 18 if radius < 80 else 27
            label_pos = center + QPointF(v.x() * (radius + label_gap), v.y() * (radius + label_gap))
            p.setPen(label_color)
            p.drawText(QRectF(label_pos.x() - 35, label_pos.y() - 14, 70, 28), Qt.AlignmentFlag.AlignCenter, code)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        hub_radius = min(36.0, max(17.0, radius * .45))
        p.drawEllipse(center, hub_radius, hub_radius)
        p.setPen(QColor("#2375E8"))
        p.drawText(
            QRectF(center.x() - hub_radius, center.y() - hub_radius / 2, hub_radius * 2, hub_radius),
            Qt.AlignmentFlag.AlignCenter,
            f"{len(self.codes)}지",
        )


class TopologyPage(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 14)
        title = QLabel("교차로 형태를 선택해 주세요")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        instruction = QLabel("평면도의 접근로를 클릭해 켜거나 끄세요. 꺼진 접근로는 흐리게 표시됩니다.")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(instruction)
        self.preview = IntersectionPreview()
        self.preview.set_selectable(True)
        self.preview.setMinimumSize(540, 420)
        self.preview.selectionChanged.connect(self._selection_changed)
        self.preview.selectionRejected.connect(self._selection_rejected)
        root.addWidget(self.preview, 1, Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.hint)
        self.select_count(4)

    def select_count(self, count: int) -> None:
        defaults = {
            3: ["NB", "WB", "EB"],
            4: ["SB", "NB", "WB", "EB"],
            5: ["SB", "NB", "WB", "EB", "SEB"],
            6: ["SB", "NB", "WB", "EB", "SEB", "NWB"],
        }[count]
        self.preview.set_data(defaults)
        self._selection_changed()

    def set_codes(self, codes: list[str]) -> None:
        if not 3 <= len(codes) <= 6:
            raise ValueError("접근로는 3~6개여야 합니다.")
        self.preview.set_data(codes)
        self._selection_changed()

    def _selection_changed(self) -> None:
        selected = self.selected_codes()
        self.hint.setText(f"{len(selected)}지 교차로 · {', '.join(selected)}")
        self.changed.emit()

    def _selection_rejected(self, message: str) -> None:
        self.hint.setText(message)

    def selected_codes(self) -> list[str]:
        return list(self.preview.codes)

    @property
    def count(self) -> int:
        return len(self.preview.codes)

    def is_valid(self) -> bool:
        return 3 <= self.count <= 6


class SelectAllLineEdit(QLineEdit):
    """클릭하면 기존 숫자를 즉시 덮어쓸 수 있는 입력칸."""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        self.selectAll()


class TrafficInput(SelectAllLineEdit):
    valueChanged = Signal(int)

    def __init__(self) -> None:
        super().__init__("0")
        self.setValidator(QIntValidator(0, 99_999, self))
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setObjectName("trafficEditor")
        self.setFixedWidth(90)
        self.textChanged.connect(lambda: self.valueChanged.emit(self.value()))

    def value(self) -> int:
        return int(self.text() or 0)

    def setValue(self, value: int) -> None:  # noqa: N802
        self.setText(str(max(0, min(99_999, int(value)))))


class LaneStepper(QWidget):
    valueChanged = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._value = 2
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.minus = QPushButton("−")
        self.plus = QPushButton("+")
        for button in (self.minus, self.plus):
            button.setObjectName("stepButton")
            button.setFixedSize(28, 28)
        self.editor = SelectAllLineEdit("2")
        self.editor.setValidator(QIntValidator(1, 12, self))
        self.editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor.setFixedWidth(38)
        self.editor.editingFinished.connect(self._from_editor)
        self.minus.clicked.connect(lambda: self.setValue(self._value - 1))
        self.plus.clicked.connect(lambda: self.setValue(self._value + 1))
        layout.addWidget(self.minus)
        layout.addWidget(self.editor)
        layout.addWidget(self.plus)

    def _from_editor(self) -> None:
        self.setValue(int(self.editor.text() or self._value))

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802
        value = max(1, min(12, int(value)))
        changed = value != self._value
        self._value = value
        self.editor.setText(str(value))
        self.minus.setEnabled(value > 1)
        self.plus.setEnabled(value < 12)
        if changed:
            self.valueChanged.emit(value)


class ApproachCard(QFrame):
    changed = Signal()

    def __init__(self, code: str) -> None:
        super().__init__()
        self.code = code
        self.setObjectName("approachRow")
        self.setMinimumHeight(50)
        self.setMaximumHeight(74)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setHorizontalSpacing(8)
        label = QLabel(code)
        label.setObjectName("approachCode")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lanes = LaneStepper()
        self.heavy = QDoubleSpinBox()
        self.heavy.setRange(0, 100)
        self.heavy.setDecimals(1)
        self.heavy.setSuffix(" %")
        self.heavy.setValue(20)
        self.heavy.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.heavy.setFixedWidth(70)
        self.left = TrafficInput()
        self.through = TrafficInput()
        self.right = TrafficInput()
        self.total_label = QLabel("0")
        self.total_label.setObjectName("total")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        widgets = (label, self.lanes, self.left, self.through, self.right, self.heavy, self.total_label)
        for column, widget in enumerate(widgets):
            alignment = Qt.AlignmentFlag.AlignCenter if column in (0, 1, 5) else Qt.AlignmentFlag.AlignVCenter
            layout.addWidget(widget, 0, column, alignment)
        for column in (2, 3, 4):
            layout.setColumnMinimumWidth(column, 90)
        layout.setColumnMinimumWidth(0, 52)
        layout.setColumnMinimumWidth(1, 106)
        layout.setColumnMinimumWidth(5, 74)
        layout.setColumnMinimumWidth(6, 82)
        for widget in (self.lanes, self.left, self.through, self.right, self.heavy):
            widget.valueChanged.connect(self._changed)

    def _changed(self) -> None:
        self.total_label.setText(f"{self.total():,}")
        self.changed.emit()

    def total(self) -> int:
        return self.left.value() + self.through.value() + self.right.value()

    def value(self) -> ApproachInput:
        return ApproachInput(
            code=self.code,
            lanes=self.lanes.value(),
            left=self.left.value(),
            through=self.through.value(),
            right=self.right.value(),
            heavy_percent=self.heavy.value(),
        )

    def set_value(self, data: dict) -> None:
        self.lanes.setValue(int(data.get("lanes", 2)))
        self.left.setValue(int(data.get("left", 0)))
        self.through.setValue(int(data.get("through", 0)))
        self.right.setValue(int(data.get("right", 0)))
        self.heavy.setValue(float(data.get("heavy_percent", 20)))


class CoefficientSettingsDialog(QDialog):
    """기본 화면을 복잡하게 만들지 않는 선택형 상세 계산 설정."""

    def __init__(self, codes: list[str], settings: dict, direct: dict[str, tuple[float, float]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("상세 보정 설정")
        self.resize(590, 530)
        root = QVBoxLayout(self)
        intro = QLabel(
            "자동 산정은 도로용량편람의 통합 회전식과 중차량식을 적용합니다. "
            "별도 용량분석 계수가 있으면 접근로별 직접 입력을 선택하세요."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("자동 산정 (도로용량편람)", "auto")
        self.mode.addItem("보정계수 직접 입력", "direct")
        self.mode.setCurrentIndex(1 if settings.get("mode") == "direct" else 0)
        form.addRow("계산 방식", self.mode)
        self.left_equivalent = self._factor_spin(1.0, 10.0, settings.get("left_equivalent", 2.0), 2)
        self.right_equivalent = self._factor_spin(1.0, 10.0, settings.get("right_equivalent", 1.5), 2)
        self.heavy_equivalent = self._factor_spin(1.0, 10.0, settings.get("heavy_equivalent", 1.8), 2)
        form.addRow("좌회전 직진환산계수 EL", self.left_equivalent)
        form.addRow("우회전 직진환산계수 ER", self.right_equivalent)
        form.addRow("중차량 승용차환산계수 EHV", self.heavy_equivalent)
        root.addLayout(form)

        direct_title = QLabel("접근로별 직접 보정계수")
        direct_title.setObjectName("panelTitle")
        root.addWidget(direct_title)
        self.direct_table = QTableWidget(len(codes), 3)
        install_auto_scrollbar(self.direct_table)
        self.direct_table.setHorizontalHeaderLabels(["접근로", "통합 회전계수", "중차량계수"])
        self.direct_table.verticalHeader().setVisible(False)
        self.direct_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.direct_spins: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        for row, code in enumerate(codes):
            item = QTableWidgetItem(code)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.direct_table.setItem(row, 0, item)
            turn_value, heavy_value = direct.get(code, (0.85, 0.85))
            turn = self._factor_spin(0.001, 1.0, turn_value, 4)
            heavy = self._factor_spin(0.001, 1.0, heavy_value, 4)
            self.direct_table.setCellWidget(row, 1, turn)
            self.direct_table.setCellWidget(row, 2, heavy)
            self.direct_table.setRowHeight(row, 40)
            self.direct_spins[code] = (turn, heavy)
        self.direct_table.setFixedHeight(min(300, 50 + len(codes) * 40))
        root.addWidget(self.direct_table)
        root.addSpacing(8)

        pprime = card()
        pprime_box = QVBoxLayout(pprime)
        pprime_box.setContentsMargins(12, 8, 12, 10)
        pprime_box.setSpacing(4)
        self.pprime_title = QLabel("회전차로 설치 시 P′ 가정")
        self.pprime_title.setObjectName("sectionTitle")
        pprime_box.addWidget(self.pprime_title)
        pform = QFormLayout()
        pform.setContentsMargins(0, 0, 0, 0)
        pform.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.right_addition = self._factor_spin(0.0, 5_000.0, settings.get("right_addition", 600.0), 1)
        self.effective_green = self._factor_spin(1.0, 79.0, settings.get("effective_green", 36.0), 1)
        self.left_per_cycle = self._factor_spin(0.0, 20.0, settings.get("left_per_cycle", 2.0), 2)
        self.utilization = self._factor_spin(0.01, 1.0, settings.get("utilization", 0.9), 3)
        pform.addRow("우회전 부가용량 (대/시·접근로)", self.right_addition)
        pform.addRow("유효녹색시간 (초)", self.effective_green)
        pform.addRow("좌회전 통행량 (대/주기)", self.left_per_cycle)
        pform.addRow("유입부 이용계수", self.utilization)
        pprime_box.addLayout(pform)
        root.addWidget(pprime)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._update_mode)
        self._update_mode()

    @staticmethod
    def _factor_spin(minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(float(value))
        spin.setSingleStep(0.01 if decimals >= 2 else 10.0)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setMinimumHeight(32)
        return spin

    def _update_mode(self) -> None:
        direct = self.mode.currentData() == "direct"
        self.direct_table.setEnabled(direct)
        for widget in (self.left_equivalent, self.right_equivalent, self.heavy_equivalent):
            widget.setEnabled(not direct)

    def values(self) -> tuple[dict, dict[str, tuple[float, float]]]:
        settings = {
            "mode": self.mode.currentData(),
            "left_equivalent": self.left_equivalent.value(),
            "right_equivalent": self.right_equivalent.value(),
            "heavy_equivalent": self.heavy_equivalent.value(),
            "right_addition": self.right_addition.value(),
            "effective_green": self.effective_green.value(),
            "left_per_cycle": self.left_per_cycle.value(),
            "utilization": self.utilization.value(),
        }
        direct = {
            code: (turn.value(), heavy.value())
            for code, (turn, heavy) in self.direct_spins.items()
        }
        return settings, direct


class InputPage(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 8)
        root.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("접근로별 교통량을 입력해 주세요")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.calculation_settings = {
            "mode": "auto",
            "left_equivalent": 2.0,
            "right_equivalent": 1.5,
            "heavy_equivalent": 1.8,
            "right_addition": 600.0,
            "effective_green": 36.0,
            "left_per_cycle": 2.0,
            "utilization": 0.9,
        }
        self.direct_factors: dict[str, tuple[float, float]] = {}
        self.advanced_button = QPushButton("상세 보정 설정")
        self.advanced_button.setObjectName("secondaryButton")
        title_row.addWidget(self.advanced_button)
        self.same_heavy = QCheckBox("모든 접근로에 같은 중차량 비율 적용")
        self.same_heavy.setChecked(True)
        self.global_heavy = QDoubleSpinBox()
        self.global_heavy.setRange(0, 100)
        self.global_heavy.setDecimals(1)
        self.global_heavy.setValue(20)
        self.global_heavy.setSuffix(" %")
        self.global_heavy.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.global_heavy.setFixedWidth(78)
        title_row.addWidget(self.same_heavy)
        title_row.addWidget(self.global_heavy)
        root.addLayout(title_row)
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        root.addWidget(self.warning)
        body = QHBoxLayout()
        body.setSpacing(12)
        preview_panel = card()
        preview_panel.setMinimumWidth(280)
        preview_panel.setMaximumWidth(320)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 8, 10, 8)
        preview_layout.setSpacing(4)
        preview_title = QLabel("교차로 미리보기")
        preview_title.setObjectName("panelTitle")
        preview_layout.addWidget(preview_title)
        self.preview = IntersectionPreview()
        self.preview.setMinimumSize(260, 300)
        preview_layout.addWidget(self.preview, 1)
        self.total = QLabel("전체 유입교통량\n0 대/시")
        self.total.setObjectName("trafficSummary")
        self.total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.total)
        body.addWidget(preview_panel)

        input_panel = card()
        panel_layout = QVBoxLayout(input_panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(0)
        panel_head = QHBoxLayout()
        panel_title = QLabel("접근로별 입력")
        panel_title.setObjectName("panelTitle")
        panel_head.addWidget(panel_title)
        panel_head.addStretch()
        panel_unit = QLabel("교통량 단위: 대/시")
        panel_unit.setObjectName("unit")
        panel_head.addWidget(panel_unit)
        panel_layout.addLayout(panel_head)
        header = QGridLayout()
        header.setContentsMargins(10, 6, 10, 6)
        header.setHorizontalSpacing(8)
        for column, text in enumerate(("접근로", "편도 차로수", "좌회전", "직진", "우회전", "중차량", "합계")):
            item = QLabel(text)
            item.setObjectName("inputHeader")
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(item, 0, column)
        for column in (2, 3, 4):
            header.setColumnMinimumWidth(column, 90)
        header.setColumnMinimumWidth(0, 52)
        header.setColumnMinimumWidth(1, 106)
        header.setColumnMinimumWidth(5, 74)
        header.setColumnMinimumWidth(6, 82)
        panel_layout.addLayout(header)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        panel_layout.addLayout(self.rows_layout)
        body.addWidget(input_panel, 1)
        root.addLayout(body, 1)
        self.cards: dict[str, ApproachCard] = {}
        self.same_heavy.toggled.connect(self._apply_global)
        self.global_heavy.valueChanged.connect(self._apply_global)
        self.advanced_button.clicked.connect(self._show_settings)

    def _show_settings(self) -> None:
        dialog = CoefficientSettingsDialog(list(self.cards), self.calculation_settings, self.direct_factors, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.calculation_settings, self.direct_factors = dialog.values()
            mode = "직접 계수" if self.calculation_settings["mode"] == "direct" else "자동 산정"
            self.advanced_button.setText(f"상세 보정 설정 · {mode}")
            self.changed.emit()

    def set_codes(self, codes: list[str], preserve: bool = True) -> None:
        codes = [code for code in APPROACH_ORDER if code in codes]
        previous = {
            code: vars(item.value())
            for code, item in self.cards.items()
        } if preserve else {}
        for card_widget in self.cards.values():
            card_widget.setParent(None)
        self.cards = {}
        row_height = min(90, max(56, 320 // max(1, len(codes))))
        for index, code in enumerate(codes):
            item = ApproachCard(code)
            item.setFixedHeight(row_height)
            item.setProperty("alternate", index % 2 == 1)
            item.changed.connect(self._card_changed)
            if code in previous:
                item.set_value(previous[code])
            self.rows_layout.addWidget(item)
            self.cards[code] = item
        self._apply_global()
        self._card_changed()

    def _apply_global(self) -> None:
        active = self.same_heavy.isChecked()
        self.global_heavy.setEnabled(active)
        for item in self.cards.values():
            item.heavy.setEnabled(not active)
            if active:
                item.heavy.setValue(self.global_heavy.value())
        self._card_changed()

    def _card_changed(self) -> None:
        total = sum(item.total() for item in self.cards.values())
        zeros = [code for code, item in self.cards.items() if item.total() == 0]
        self.total.setText(f"전체 유입교통량\n{total:,} 대/시")
        self.warning.setText(
            "교통량이 0인 접근로: " + ", ".join(zeros) + " · 실제 0인지 확인해 주세요."
            if zeros else "모든 접근로 입력이 완료됐습니다."
        )
        self.preview.set_data(list(self.cards), {code: item.lanes.value() for code, item in self.cards.items()})
        self.changed.emit()

    def values(self) -> list[ApproachInput]:
        values = []
        direct_mode = self.calculation_settings["mode"] == "direct"
        for code in APPROACH_ORDER:
            if code not in self.cards:
                continue
            value = self.cards[code].value()
            if direct_mode:
                turn, heavy = self.direct_factors.get(code, (0.85, 0.85))
                value = replace(value, direct_turn_factor=turn, direct_heavy_factor=heavy)
            values.append(value)
        return values

    def assumptions(self) -> CoefficientAssumptions:
        return CoefficientAssumptions(
            left_equivalent=float(self.calculation_settings["left_equivalent"]),
            right_equivalent=float(self.calculation_settings["right_equivalent"]),
            heavy_equivalent=float(self.calculation_settings["heavy_equivalent"]),
        )

    def signal_assumptions(self) -> SignalAssumptions:
        return SignalAssumptions(
            cycle_seconds=80.0,
            effective_green_seconds=float(self.calculation_settings["effective_green"]),
            left_turn_vehicles_per_cycle=float(self.calculation_settings["left_per_cycle"]),
            added_right_turn_capacity=float(self.calculation_settings["right_addition"]),
            utilization_factor=float(self.calculation_settings["utilization"]),
        )

    def settings_data(self) -> dict:
        return {
            **self.calculation_settings,
            "direct_factors": {
                code: {"turn": turn, "heavy": heavy}
                for code, (turn, heavy) in self.direct_factors.items()
            },
        }

    def apply_settings_data(self, data: dict | None) -> None:
        if not data:
            return
        for key in self.calculation_settings:
            if key in data:
                self.calculation_settings[key] = data[key]
        self.direct_factors = {
            code: (float(values["turn"]), float(values["heavy"]))
            for code, values in data.get("direct_factors", {}).items()
            if code in APPROACH_ORDER
        }
        mode = "직접 계수" if self.calculation_settings["mode"] == "direct" else "자동 산정"
        self.advanced_button.setText(f"상세 보정 설정 · {mode}")

    def reset_settings(self) -> None:
        self.calculation_settings.update(
            mode="auto",
            left_equivalent=2.0,
            right_equivalent=1.5,
            heavy_equivalent=1.8,
            right_addition=600.0,
            effective_green=36.0,
            left_per_cycle=2.0,
            utilization=0.9,
        )
        self.direct_factors = {}
        self.advanced_button.setText("상세 보정 설정")

    def is_valid(self) -> bool:
        return len([item for item in self.cards.values() if item.total() > 0]) >= 2


class ConfirmPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 14, 24, 12)
        root.setSpacing(8)
        title = QLabel("입력 내용을 확인해 주세요")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.overview = QLabel()
        self.overview.setObjectName("confirmOverview")
        root.addWidget(self.overview)
        self.table = QTableWidget(0, 7)
        install_auto_scrollbar(self.table)
        self.table.setHorizontalHeaderLabels(["접근로", "차로", "좌회전", "직진", "우회전", "합계", "중차량"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setFont(QFont("Noto Sans KR", 11, QFont.Weight.DemiBold))
        root.addWidget(self.table, 1)
        assumptions = card()
        assumptions.setMinimumHeight(108)
        box = QVBoxLayout(assumptions)
        box.setContentsMargins(14, 8, 14, 10)
        box.setSpacing(4)
        self.assumptions_title = QLabel("적용 가정")
        self.assumptions_title.setObjectName("sectionTitle")
        box.addWidget(self.assumptions_title)
        self.assumption_text = QLabel()
        self.assumption_text.setWordWrap(True)
        self.assumption_text.setMinimumHeight(64)
        box.addWidget(self.assumption_text)
        root.addWidget(assumptions)
        root.addStretch()

    def set_values(
        self,
        count: int,
        values: list[ApproachInput],
        assumptions: CoefficientAssumptions | None = None,
        signal: SignalAssumptions | None = None,
    ) -> None:
        assumptions = assumptions or CoefficientAssumptions()
        signal = signal or SignalAssumptions()
        total = sum(x.total for x in values)
        self.overview.setText(f"{count}지 교차로    ·    전체 유입교통량 {total:,} 대/시")
        self.table.setRowCount(len(values))
        for row, value in enumerate(values):
            texts = [
                value.code, f"{value.lanes:,}", f"{value.left:,}", f"{value.through:,}",
                f"{value.right:,}", f"{value.total:,}", f"{value.heavy_percent:.1f}%",
            ]
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                alignment = Qt.AlignmentFlag.AlignCenter if column == 0 else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                item.setTextAlignment(alignment)
                if column in (0, 5):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 40)
        table_height = self.table.horizontalHeader().height() + len(values) * 40 + 4
        self.table.setFixedHeight(table_height)
        direct = any(value.direct_turn_factor is not None for value in values)
        factor_line = (
            "보정계수: 접근로별 직접 입력값을 적용합니다."
            if direct
            else "자동 보정계수: 도로용량편람 통합 회전식·중차량식, "
            f"EL={assumptions.left_equivalent:.2f}, ER={assumptions.right_equivalent:.2f}, "
            f"EHV={assumptions.heavy_equivalent:.2f}."
        )
        self.assumption_text.setText(
            "2025 교차로 설계 지침의 A·B·C·D 판정식과 차로당 1,800대/시를 적용합니다.\n"
            f"{factor_line}\n"
            f"회전차로 설치 시: 유효녹색 {signal.effective_green_seconds:g}초, "
            f"좌회전 {signal.left_turn_vehicles_per_cycle:g}대/주기, "
            f"우회전 부가용량 {signal.added_right_turn_capacity:g}대/시·접근로, "
            f"이용계수 {signal.utilization_factor:g}."
        )


class ResultPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.result: IntersectionResult | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 10, 18, 10)
        root.setSpacing(7)
        self.hero = QFrame()
        self.hero.setObjectName("resultHero")
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(14, 8, 14, 8)
        self.area = QLabel("판정: 영역 –")
        self.area.setObjectName("resultArea")
        hero_layout.addWidget(self.area)
        hero_layout.addStretch()
        self.recommendation = QLabel()
        self.recommendation.setWordWrap(True)
        hero_layout.addWidget(self.recommendation, 2)
        root.addWidget(self.hero)
        self.extension = QLabel()
        self.extension.setObjectName("warning")
        root.addWidget(self.extension)
        body = QHBoxLayout()
        body.setSpacing(9)
        left = QVBoxLayout()
        left.setSpacing(5)
        left.addWidget(QLabel("접근로 쌍별 판정"))
        self.critical_label = QLabel()
        self.critical_label.setObjectName("criticalPair")
        left.addWidget(self.critical_label)
        self.pairs = QTableWidget(0, 2)
        install_auto_scrollbar(self.pairs)
        self.pairs.setHorizontalHeaderLabels(["접근로 쌍", "영역"])
        self.pairs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.pairs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.pairs.verticalHeader().setVisible(False)
        self.pairs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pairs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pairs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pairs.setAlternatingRowColors(True)
        self.pairs.setFont(QFont("Noto Sans KR", 11, QFont.Weight.DemiBold))
        self.pairs.setMinimumWidth(230)
        self.pairs.setMinimumHeight(165)
        self.pairs.currentCellChanged.connect(self._pair_selected)
        left.addWidget(self.pairs, 3)
        selected_title = QLabel("선택한 접근로 쌍")
        selected_title.setObjectName("sideTitle")
        left.addWidget(selected_title)
        self.pair_preview = IntersectionPreview()
        self.pair_preview.setMinimumSize(225, 165)
        self.pair_preview.setMaximumHeight(165)
        left.addWidget(self.pair_preview, 2)
        body.addLayout(left, 1)

        self.chart = CapacityChart()
        body.addWidget(self.chart, 3)

        side_panel = QWidget()
        side_panel.setMinimumWidth(290)
        side = QVBoxLayout(side_panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(5)
        self.detail_title = QLabel("상세 계산값")
        self.detail_title.setObjectName("sideTitle")
        self.detail_title.setWordWrap(True)
        side.addWidget(self.detail_title)
        self.detail_table = QTableWidget(8, 3)
        install_auto_scrollbar(self.detail_table)
        self.detail_table.setHorizontalHeaderLabels(["구분", "접근로 1", "접근로 2"])
        self.detail_table.setVerticalHeaderLabels([])
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.detail_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.detail_table.setShowGrid(True)
        self.detail_table.setFont(QFont("Noto Sans KR", 9, QFont.Weight.DemiBold))
        self.detail_table.setFixedHeight(225)
        side.addWidget(self.detail_table)
        self.copy_button = QPushButton("클립보드에 복사")
        self.png_button = QPushButton("PNG 다운로드")
        self.detail_button = QPushButton("상세 그래프 다운로드")
        self.all_button = QPushButton("모든 그래프 PNG 다운로드")
        self.text_button = QPushButton("계산 결과 복사")
        for button in (self.copy_button, self.png_button, self.detail_button, self.all_button, self.text_button):
            button.setMinimumHeight(30)
            side.addWidget(button)
        body.addWidget(side_panel, 1)
        root.addLayout(body, 1)
        self.copy_button.clicked.connect(self.copy_current)
        self.png_button.clicked.connect(lambda: self.save_current(False))
        self.detail_button.clicked.connect(lambda: self.save_current(True))
        self.all_button.clicked.connect(self.save_all)
        self.text_button.clicked.connect(self.copy_result_text)

    def set_result(self, result: IntersectionResult) -> None:
        self.result = result
        bg, color, message = AREA_STYLE[result.area.value]
        self.hero.setStyleSheet(f"QFrame#resultHero {{ background:{bg}; border:1px solid {color}; border-radius:18px; }}")
        self.area.setStyleSheet(f"color:{color};")
        self.area.setText(f"판정: 영역 {result.area.value}")
        self.recommendation.setText(f"{message}\n가장 불리한 접근로 쌍: {result.critical_pair.name} · 전체 {result.total_traffic:,} 대/시")
        self.extension.setText(
            "※ 3·5·6지 결과는 지침의 4지 교차로 판정식을 충돌 접근로 쌍에 보수적으로 확장하고 최악 결과를 채택합니다."
            if result.is_extended_method else "지침의 4지 교차로 기준에 따라 4개 충돌 접근로 쌍을 검토했습니다."
        )
        self.critical_label.setText(f"가장 불리한 접근로 쌍  {result.critical_pair.name}")
        self.pairs.setRowCount(len(result.pairs))
        for row, pair in enumerate(result.pairs):
            pair_item = QTableWidgetItem(pair.name)
            area_item = QTableWidgetItem(pair.classification.area.value)
            pair_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            area_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if pair is result.critical_pair:
                pair_item.setBackground(QColor("#EAF2FF"))
                area_item.setBackground(QColor("#EAF2FF"))
                font = pair_item.font()
                font.setBold(True)
                pair_item.setFont(font)
                area_item.setFont(font)
            self.pairs.setItem(row, 0, pair_item)
            self.pairs.setItem(row, 1, area_item)
            self.pairs.setRowHeight(row, 31)
        self.pair_preview.set_data(
            [item.input.code for item in result.approaches],
            {item.input.code: item.input.lanes for item in result.approaches},
        )
        critical_index = list(result.pairs).index(result.critical_pair)
        self.pairs.selectRow(critical_index)
        self.pairs.setCurrentCell(critical_index, 0)

    def current_pair(self):
        if self.result is None or self.pairs.currentRow() < 0:
            return None
        return self.result.pairs[self.pairs.currentRow()]

    def _pair_selected(self, row: int, *args) -> None:
        pair = self.current_pair()
        self.chart.set_pair(pair)
        if pair:
            a, b = pair.first, pair.second
            self.pair_preview.set_highlight([a.input.code, b.input.code])
            self.detail_title.setText(f"{pair.name} · 영역 {pair.classification.area.value}  |  단위: 대/시")
            self.detail_table.setHorizontalHeaderLabels(["구분", a.input.code, b.input.code])
            rows = [
                ("교통량 q", f"{a.direction.hourly_design_traffic_q:,.0f}", f"{b.direction.hourly_design_traffic_q:,.0f}"),
                ("좌/우(%)", f"{a.input.left_ratio * 100:.1f}/{a.input.right_ratio * 100:.1f}", f"{b.input.left_ratio * 100:.1f}/{b.input.right_ratio * 100:.1f}"),
                ("통합 회전계수", f"{a.turn_factor:.4f}", f"{b.turn_factor:.4f}"),
                ("중차량계수", f"{a.heavy_factor:.4f}", f"{b.heavy_factor:.4f}"),
                ("P", f"{a.direction.no_turn_lane_capacity_p_raw:,.1f}", f"{b.direction.no_turn_lane_capacity_p_raw:,.1f}"),
                ("P′", f"{a.direction.with_turn_lane_capacity_p_prime_raw:,.1f}", f"{b.direction.with_turn_lane_capacity_p_prime_raw:,.1f}"),
                ("C", f"{a.direction.segment_capacity_c:,.0f}", f"{b.direction.segment_capacity_c:,.0f}"),
                ("적용 기준", a.factor_mode, b.factor_mode),
            ]
            for row, values in enumerate(rows):
                for column, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                        if column == 0
                        else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                    self.detail_table.setItem(row, column, item)
                self.detail_table.setRowHeight(row, 22)

    def copy_current(self) -> None:
        pair = self.current_pair()
        if pair:
            QApplication.clipboard().setImage(render_pair_chart(pair, 839))
            QMessageBox.information(self, APP_NAME, "복사했습니다.")

    def save_current(self, detailed: bool) -> None:
        pair = self.current_pair()
        if not pair:
            return
        suffix = "상세" if detailed else "보고서용_71mm"
        path, _ = QFileDialog.getSaveFileName(self, "그래프 저장", f"{pair.name}_{suffix}.png", "PNG 이미지 (*.png)")
        if path:
            save_pair_chart(pair, path, detailed)
            QMessageBox.information(self, APP_NAME, "저장했습니다.")

    def save_all(self) -> None:
        if not self.result:
            return
        folder = QFileDialog.getExistingDirectory(self, "모든 그래프를 저장할 폴더")
        if folder:
            for pair in self.result.pairs:
                save_pair_chart(pair, Path(folder) / f"{pair.name}_보고서용_71mm.png")
            QMessageBox.information(self, APP_NAME, "저장했습니다.")

    def copy_result_text(self) -> None:
        if not self.result:
            return
        lines = [
            f"판정: 영역 {self.result.area.value}",
            f"가장 불리한 접근로 쌍: {self.result.critical_pair.name}",
            f"교차로 전체 유입교통량: {self.result.total_traffic:,} 대/시",
        ]
        for pair in self.result.pairs:
            lines.append(f"{pair.name}: 영역 {pair.classification.area.value}")
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(self, APP_NAME, "복사했습니다.")


class AppendixTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QHBoxLayout(self)
        nav = QListWidget()
        install_auto_scrollbar(nav)
        nav.addItems([
            "적용 근거", "지침 원문 235", "지침 원문 236", "지침 원문 237", "지침 원문 238",
            "편람 식 8-26", "편람 식 8-39",
        ])
        root.addWidget(nav, 1)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 4)
        text = QTextBrowser()
        text.setHtml(
            "<h1>지침·공식</h1>"
            "<h2>지침 원문</h2>"
            "<p><b>판정식과 정의</b> — 「교차로 설계 지침(국토교통부, 2025.06)」 PDF 244~247쪽, 인쇄면 235~238쪽.</p>"
            "<p>A 경계: x/P₂ + y/P₁ = 1, 단 x ≤ C₂, y ≤ C₁</p>"
            "<p>B 경계: x/P′₂ + y/P′₁ = 1, 단 x ≤ C₂, y ≤ C₁</p>"
            "<p>판정에는 표시용 백 단위 반올림값이 아니라 계산 원시값을 사용합니다.</p>"
            "<h2>프로그램 계산 설명</h2>"
            "<p>C = 1,800 × 편도 본선 차로수</p>"
            "<p>P = C × 통합 회전 보정계수 × 중차량 보정계수 × 이용계수</p>"
            "<p>통합 회전 보정계수 f = 1 / [1 + PL(EL − 1) + PR(ER − 1)] — 도로용량편람(2013), 통합차로군 식</p>"
            "<p>중차량 보정계수 fHV = 1 / [1 + PHV(EHV − 1)] — 도로용량편람(2013), 식 8-39</p>"
            "<p>P′ 기본값 = (C + 600) × 0.9 + 2 × 3,600 / 36이며 상세 보정 설정에서 변경할 수 있습니다.</p>"
            "<p><b>주의:</b> 2025 지침의 A~D 판정과 2013 편람의 자동 계수 산정은 출처가 서로 다릅니다. 상세 차로군 분석을 대신하지 않습니다.</p>"
            "<h2>기본 적용값</h2>"
            "<p>EL=2.0, ER=1.5, EHV=1.8 · 유효녹색 36초 · 좌회전 2대/주기 · 우회전 부가용량 600대/시·접근로 · 이용계수 0.9</p>"
            "<p>별도 용량분석에서 산정한 계수가 있으면 접근로별 통합 회전계수와 중차량계수를 직접 입력할 수 있습니다.</p>"
        )
        self.stack.addWidget(text)
        for page in (244, 245, 246, 247):
            viewer = QScrollArea()
            install_auto_scrollbar(viewer)
            viewer.setWidgetResizable(True)
            label = QLabel()
            image_path = resource_path(f"guideline-page-{page}.png")
            if image_path.exists():
                label.setPixmap(QPixmap(str(image_path)))
            else:
                label.setText(f"원문 이미지 파일을 찾을 수 없습니다: PDF {page}쪽")
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            viewer.setWidget(label)
            self.stack.addWidget(viewer)
        for filename, printed_page in (("khcm-page-241.png", 241), ("khcm-page-249.png", 249)):
            viewer = QScrollArea()
            install_auto_scrollbar(viewer)
            viewer.setWidgetResizable(True)
            label = QLabel()
            image_path = resource_path(filename)
            if image_path.exists():
                label.setPixmap(QPixmap(str(image_path)))
            else:
                label.setText(f"도로용량편람 원문 이미지 파일을 찾을 수 없습니다: {printed_page}쪽")
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            viewer.setWidget(label)
            self.stack.addWidget(viewer)
        nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        nav.setCurrentRow(0)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project_path: Path | None = None
        self.last_result: IntersectionResult | None = None
        self.is_dirty = False
        self._suppress_dirty = False
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        icon = resource_path("interchange.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1280, 860)
        self.setMinimumSize(1050, 750)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(0, 0, 0, 0)
        self.step_label = QLabel()
        self.step_label.setObjectName("stepper")
        review_layout.addWidget(self.step_label)
        self.pages = QStackedWidget()
        self.topology = TopologyPage()
        self.input = InputPage()
        self.confirm = ConfirmPage()
        self.results = ResultPage()
        for page in (self.topology, self.input, self.confirm, self.results):
            self.pages.addWidget(page)
        review_layout.addWidget(self.pages, 1)
        nav = QHBoxLayout()
        nav.setContentsMargins(18, 4, 18, 8)
        self.back = QPushButton("이전")
        self.next = QPushButton("다음")
        self.next.setObjectName("primary")
        nav.addWidget(self.back)
        nav.addStretch()
        nav.addWidget(self.next)
        review_layout.addLayout(nav)
        self.tabs.addTab(review, "검토")
        self.tabs.addTab(AppendixTab(), "지침·공식")
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.go_next)
        self.pages.currentChanged.connect(self._page_changed)
        self.topology.changed.connect(self._update_nav)
        self.input.changed.connect(self._update_nav)
        self.topology.changed.connect(self._mark_dirty)
        self.input.changed.connect(self._mark_dirty)
        self._create_menu()
        self.updater = UpdateController(APP_VERSION, self)
        self.statusBar().showMessage(f"{APP_NAME} v{APP_VERSION}   ·   {APP_AUTHOR}")
        self._page_changed(0)
        if getattr(sys, "frozen", False) and os.environ.get("KGSS_DISABLE_UPDATE_CHECK") != "1":
            QTimer.singleShot(2_500, self.updater.check)

    def _create_menu(self) -> None:
        project = self.menuBar().addMenu("프로젝트")
        actions = [
            ("새 프로젝트", self.new_project, "Ctrl+N"),
            ("열기", self.open_project, "Ctrl+O"),
            ("저장", self.save_project, "Ctrl+S"),
            ("다른 이름으로 저장", self.save_as, "Ctrl+Shift+S"),
        ]
        for text, slot, shortcut in actions:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            project.addAction(action)
        help_menu = self.menuBar().addMenu("도움말")
        guide = QAction("지침·공식", self)
        guide.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        about = QAction("프로그램 정보", self)
        about.triggered.connect(self.show_about)
        update = QAction("업데이트 확인", self)
        update.triggered.connect(lambda: self.updater.check(manual=True))
        help_menu.addActions([guide, update, about])

    def _page_changed(self, index: int) -> None:
        names = ["교차로 형태", "교통량 입력", "입력 확인", "검토 결과"]
        self.step_label.setText("    ".join(f"{'●' if i == index else '○'} {name}" for i, name in enumerate(names)))
        self.back.setVisible(index > 0)
        self.next.setText("검토 실행" if index == 2 else ("처음으로" if index == 3 else "다음"))
        self._update_nav()

    def _update_nav(self) -> None:
        index = self.pages.currentIndex()
        valid = self.topology.is_valid() if index == 0 else self.input.is_valid() if index == 1 else True
        self.next.setEnabled(valid)

    def _mark_dirty(self) -> None:
        if self._suppress_dirty:
            return
        self.is_dirty = True
        self.last_result = None

    def go_back(self) -> None:
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))

    def go_next(self) -> None:
        index = self.pages.currentIndex()
        if index == 0:
            selected = self.topology.selected_codes()
            if list(self.input.cards) != selected:
                self.input.set_codes(selected)
            self.pages.setCurrentIndex(1)
        elif index == 1:
            self.confirm.set_values(
                self.topology.count,
                self.input.values(),
                self.input.assumptions(),
                self.input.signal_assumptions(),
            )
            self.pages.setCurrentIndex(2)
        elif index == 2:
            try:
                self.last_result = analyze_intersection(
                    self.input.values(),
                    self.input.assumptions(),
                    self.input.signal_assumptions(),
                )
                self.results.set_result(self.last_result)
                self.is_dirty = True
                self.pages.setCurrentIndex(3)
            except ValueError as error:
                QMessageBox.warning(self, APP_NAME, str(error))
        else:
            self._return_to_start()

    def _return_to_start(self) -> None:
        if not self.is_dirty:
            self.new_project()
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(APP_NAME)
        box.setText("현재 검토 내용을 저장하시겠습니까?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        box.button(QMessageBox.StandardButton.Save).setText("저장")
        box.button(QMessageBox.StandardButton.Discard).setText("저장 안 함")
        box.button(QMessageBox.StandardButton.Cancel).setText("취소")
        choice = box.exec()
        if choice == QMessageBox.StandardButton.Save:
            if self.save_project():
                self.new_project()
        elif choice == QMessageBox.StandardButton.Discard:
            self.new_project()

    def project_data(self) -> dict:
        result_data = None
        if self.last_result is not None:
            result_data = {
                "area": self.last_result.area.value,
                "total_traffic": self.last_result.total_traffic,
                "critical_pair": self.last_result.critical_pair.name,
                "pairs": [
                    {"name": pair.name, "area": pair.classification.area.value}
                    for pair in self.last_result.pairs
                ],
            }
        return {
            "schema": 2,
            "app_version": APP_VERSION,
            "intersection_count": self.topology.count,
            "active_codes": self.topology.selected_codes(),
            "same_heavy": self.input.same_heavy.isChecked(),
            "global_heavy": self.input.global_heavy.value(),
            "approaches": [vars(item) for item in self.input.values()],
            "calculation_settings": self.input.settings_data(),
            "result": result_data,
        }

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_as()
        self.project_path.write_text(json.dumps(self.project_data(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.is_dirty = False
        self.statusBar().showMessage(f"저장했습니다.   ·   {APP_AUTHOR}", 5000)
        return True

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "프로젝트 저장", "새_입체화검토.igr3", PROJECT_FILTER)
        if path:
            if not path.lower().endswith(".igr3"):
                path += ".igr3"
            self.project_path = Path(path)
            return self.save_project()
        return False

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", "", PROJECT_FILTER)
        if not path:
            return
        try:
            self._suppress_dirty = True
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            active = list(data["active_codes"])
            self.topology.set_codes(active)
            self.input.set_codes(self.topology.selected_codes())
            settings = data.get("calculation_settings")
            if settings is None and "assumptions" in data:
                old = data["assumptions"]
                settings = {
                    "left_equivalent": old.get("left_equivalent", 2.0),
                    "right_equivalent": old.get("right_equivalent", 1.5),
                    "heavy_equivalent": old.get("heavy_equivalent", 1.8),
                    "effective_green": old.get("effective_green_seconds", 36.0),
                    "left_per_cycle": old.get("left_turn_vehicles_per_cycle", 2.0),
                    "utilization": old.get("utilization_factor", 0.9),
                    "right_addition": 600.0,
                    "mode": "auto",
                }
            self.input.apply_settings_data(settings)
            self.input.same_heavy.setChecked(bool(data.get("same_heavy", True)))
            self.input.global_heavy.setValue(float(data.get("global_heavy", 20)))
            for item in data.get("approaches", []):
                if item["code"] in self.input.cards:
                    self.input.cards[item["code"]].set_value(item)
            self.project_path = Path(path)
            if data.get("result") and self.input.is_valid():
                self.last_result = analyze_intersection(
                    self.input.values(),
                    self.input.assumptions(),
                    self.input.signal_assumptions(),
                )
                self.results.set_result(self.last_result)
                self.pages.setCurrentIndex(3)
            else:
                self.pages.setCurrentIndex(1)
            self.is_dirty = False
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.critical(self, APP_NAME, f"프로젝트 파일을 열 수 없습니다.\n{error}")
        finally:
            self._suppress_dirty = False

    def new_project(self) -> None:
        self._suppress_dirty = True
        self.project_path = None
        self.last_result = None
        self.input.reset_settings()
        self.topology.select_count(4)
        self.input.set_codes(self.topology.selected_codes(), preserve=False)
        self.pages.setCurrentIndex(0)
        self.is_dirty = False
        self._suppress_dirty = False

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "프로그램 정보",
            f"<h2>{APP_NAME}</h2><p>v{APP_VERSION}</p><p>{APP_AUTHOR}</p>"
            "<p><b>이메일</b>: yuhyun1245@gmail.com</p>"
            "<p>국토교통부 「교차로 설계지침(2025)」과 「도로용량편람(2013)」을 참고하여 제작하였습니다.</p>"
            "<p>본 결과는 기본계획 단계의 개략검토이며 상세 교통분석을 대신하지 않습니다.</p>",
        )


STYLE = """
* { font-family: 'Noto Sans KR'; font-size: 10pt; color: #253044; }
QMainWindow, QWidget { background: #F5F7FA; }
QLabel { background: transparent; }
QMenuBar, QMenu, QStatusBar { background: white; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: white; padding: 9px 20px; color: #657087; }
QTabBar::tab:selected { color: #1769D2; border-bottom: 3px solid #2375E8; font-weight: 700; }
QFrame#card, QGroupBox { background: white; border: 1px solid #E0E6EE; border-radius: 12px; padding: 5px; }
QLabel#pageTitle { font-size: 18pt; font-weight: 800; color: #172033; }
QLabel#approachCode { font-size: 14pt; font-weight: 800; color: #1769D2; }
QLabel#panelTitle { font-size: 12pt; font-weight: 800; color: #172033; padding: 2px; }
QLabel#sectionTitle { font-weight: 800; color: #172033; padding: 0px; }
QLabel#inputHeader { color: #526079; font-size: 9pt; font-weight: 800; }
QLabel#trafficSummary { background: #EAF2FF; color: #1769D2; border-radius: 10px; padding: 9px; font-size: 13pt; font-weight: 900; }
QLabel#grandTotal { font-size: 14pt; font-weight: 800; color: #172033; }
QLabel#total { font-weight: 700; color: #1769D2; }
QLabel#warning { background: #FFF8E6; color: #8A5A00; padding: 7px; border-radius: 8px; }
QLabel#hint { padding: 6px; color: #1769D2; font-weight: 700; }
QLabel#hint[invalid='true'] { color: #C9363E; background: #FFF0F1; }
QLabel#stepper { background: white; padding: 10px 20px; color: #657087; font-weight: 700; border-bottom: 1px solid #E7EBF0; }
QLabel#resultArea { font-size: 22pt; font-weight: 900; }
QLabel#criticalPair { color: #1769D2; font-weight: 800; padding: 4px; }
QLabel#sideTitle { font-size: 11pt; font-weight: 800; color: #172033; }
QLabel#pairDetail { font-size: 9pt; font-weight: 600; color: #354052; }
QLabel#confirmOverview { font-size: 13pt; font-weight: 800; color: #172033; padding: 4px; }
QLabel#unit { color: #748095; font-size: 9pt; }
QFrame#resultHero { padding: 5px; }
QFrame#approachRow { background: #FFFFFF; border-top: 1px solid #E8EDF4; }
QFrame#approachRow[alternate="true"] { background: #F8FAFD; }
QPushButton { background: white; border: 1px solid #DDE3EC; border-radius: 9px; padding: 7px 12px; font-weight: 700; }
QPushButton:hover { background: #F0F5FF; border-color: #8CB9F5; }
QPushButton:checked, QPushButton#primary { background: #2375E8; color: white; border-color: #2375E8; }
QPushButton:disabled { background: #E9EDF2; color: #A4ACB8; border-color: #E9EDF2; }
QPushButton#stepButton { padding: 0; min-width: 28px; max-width: 28px; font-size: 14pt; font-weight: 900; }
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit { background: #FFFFFF; border: 1px solid #CFD7E3; border-radius: 7px; padding: 5px; }
QLineEdit#trafficEditor { min-width: 44px; }
QListWidget, QTextBrowser, QScrollArea { background: white; border: 1px solid #E1E6EE; border-radius: 12px; padding: 6px; }
QListWidget::item { padding: 11px; border-radius: 8px; }
QListWidget::item:selected { background: #E9F2FF; color: #1769D2; }
QTableWidget { background: white; alternate-background-color: #F8FAFD; border: 1px solid #D8E0EA; gridline-color: #D8E0EA; border-radius: 9px; }
QHeaderView::section { background: #E9EEF5; color: #253044; border: 0; border-right: 1px solid #CED7E2; border-bottom: 1px solid #C7D1DE; padding: 8px; font-size: 11pt; font-weight: 900; }
QTableWidget::item { border-bottom: 1px solid #E1E6ED; padding: 6px; font-weight: 600; }
QTableWidget::item:selected { background: #DDEBFF; color: #1769D2; }
QScrollBar#autoFadeScrollBar:vertical { background: transparent; width: 10px; margin: 3px 2px; }
QScrollBar#autoFadeScrollBar::handle:vertical { background: #9AA7B8; min-height: 34px; border-radius: 3px; }
QScrollBar#autoFadeScrollBar::handle:vertical:hover { background: #6F7E92; }
QScrollBar#autoFadeScrollBar::add-line:vertical, QScrollBar#autoFadeScrollBar::sub-line:vertical { height: 0; border: 0; }
QScrollBar#autoFadeScrollBar::add-page:vertical, QScrollBar#autoFadeScrollBar::sub-page:vertical { background: transparent; }
"""


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    font_path = resource_path("NotoSansKR.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Noto Sans KR", 10))
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("NYH")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    icon = resource_path("interchange.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    return app.exec()
