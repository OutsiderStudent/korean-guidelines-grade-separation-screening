"""Signal plan input and cycle capacity results."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .phase_review import TURNS, check_phase_plan


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.setAlternatingRowColors(True)
    return widget


def put_row(widget, values):
    row = widget.rowCount()
    widget.insertRow(row)
    for column, value in enumerate(values):
        cell = QTableWidgetItem(str(value))
        cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        widget.setItem(row, column, cell)
    return row


def note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class SignalPlanDialog(QDialog):
    def __init__(self, approaches, saved, parent=None):
        super().__init__(parent)
        self.setWindowTitle("신호계획")
        self.resize(920, 650)
        self.approaches = approaches
        self.codes = [item.code for item in approaches]
        saved = saved if saved and saved.get("codes") == self.codes else {}
        layout = QVBoxLayout(self)
        cycle_row = QHBoxLayout()
        cycle_row.addWidget(QLabel("신호주기 (초)"))
        self.cycle = QLineEdit(str(saved.get("cycle", "")))
        self.cycle.setMaximumWidth(110)
        cycle_row.addWidget(self.cycle)
        cycle_row.addStretch()
        layout.addLayout(cycle_row)
        layout.addWidget(note("현시 순서대로 시간을 입력하세요. ‘그 외’에는 유효녹색에 포함되지 않은 시간을 입력합니다."))
        self.phases = table(["유효녹색 (초)", "그 외 (초)"])
        self.phases.verticalHeader().show()
        layout.addWidget(self.phases, 1)
        for phase in saved.get("phases", [{"green": "", "other": ""}]):
            put_row(self.phases, (phase["green"], phase["other"]))
        self._controls(layout, self.phases, lambda: put_row(self.phases, ("", "")), "현시 추가", "마지막 삭제", last_only=True)

        layout.addWidget(note("진출로는 나가는 도로 쪽을 고르세요. 같은 현시 번호를 입력한 이동류는 함께 통행합니다(예: 1,3)."))
        layout.addWidget(note("보정 포화교통류율은 녹색 1시간 기준입니다. 차로가 겹치는 이동류는 같은 차로군 번호를 입력하세요. 빈칸은 전용차로로 계산합니다."))
        self.movements = table(["유입 접근로", "이동 방향", "진출로 위치", "교통량 (대/시)", "포화교통류율 (대/녹색시)", "차로군", "통행 현시"])
        self.movements.verticalHeader().setDefaultSectionSize(39)
        self.movements.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.movements, 2)
        self._controls(layout, self.movements, lambda: self._movement({}), "이동류 추가", "삭제")
        if "movements" in saved:
            for movement in saved["movements"]:
                self._movement(movement)
        else:
            for item in approaches:
                for turn in ("left", "through", "right"):
                    if getattr(item, turn):
                        self._movement({"approach": item.code, "turn": turn, "demand": getattr(item, turn)})
        self.confirmed = QCheckBox("현시별 동시 통행, 합류·보행 상충 및 차로군 구성을 확인했습니다")
        layout.addWidget(self.confirmed)
        self.confirmed.setChecked(bool(saved.get("confirmed")))
        self.phases.itemChanged.connect(self._clear_confirmation)
        self.movements.itemChanged.connect(self._clear_confirmation)
        self.cycle.textChanged.connect(self._clear_confirmation)
        self.error = note("")
        self.error.setObjectName("warning")
        self.error.hide()
        layout.addWidget(self.error)
        footer = QHBoxLayout()
        footer.addStretch()
        run = QPushButton("검토")
        run.setObjectName("primary")
        run.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        footer.addWidget(run)
        footer.addWidget(cancel)
        layout.addLayout(footer)

    def _clear_confirmation(self, *_):
        self.confirmed.setChecked(False)

    def _controls(self, layout, widget, add, add_label, delete_label, last_only=False):
        row = QHBoxLayout()
        add_button = QPushButton(add_label)
        add_button.setAutoDefault(False)
        delete_button = QPushButton(delete_label)
        delete_button.setAutoDefault(False)

        def remove():
            index = widget.rowCount() - 1 if last_only else widget.currentRow()
            if index >= 0:
                widget.removeRow(index)
                self._clear_confirmation()

        add_button.clicked.connect(add)
        add_button.clicked.connect(self._clear_confirmation)
        delete_button.clicked.connect(remove)
        row.addWidget(add_button)
        row.addWidget(delete_button)
        row.addStretch()
        layout.addLayout(row)

    def _movement(self, movement):
        from .app import SettingsComboBox
        row = put_row(self.movements, ["", "", "", movement.get("demand", ""), movement.get("saturation", ""),
                                       movement.get("lane_group", ""), ",".join(map(str, movement.get("phases", [])))])
        for column, (key, options) in enumerate((
            ("approach", {code: code for code in self.codes}), ("turn", TURNS),
            ("exit_leg", {code: code + " 쪽" for code in self.codes}),
        )):
            combo = SettingsComboBox()
            combo.addItem("선택", "")
            for value, label in options.items():
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(movement.get(key))))
            combo.currentIndexChanged.connect(self._clear_confirmation)
            self.movements.setCellWidget(row, column, combo)

    def accept(self):
        try:
            def cell(widget, row, col):
                return widget.item(row, col).text().strip()

            data = {"codes": self.codes, "cycle": float(self.cycle.text()), "confirmed": self.confirmed.isChecked(),
                    "phases": [], "movements": []}
            for row in range(self.phases.rowCount()):
                data["phases"].append({"green": float(cell(self.phases, row, 0)), "other": float(cell(self.phases, row, 1))})
            for row in range(self.movements.rowCount()):
                item = {key: self.movements.cellWidget(row, col).currentData()
                        for col, key in enumerate(("approach", "turn", "exit_leg"))}
                item.update(demand=int(cell(self.movements, row, 3)), saturation=float(cell(self.movements, row, 4)),
                            lane_group=cell(self.movements, row, 5),
                            phases=[int(value) for value in cell(self.movements, row, 6).split(",")])
                data["movements"].append(item)
            self.review_result = check_phase_plan(self.approaches, data)
        except ValueError as error:
            message = str(error)
            if "invalid literal" in message or "could not convert" in message:
                message = "빈칸이나 숫자 형식을 확인하세요. 통행 현시가 여러 개면 쉼표로 구분하세요."
            self.error.setText(message)
            self.error.show()
            return
        self.data = data
        super().accept()


class SignalResultPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setObjectName("pageTitle")
        layout.addWidget(self.summary)
        self.description = note("")
        layout.addWidget(self.description)
        self.phase_times = note("")
        layout.addWidget(self.phase_times)
        self.table = table(["이동류", "진출로 위치", "교통량", "포화교통류율", "통행 현시", "필요 녹색 (초)",
                            "차로군 필요 녹색 (초)", "유효녹색 (초)", "부족 (초)"])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        layout.addWidget(note("부족 시간이 있는 차로군은 입력한 신호계획으로 설계 교통량을 처리하기 어렵습니다. 현시 조정이나 차로 개선안을 적용해 다시 검토할 수 있습니다."))
        copy = QPushButton("결과 복사")
        copy.clicked.connect(self.copy_result)
        layout.addWidget(copy, alignment=Qt.AlignmentFlag.AlignRight)

    def set_result(self, result):
        self.summary.setText("입력 신호계획으로 처리 가능" if result.feasible else "입력 신호계획의 녹색시간 부족")
        self.description.setText(f"신호주기 {result.cycle:g}초 · 교통량 단위 대/시 · 필요 녹색 = 주기 × 교통량 ÷ 보정 포화교통류율")
        self.phase_times.setText("현시별 유효녹색 / 그 외 (초)   " + "   ·   ".join(
            f"{i}현시 {phase.green:g} / {phase.other:g}" for i, phase in enumerate(result.phases, 1)))
        self.table.setRowCount(0)
        for item in result.movements:
            movement = item.movement
            label = f"{movement.approach} {TURNS[movement.turn]}"
            if movement.lane_group:
                label += f" ({movement.lane_group})"
            missing = max(0, item.group_required_green - item.available_green)
            put_row(self.table, (label, movement.exit_leg + " 쪽", f"{movement.demand:,}", f"{movement.saturation:,g}",
                                 ", ".join(map(str, movement.phases)), f"{item.required_green:.2f}",
                                 f"{item.group_required_green:.2f}", f"{item.available_green:.2f}", f"{missing:.2f}"))

    def copy_result(self):
        from PySide6.QtWidgets import QApplication
        lines = [self.summary.text(), self.description.text(), self.phase_times.text()]
        lines.append("\t".join(self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())))
        for row in range(self.table.rowCount()):
            lines.append("\t".join(self.table.item(row, c).text() for c in range(self.table.columnCount())))
        QApplication.clipboard().setText("\n".join(lines))
