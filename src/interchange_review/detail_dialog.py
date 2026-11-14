"""Sectioned, scroll-safe detail editor. No edits reach the project until Apply."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QScrollArea, QStackedWidget, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

# Imported after the reusable widgets and original editor have been defined.
from .app import (
    _CommonSettingsDialog as BaseSettingsDialog, MotionButton,
    SettingsComboBox, card, install_auto_scrollbar,
)
from .detail import (
    LANE_TYPES, MOVEMENTS, LaneInput, RoadConditions, calculate_lane,
    road_defaults, validate_lane_totals,
)
from .engine import SignalAssumptions
from .screening import APPROACH_ORDER, CoefficientAssumptions, calculate_approach


def note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def combo(items, value=None):
    field = SettingsComboBox()
    for label, key in items:
        field.addItem(label, key)
    if value is not None:
        field.setCurrentIndex(max(0, field.findData(value)))
    return field


def scroll_content(content):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(content)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    install_auto_scrollbar(area)
    return area


def form_layout(widget=None):
    form = QFormLayout(widget)
    form.setContentsMargins(12, 10, 12, 10)
    form.setHorizontalSpacing(20)
    form.setVerticalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    return form


spin = BaseSettingsDialog._factor_spin


class RoadEditor(QWidget):
    def __init__(self, data: dict):
        super().__init__()
        self.form = form_layout(self)
        self.form.addRow(note("입체화 개략검토에 적용하는 대표 조건입니다. 차로별 신호 용량은 다음 구역에서 별도로 분석합니다."))
        self.width = spin(2, 6, data["lane_width_m"], 2)
        self.grade = spin(-20, 20, data["grade_percent"], 2)
        self.method = combo([("대향 차로수·차로순서", "opposing"), ("곡선반경", "radius")], data["left_geometry"])
        self.radius = spin(1, 500, data["radius_m"], 1)
        self.opposing = spin(1, 12, data["opposing_lanes"], 0)
        self.order = spin(1, 12, data["lane_order"], 0)
        self.angle = spin(1, 179, data["left_angle"], 1)
        self.right = combo([("녹색신호 우회전", "green"), ("적색신호 우회전", "red"),
                            ("녹색·적색 모두", "mixed"), ("우회전신호 우회전", "right_signal")], data["right_turn_mode"])
        self.red = spin(-1, 100, -1 if data["red_right_percent"] is None else data["red_right_percent"], 1)
        self.red.setSpecialValueText("미입력")
        self.result = note("")
        for label, field in (("대표 차로폭 (m)", self.width), ("접근경사 (%, 오르막 +)", self.grade),
                             ("보호좌회전 산정 기준", self.method), ("곡선반경 (m)", self.radius),
                             ("대향 차로수", self.opposing), ("대표 차로순서 (좌측부터)", self.order),
                             ("좌회전 교차각 (°)", self.angle), ("우회전 통행방식", self.right),
                             ("적색 우회전 차량 비율 (%)", self.red)):
            self.form.addRow(label, field)
            signal = field.currentIndexChanged if isinstance(field, SettingsComboBox) else field.valueChanged
            signal.connect(self.refresh)
        self.form.addRow(note("적색 비율은 실제 통과 차량 기준입니다. 신호시간 비율을 대신 넣지 않습니다.\n"
                              "비보호·겸용좌회전의 입체화 보정은 별도 분석에서 산정한 계수를 사용하세요."))
        self.form.addRow("계산된 계수", self.result)
        reset = MotionButton("기본값")
        reset.setAutoDefault(False)
        reset.clicked.connect(self.reset_values)
        self.form.addRow(reset)
        self.refresh()

    def reset_values(self):
        self.width.setValue(3)
        self.grade.setValue(0)
        self.method.setCurrentIndex(0)
        self.radius.setValue(16)
        self.opposing.setValue(2)
        self.order.setValue(1)
        self.angle.setValue(90)
        self.right.setCurrentIndex(0)
        self.red.setValue(-1)

    def value(self):
        return RoadConditions(**self.data())

    def data(self):
        return dict(lane_width_m=self.width.value(), grade_percent=self.grade.value(),
                    left_geometry=self.method.currentData(), radius_m=self.radius.value(),
                    opposing_lanes=int(self.opposing.value()), lane_order=int(self.order.value()),
                    left_angle=self.angle.value(), right_turn_mode=self.right.currentData(),
                    red_right_percent=None if self.red.value() < 0 else self.red.value())

    def refresh(self, *_):
        radius = self.method.currentData() == "radius"
        uses_geometry = self.angle.value() < 120
        self.form.setRowVisible(self.radius, radius and uses_geometry)
        self.form.setRowVisible(self.opposing, not radius and uses_geometry)
        self.form.setRowVisible(self.order, not radius and uses_geometry)
        self.form.setRowVisible(self.red, self.right.currentData() == "mixed")
        try:
            value = self.value()
            self.result.setText(f"좌회전 E = {value.left_equivalent:.2f}   ·   우회전 E = {value.right_equivalent:.2f}   ·   EHV = 1.80\n"
                                "표 8-4·8-13·8-14 / 교차각 120° 이상은 좌회전 E = 1.00")
        except ValueError as error:
            self.result.setText(str(error))


class LaneEditor(QWidget):
    def __init__(self, data: dict, order: int):
        super().__init__()
        self.saved = data
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 8, 6, 8)
        head = QHBoxLayout()
        head.addWidget(QLabel(f"{order}차로"))
        self.kind = combo([(k, k) for k in LANE_TYPES], data.get("kind", "직진"))
        head.addWidget(self.kind, 1)
        head.addWidget(QLabel("폭 (m)"))
        self.width = spin(2, 6, data.get("width_m", 3), 2)
        self.width.setMaximumWidth(85)
        head.addWidget(self.width)
        self.radius = spin(0, 500, data.get("radius_m") or 0, 1)
        self.radius.setSpecialValueText("도로 조건 사용")
        self.radius.setToolTip("이 차로의 좌회전 곡선반경(m). 0이면 도로·회전 조건을 사용합니다.")
        head.addWidget(self.radius, 1)
        box.addLayout(head)
        grid = QGridLayout()
        self.flows, self.heavy, self.labels = {}, {}, {}
        for col, (key, label) in enumerate(zip(MOVEMENTS, ("유턴", "좌회전", "직진", "우회전")), 1):
            self.labels[key] = QLabel(label)
            grid.addWidget(self.labels[key], 0, col)
            self.flows[key] = spin(0, 99999, data.get(key, 0), 0)
            self.heavy[key] = spin(0, 100, data.get("heavy_" + key, 20), 1)
            grid.addWidget(self.flows[key], 1, col)
            grid.addWidget(self.heavy[key], 2, col)
        grid.addWidget(QLabel("교통량 (대/시)"), 1, 0)
        grid.addWidget(QLabel("중차량 (%)"), 2, 0)
        box.addLayout(grid)
        self.kind.currentIndexChanged.connect(self.update_allowed)
        self.update_allowed()

    def update_allowed(self, *_):
        for key in MOVEMENTS:
            allowed = key in LANE_TYPES[self.kind.currentData()]
            # Keep a previous number visible to let the user move it deliberately.
            self.flows[key].setEnabled(allowed or self.flows[key].value() > 0)
            self.heavy[key].setEnabled(allowed)
            if key == "uturn":
                for widget in (self.labels[key], self.flows[key], self.heavy[key]):
                    widget.setVisible(allowed or self.flows[key].value() > 0)
        self.radius.setEnabled("left" in LANE_TYPES[self.kind.currentData()])

    def data(self):
        return {**self.saved, "kind": self.kind.currentData(), "width_m": self.width.value(),
                "radius_m": self.radius.value() or None,
                **{m: self.flows[m].value() for m in MOVEMENTS},
                **{"heavy_" + m: self.heavy[m].value() for m in MOVEMENTS}}


class LanePanel(QWidget):
    def __init__(self, data, road, traffic):
        super().__init__()
        self.traffic = traffic
        self.road = road
        self.data_saved = data
        self.rows = []
        root = QVBoxLayout(self)
        self.enabled = QCheckBox("차로 용량도 검토")
        self.enabled.setChecked(data.get("enabled", False))
        root.addWidget(self.enabled)
        root.addWidget(note("정지선 기준 차로별 실측·배분 교통량을 입력합니다. 본선 차로수와 다를 수 있습니다.\n"
                            "지원 범위: 동일 진입신호를 쓰는 차로, 보호좌회전·녹색우회전·신호우회전·녹색유턴.\n"
                            "적색 우회전·비보호·겸용·보행 상충·도류화·짧은 부가차로는 추가 분석이 필요합니다."))
        root.addWidget(note("유턴은 이 차로 검토에만 반영하며, 기본 화면의 입체화 교통량 합계에는 포함하지 않습니다."))
        self.constraints = QCheckBox("지원 조건 확인 · 동일 진입신호, 상충·도류화·차로 길이 영향 없음")
        self.constraints.setChecked(data.get("conditions_confirmed", False))
        root.addWidget(self.constraints)
        row = QHBoxLayout()
        row.addWidget(QLabel("정지선 차로수"))
        self.count = spin(1, 12, max(1, len(data.get("lanes", []))), 0)
        self.count.setMaximumWidth(85)
        row.addWidget(self.count)
        row.addWidget(QLabel("첨두시간계수 PHF"))
        self.phf = spin(0.25, 1, data.get("phf", 1), 2)
        self.phf.setMaximumWidth(85)
        row.addWidget(self.phf)
        row.addStretch()
        self.import_traffic = MotionButton("교통량 가져오기")
        self.import_traffic.setAutoDefault(False)
        self.import_traffic.setToolTip("진행 가능한 차로가 한 개일 때만 해당 방향 교통량을 가져옵니다. 여러 차로이면 배분값을 직접 입력합니다.")
        self.import_traffic.clicked.connect(self.fill_traffic)
        row.addWidget(self.import_traffic)
        root.addLayout(row)
        self.fill_message = note("")
        self.fill_message.hide()
        root.addWidget(self.fill_message)
        self.total_label = note("")
        root.addWidget(self.total_label)
        self.container = QVBoxLayout()
        root.addLayout(self.container)
        root.addStretch()
        self.count.valueChanged.connect(self.resize_lanes)
        self.enabled.toggled.connect(self.update_enabled)
        self.resize_lanes()
        self.update_enabled()

    def update_enabled(self):
        for widget in (self.constraints, self.count, self.phf, self.import_traffic, *self.rows):
            widget.setEnabled(self.enabled.isChecked())

    def fill_traffic(self):
        if self.traffic is None:
            return
        messages = []
        for key, label in (("left", "좌회전"), ("through", "직진"), ("right", "우회전")):
            eligible = [row for row in self.active_rows() if key in LANE_TYPES[row.kind.currentData()]]
            volume = getattr(self.traffic, key)
            if len(eligible) == 1:
                eligible[0].flows[key].setValue(volume)
            elif volume:
                messages.append(f"{label}: {'차로를 지정해 주세요' if not eligible else '차로별 배분값을 입력해 주세요'}")
        self.fill_message.setText(" · ".join(messages) if messages else "기본 교통량을 가져왔습니다. 중차량 비율과 차로별 조건도 확인해 주세요.")
        self.fill_message.show()

    def resize_lanes(self, *_):
        count = int(self.count.value())
        while len(self.rows) < count:
            index = len(self.rows)
            saved = self.data_saved.get("lanes", [])
            data = saved[index] if index < len(saved) else {
                "width_m": self.road.get("lane_width_m", 3),
                **{"heavy_" + m: self.traffic.heavy_percent if self.traffic else 20 for m in MOVEMENTS},
            }
            editor = LaneEditor(data, index + 1)
            for field in editor.flows.values():
                field.valueChanged.connect(self.refresh_totals)
            self.rows.append(editor)
            self.container.addWidget(editor)
        # Hidden rows retain entries while editing, so reducing and undoing the
        # count does not silently discard data. Only active rows are serialized.
        for index, editor in enumerate(self.rows):
            editor.setVisible(index < count)
            editor.setEnabled(self.enabled.isChecked())
        self.refresh_totals()

    def active_rows(self):
        return self.rows[:int(self.count.value())]

    def refresh_totals(self, *_):
        totals = [sum(r.flows[m].value() for r in self.active_rows()) for m in ("left", "through", "right")]
        expected = [getattr(self.traffic, m) if self.traffic else 0 for m in ("left", "through", "right")]
        self.total_label.setText("차로 합계 / 기본 입력   " + "   ·   ".join(
            f"{label} {a:,.0f}/{b:,.0f}" for label, a, b in zip(("좌", "직", "우"), totals, expected)))

    def value(self):
        return {"enabled": self.enabled.isChecked(), "conditions_confirmed": self.constraints.isChecked(),
                "phf": self.phf.value(), "lanes": [row.data() for row in self.active_rows()]}


class DetailSettingsDialog(BaseSettingsDialog):
    def __init__(self, codes, settings, direct, parent=None, traffic=None):
        self.ready = False
        self.original = deepcopy(settings)
        self.codes = [code for code in APPROACH_ORDER if code in codes]
        self.traffic = {item.code: item for item in (traffic or [])}
        super().__init__(self.codes, settings, direct, parent)
        root = self.layout()
        # Reuse the existing input controls and all legacy values, but give each
        # input a stable section with its own bounded scroll region.
        pprime = self.pprime_title.parentWidget()
        from PySide6.QtWidgets import QDialogButtonBox
        buttons = self.findChild(QDialogButtonBox)
        while root.count():
            item = root.takeAt(0)
            if item.widget():
                item.widget().hide()
            if item.layout():
                for i in range(item.layout().count()):
                    child = item.layout().itemAt(i).widget()
                    if child:
                        child.hide()
        title = QLabel("상세 설정")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        root.addWidget(note("4지 도표의 보정계수와 차로 용량 계산에 쓰는 값을 설정합니다."))
        nav = QHBoxLayout()
        nav.addWidget(QLabel("접근로"))
        self.approach = combo([(code, code) for code in self.codes])
        self.approach.setMaximumWidth(125)
        nav.addWidget(self.approach)
        nav.addStretch()
        root.addLayout(nav)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        mode_page = QWidget()
        mode_box = QVBoxLayout(mode_page)
        mode_box.addWidget(note("1  입체화 판정에 적용할 보정 방식"))
        self.mode.setParent(mode_page)
        self.mode.setItemText(self.mode.findData("auto"), "입력 조건으로 자동 계산")
        self.mode.setItemText(self.mode.findData("direct"), "외부 분석 계수 입력")
        mode_box.addWidget(self.mode)
        self.mode.show()
        self.scope = combo([("모든 접근로 공통", "common"), ("접근로별 설정", "approach")],
                           settings.get("detail_scope", "common"))
        mode_box.addWidget(self.scope)
        mode_box.addWidget(note("자동 계산: 폭·경사·회전 조건과 기본 화면의 교통량·중차량 비율을 사용합니다.\n"
                               "외부 분석: 이미 산정한 도로·이동류 통합계수와 중차량계수를 적용합니다.\n"
                               "차로 용량은 별도 참고 결과이며 입체화 판정의 P·P′를 대체하지 않습니다."))
        mode_box.addWidget(self.direct_panel)
        self.direct_title.setText("외부 분석 결과 · 접근로별 보정계수")
        self.direct_table.setHorizontalHeaderLabels(["접근로", "도로·이동류 통합계수", "중차량계수"])
        self.direct_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.direct_table.setMinimumHeight(150)
        self.direct_source = QLineEdit(settings.get("direct_source", "기존 프로젝트의 직접 입력 계수" if direct and settings.get("mode") == "direct" else ""))
        self.direct_source.setPlaceholderText("분석 보고서·계산서 등 계수 출처")
        mode_box.addWidget(self.direct_source)
        # Newly selected external mode must not silently apply arbitrary 0.85s.
        for code, (turn, heavy) in self.direct_spins.items():
            for field in (turn, heavy):
                field.setMinimum(0)
                field.setSpecialValueText("미입력")
                if code not in direct:
                    field.setValue(0)
        self.reset_direct.setText("자동값")
        mode_box.addStretch()
        self.tabs.addTab(scroll_content(mode_page), "분석 방식")

        road_page = QWidget()
        road_box = QVBoxLayout(road_page)
        road_box.addWidget(self.auto_panel)
        self.auto_panel.show()
        form = self.auto_panel.layout()
        for field in (self.left_equivalent, self.right_equivalent, self.heavy_equivalent):
            form.setRowVisible(field, False)
        form.setRowVisible(self.left_mode, False)
        self.common_factors = note("")
        form.addRow("계산된 계수", self.common_factors)
        form.addRow(note("자동 산정: 좌회전 E 1.08(대향 2차로·1차로), EHV 1.80.\n"
                         "곡선반경·교차각·서로 다른 접근로 조건은 ‘접근로별 설정’에서 입력합니다."))
        self.roads = {}
        self.road_stack = QStackedWidget()
        road_box.addWidget(self.road_stack)
        for code in self.codes:
            data = {**road_defaults(settings), **settings.get("approach_conditions", {}).get(code, {})}
            editor = RoadEditor(data)
            self.roads[code] = editor
            self.road_stack.addWidget(editor)
        self.road_unavailable = note("외부 분석 계수 또는 기존 자동식을 사용합니다. 도로 조건은 현재 입체화 판정에 적용하지 않습니다.")
        road_box.addWidget(self.road_unavailable)
        road_box.addStretch()
        self.tabs.addTab(scroll_content(road_page), "도로·회전")

        self.lanes = {}
        self.lane_stack = QStackedWidget()
        for code in self.codes:
            data = settings.get("lane_analysis", {}).get(code, {})
            panel = LanePanel(data, {**road_defaults(settings), **settings.get("approach_conditions", {}).get(code, {})}, self.traffic.get(code))
            self.lanes[code] = panel
            self.lane_stack.addWidget(scroll_content(panel))
        self.tabs.addTab(self.lane_stack, "차로·교통량")

        signal_page = QWidget()
        signal_box = QVBoxLayout(signal_page)
        signal_box.addWidget(note("차로 신호 용량용 · 실제 신호 운영"))
        self.operating_cycle = spin(0, 600, settings.get("operating_cycle") or 0, 1)
        self.operating_cycle.setSpecialValueText("미입력")
        signal_form = form_layout()
        signal_form.addRow("실제 신호주기 (초)", self.operating_cycle)
        signal_box.addLayout(signal_form)
        signal_box.addWidget(note("차로의 모든 진행방향이 함께 진입하는 신호시간 G를 입력합니다.\n"
                                 "g = G - 출발손실 + 진입신호연장. 황색시간 전체를 녹색에 더하지 않습니다.\n"
                                 "직좌는 좌·직 동시 진입 조건에서만 이 분석을 사용할 수 있습니다."))
        self.signal_container = QWidget()
        self.signal_form = form_layout(self.signal_container)
        signal_box.addWidget(self.signal_container)
        self.signal_fields = {}
        signal_box.addWidget(note("입체화 개략검토용 · 회전차로 설치 가정 (P′)"))
        self.pprime_toggle = QCheckBox("P′ 가정 수정")
        signal_box.addWidget(self.pprime_toggle)
        signal_box.addWidget(pprime)
        self.pprime_toggle.toggled.connect(pprime.setVisible)
        pprime.hide()
        self.effective_green.setMaximum(599)
        self.effective_green.setValue(settings.get("effective_green", 36))
        self.pprime_title.setText("지침 예제의 가정 · 실제 신호 운영 입력과 별도")
        self.right_addition.setToolTip("지침 예제의 녹색 1시간 환산 우회전 부가용량. 실제 시간당 통과량이 아닙니다.")
        signal_box.addStretch()
        self.tabs.addTab(scroll_content(signal_page), "신호")

        self.review = QTextBrowser()
        install_auto_scrollbar(self.review)
        self.review.setOpenExternalLinks(False)
        self.tabs.addTab(self.review, "확인·근거")
        self.error_label = note("")
        self.error_label.setObjectName("warning")
        self.error_label.hide()
        root.addWidget(self.error_label)
        root.addWidget(buttons)
        buttons.show()
        self.scope.currentIndexChanged.connect(self._update_mode)
        self.approach.currentIndexChanged.connect(self._select_approach)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.ready = True
        self.setMinimumSize(680, 560)
        available = self.screen().availableGeometry()
        self.resize(min(860, available.width() - 40), min(740, available.height() - 60))
        self._update_mode()
        self._movement_mode_changed()
        self._select_approach()

    def _update_mode(self, *_):
        if not self.ready:
            return
        auto = self.mode.currentData() == "auto"
        separate = self.scope.currentData() == "approach"
        self.auto_panel.setVisible(not separate)
        self.road_stack.setVisible(separate)
        self.road_unavailable.setVisible(not auto)
        self.road_unavailable.setText("이 도로 조건은 차로 용량에만 적용합니다. 입체화 판정은 선택한 외부 계수 또는 기존 자동식을 유지합니다.")
        self.direct_panel.setVisible(self.mode.currentData() == "direct")
        self.direct_source.setVisible(self.mode.currentData() == "direct")
        for field in (self.left_equivalent, self.right_equivalent, self.heavy_equivalent):
            field.setReadOnly(True)
            self.auto_panel.layout().setRowVisible(field, False)

    def _movement_mode_changed(self, *_):
        super()._movement_mode_changed()
        if self.ready:
            self.auto_panel.layout().setRowVisible(self.right_equivalent, False)
            self.common_factors.setText(
                f"좌회전 E 1.08 · 우회전 E {self.right_equivalent.value():.2f} · EHV 1.80"
                if self.right_mode.currentData() != "mixed" or self.red_right_percent.value() >= 0
                else "적색 우회전 차량 비율을 입력하면 계수를 계산합니다.")

    def _select_approach(self, *_):
        index = self.approach.currentIndex()
        self.road_stack.setCurrentIndex(index)
        self.lane_stack.setCurrentIndex(index)
        if self.tabs.currentIndex() == 3:
            self._build_signals()

    def _store_signals(self):
        for (code, index), fields in self.signal_fields.items():
            self.lanes[code].rows[index].saved.update(
                green=None if fields[0].value() < 0 else fields[0].value(),
                start_loss=fields[1].value(), extension=fields[2].value())

    def _build_signals(self):
        self._store_signals()
        while self.signal_form.rowCount():
            self.signal_form.removeRow(0)
        self.signal_fields.clear()
        code = self.approach.currentData()
        panel = self.lanes[code]
        if not panel.enabled.isChecked():
            self.signal_form.addRow(note("‘차로·교통량’에서 차로 용량 검토를 켜면 신호 입력이 나타납니다."))
            return
        for i, row in enumerate(panel.active_rows()):
            data = row.data()
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            green = spin(-1, 600, -1 if data.get("green") is None else data["green"], 1)
            green.setSpecialValueText("미입력")
            loss = spin(0, 30, data.get("start_loss", 2.3), 1)
            extension = spin(0, 30, data.get("extension", 2), 1)
            for label, field in (("G", green), ("손실", loss), ("연장", extension)):
                line.addWidget(QLabel(label))
                line.addWidget(field)
            self.signal_form.addRow(f"{i + 1}차로 · {row.kind.currentData()}", holder)
            self.signal_fields[(code, i)] = (green, loss, extension)

    def _tab_changed(self, index):
        self._store_signals()
        if index == 3:
            self._build_signals()
        if index == 4:
            self._review()

    def values(self):
        settings, direct = super().values()
        if not self.ready:
            return settings, direct
        self._store_signals()
        # Retain inactive-mode entries; changing a mode never erases prior work.
        settings.update(detail_scope=self.scope.currentData(),
                        approach_conditions={code: editor.data() for code, editor in self.roads.items()},
                        lane_analysis={code: panel.value() for code, panel in self.lanes.items()},
                        operating_cycle=self.operating_cycle.value() or None, direct_source=self.direct_source.text().strip())
        return settings, direct

    def _road_for_lane(self, code):
        if self.scope.currentData() == "approach":
            return self.roads[code].value()
        return RoadConditions(**{**road_defaults({}), "lane_width_m": self.lane_width.value(),
                                 "grade_percent": self.grade.value(), "right_turn_mode": self.right_mode.currentData(),
                                 "red_right_percent": None if self.red_right_percent.value() < 0 else self.red_right_percent.value()})

    def _errors_and_results(self):
        errors, rows = [], []
        try:
            SignalAssumptions(self.cycle.value(), self.effective_green.value(), self.left_per_cycle.value(),
                              self.right_addition.value(), self.utilization.value())
        except ValueError as error:
            errors.append((3, None, str(error)))
        mode = self.mode.currentData()
        if mode == "auto":
            targets = self.codes if self.scope.currentData() == "approach" else self.codes[:1]
            for code in targets:
                try:
                    self._road_for_lane(code)
                except ValueError as error:
                    errors.append((1, code, str(error)))
        if mode == "direct":
            for code, fields in self.direct_spins.items():
                if any(field.value() <= 0 for field in fields):
                    errors.append((0, code, "외부 분석 계수 두 값을 모두 입력해 주세요."))
            if not self.direct_source.text().strip():
                errors.append((0, None, "외부 분석 계수의 출처를 입력해 주세요."))
        for code, panel in self.lanes.items():
            if not panel.enabled.isChecked():
                continue
            if not panel.constraints.isChecked():
                errors.append((2, code, "지원 조건을 확인해 주세요. 해당하지 않으면 차로 용량 검토를 끄세요."))
                continue
            try:
                data = panel.value()
                lanes = [LaneInput(**row) for row in data["lanes"]]
                if code not in self.traffic:
                    raise ValueError("기본 교통량 입력을 불러올 수 없습니다.")
                validate_lane_totals(lanes, vars(self.traffic[code]))
                road = self._road_for_lane(code)
                shared = [lane.kind for lane in lanes if lane.kind in ("직좌", "직우", "좌직우", "유좌")]
                if len(shared) != len(set(shared)):
                    raise ValueError("같은 유형의 공용차로를 둘 이상 설치할 수 없습니다(표 8-15).")
                if any(lane.kind == "유턴" for lane in lanes) and any(lane.kind == "유좌" for lane in lanes):
                    raise ValueError("유턴 전용차로와 유좌 공용차로를 함께 배치할 수 없습니다(표 8-15).")
                for index, lane in enumerate(lanes):
                    if lane.total == 0:
                        rows.append((code, index + 1, None))
                        continue
                    try:
                        result = calculate_lane(lane, road, cycle=self.operating_cycle.value(), phf=data["phf"], order=index + 1)
                        rows.append((code, index + 1, result))
                    except ValueError as error:
                        errors.append((3, code, f"{index + 1}차로: {error}"))
            except (ValueError, TypeError) as error:
                errors.append((2, code, str(error)))
        return errors, rows

    def _review(self):
        self._store_signals()
        errors, rows = self._errors_and_results()
        html = ["<h3>입력 확인</h3>"]
        if errors:
            html += ["<p>입력을 확인해 주세요.</p><ul>"]
            html += [f"<li>{escape(code or '공통')}: {escape(message)}</li>" for _, code, message in errors]
            html.append("</ul>")
        else:
            html.append("<p>필수 입력과 교통량 합계를 확인했습니다.</p>")
        html.append("<h3>입체화 판정 · 적용 계수</h3><table width='99%' cellspacing='0' cellpadding='6' border='1'><tr><th>접근로</th><th>도로·이동류</th><th>중차량</th><th>적용 방식</th></tr>")
        for code in self.codes:
            try:
                if code not in self.traffic:
                    continue
                value = self.traffic[code]
                if self.mode.currentData() == "direct":
                    value = replace(value, direct_turn_factor=self.direct_spins[code][0].value(),
                                    direct_heavy_factor=self.direct_spins[code][1].value())
                else:
                    value = replace(value, direct_turn_factor=None, direct_heavy_factor=None)
                common, _ = super().values()
                assumptions = CoefficientAssumptions(
                    **{key: common[key] for key in ("left_equivalent", "right_equivalent", "heavy_equivalent",
                        "lane_width_m", "grade_percent", "right_turn_mode", "red_right_percent")},
                    legacy=self.mode.currentData() == "legacy",
                    approach_conditions={code: asdict(self.roads[code].value())}
                    if self.scope.currentData() == "approach" and self.mode.currentData() == "auto" else {})
                result = calculate_approach(value, assumptions)
                html.append(f"<tr><td align='center'>{code}</td><td align='right'>{result.turn_factor:.4f}</td><td align='right'>{result.heavy_factor:.4f}</td><td>{result.factor_mode}</td></tr>")
            except ValueError:
                html.append(f"<tr><td>{code}</td><td colspan='3'>입력 확인 필요</td></tr>")
        html.append("</table><h3>차로 신호 용량 · 참고 결과</h3>")
        if errors and rows:
            html.append("<p>입력 오류가 있어 일부 값만 산정되었습니다. 전체 검토 완료 결과가 아닙니다.</p>")
        html.append("<table width='99%' cellspacing='0' cellpadding='4' border='1'><tr><th>차로</th><th>v<br>(대/시)</th><th>g<br>(초)</th><th>s<br>(대/시)</th><th>c<br>(대/시)</th><th>v/c</th></tr>")
        for code, index, result in rows:
            if result is None:
                html.append(f"<tr><td>{code} {index}</td><td colspan='5'>교통량 0 · 산정 제외</td></tr>")
            else:
                html.append(f"<tr><td align='center'>{code} {index}</td><td align='right'>{result.demand:,.1f}</td><td align='right'>{result.effective_green:.1f}</td>"
                            f"<td align='right'>{result.saturation:,.1f}</td><td align='right'>{result.capacity:,.1f}</td><td align='right'>{result.saturation_ratio:.3f}</td></tr>")
                html.append(f"<tr><td colspan='6'>계수: 경사 {result.grade_factor:.4f} · 폭 {result.width_factor:.4f} · "
                            f"중차량 {result.heavy_factor:.4f}<br>이동류 {result.movement_factor:.4f} · 좌회전 E {result.left_equivalent:.2f}</td></tr>")
        html.append("</table><p>차로 용량은 입력한 차로별 교통량과 동일 진입신호 조건의 결과입니다. "
                    "차로 간 자동 배분, 복합 이동류, 지체·서비스수준 및 교차로 전체 용량 분석은 포함하지 않습니다.</p>"
                    "<h3>근거와 적용 범위</h3>"
                    "<p>도로용량편람 제8장: 식 8-2~8-4(331~332쪽), 표 8-4(332쪽), "
                    "표 8-12(353쪽), 표 8-13·8-14(354~355쪽). 쪽수는 인쇄면 기준입니다.</p>"
                    "<p>g = G - 출발손실 + 진입신호연장<br>"
                    "s = 2,200 × 경사계수 × 폭계수 × 중차량계수 × 이동류계수<br>"
                    "c = s × g / C, v = 교통량 / PHF<br>"
                    "이동류 비율은 승용차환산 교통량 기준, EHV = 1.8입니다.</p>"
                    "<p>교차로 설계 지침의 A·B·C·D 개략판정에는 차로당 1,800과 별도의 P′ 가정을 사용합니다. "
                    "신호계획 검토는 검토 단계에서 입력한 신호시간과 이동류별 포화교통류율을 사용합니다.</p>")
        self.review.setHtml("".join(html))
        return errors

    def _reset_direct_factors(self):
        if not self.ready:
            return
        for code, fields in self.direct_spins.items():
            if code not in self.traffic:
                continue
            try:
                road = self._road_for_lane(code)
                value = replace(self.traffic[code], direct_turn_factor=None, direct_heavy_factor=None)
                result = calculate_approach(value, CoefficientAssumptions(approach_conditions={code: asdict(road)}))
                fields[0].setValue(result.turn_factor)
                fields[1].setValue(result.heavy_factor)
            except ValueError:
                continue
        self.direct_source.setText("도로·회전 조건으로 계산")

    def accept(self):
        self._store_signals()
        errors = self._review()
        if errors:
            tab, code, message = errors[0]
            if code:
                self.approach.setCurrentIndex(self.approach.findData(code))
            self.tabs.setCurrentIndex(tab)
            self.error_label.setText(f"{code + ': ' if code else ''}{message}")
            self.error_label.show()
            return
        # Bypass the old common-only validation: this editor validates the
        # actually selected scope and every enabled lane analysis above.
        from PySide6.QtWidgets import QDialog
        QDialog.accept(self)
