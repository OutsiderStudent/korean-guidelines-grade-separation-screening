"""Qt로 그리는 보고서용 A·B·C·D 용량 그래프."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from .screening import PairResult


AREA_COLORS = {
    "A": QColor("#C9F2DD"),
    "B": QColor("#D7E8FF"),
    "C": QColor("#FFE5C2"),
    "D": QColor("#FFE0E3"),
}


def _font(pixel_size: float, scale: float, weight=QFont.Weight.Normal) -> QFont:
    """QImage의 300 dpi 메타데이터와 무관하게 물리 크기가 일정한 글꼴."""

    font = QFont("Noto Sans KR")
    font.setPixelSize(max(9, int(pixel_size * scale)))
    font.setWeight(weight)
    return font


def _nice_max(value: float) -> int:
    value = max(1_000.0, value * 1.15)
    step = 500 if value <= 5_000 else 1_000
    return int((value + step - 1) // step * step)


def _map(x: float, y: float, rect: QRectF, maximum: float) -> QPointF:
    return QPointF(rect.left() + x / maximum * rect.width(), rect.bottom() - y / maximum * rect.height())


def render_pair_chart(pair: PairResult, size: int = 839, detailed: bool = False) -> QImage:
    """71 mm/300 dpi(839 px) 또는 상세 정사각 그래프를 렌더링한다."""

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    image.setDotsPerMeterX(11_811)
    image.setDotsPerMeterY(11_811)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    scale = size / 839.0
    first, second = pair.first.direction, pair.second.direction
    q1, q2 = first.hourly_design_traffic_q, second.hourly_design_traffic_q
    maximum = _nice_max(max(
        q1, q2,
        first.segment_capacity_c, second.segment_capacity_c,
        first.with_turn_lane_capacity_p_prime_raw, second.with_turn_lane_capacity_p_prime_raw,
    ))
    # 확대된 Y축 글자와 눈금이 겹치지 않도록 왼쪽 여백을 확보한다.
    left = 138 * scale
    top = (112 if detailed else 96) * scale
    right = 42 * scale
    bottom = (142 if detailed else 130) * scale
    plot = QRectF(left, top, size - left - right, size - top - bottom)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(AREA_COLORS["D"])
    painter.drawRoundedRect(plot, 6 * scale, 6 * scale)
    painter.setBrush(QBrush(QColor(70, 78, 92, 28), Qt.BrushStyle.DiagCrossPattern))
    painter.drawRoundedRect(plot, 6 * scale, 6 * scale)

    # C 영역: 단로부 용량 사각형
    cpoly = QPolygonF([
        _map(0, 0, plot, maximum),
        _map(second.segment_capacity_c, 0, plot, maximum),
        _map(second.segment_capacity_c, first.segment_capacity_c, plot, maximum),
        _map(0, first.segment_capacity_c, plot, maximum),
    ])
    painter.setBrush(AREA_COLORS["C"])
    painter.drawPolygon(cpoly)
    painter.setBrush(QBrush(QColor(90, 75, 40, 28), Qt.BrushStyle.BDiagPattern))
    painter.drawPolygon(cpoly)

    # B/A 영역은 지침의 단로부 용량 상한(C 사각형) 안에서만 유효하다.
    painter.save()
    painter.setClipRect(QRectF(
        _map(0, first.segment_capacity_c, plot, maximum),
        _map(second.segment_capacity_c, 0, plot, maximum),
    ).normalized())
    # B 영역(원점-P' 절편 삼각형), 뒤에 A를 덮어 그린다.
    pprime = QPolygonF([
        _map(0, 0, plot, maximum),
        _map(second.with_turn_lane_capacity_p_prime_raw, 0, plot, maximum),
        _map(0, first.with_turn_lane_capacity_p_prime_raw, plot, maximum),
    ])
    painter.setBrush(AREA_COLORS["B"])
    painter.drawPolygon(pprime)
    painter.setBrush(QBrush(QColor(44, 84, 138, 26), Qt.BrushStyle.VerPattern))
    painter.drawPolygon(pprime)
    apoly = QPolygonF([
        _map(0, 0, plot, maximum),
        _map(second.no_turn_lane_capacity_p_raw, 0, plot, maximum),
        _map(0, first.no_turn_lane_capacity_p_raw, plot, maximum),
    ])
    painter.setBrush(AREA_COLORS["A"])
    painter.drawPolygon(apoly)
    painter.setBrush(QBrush(QColor(34, 110, 74, 25), Qt.BrushStyle.HorPattern))
    painter.drawPolygon(apoly)
    painter.restore()

    # 흑백 출력에서도 구분되는 경계와 격자
    painter.setPen(QPen(QColor("#D9E0EA"), max(1, int(1 * scale)), Qt.PenStyle.DashLine))
    for index in range(6):
        value = maximum * index / 5
        p1 = _map(value, 0, plot, maximum)
        p2 = _map(value, maximum, plot, maximum)
        painter.drawLine(p1, p2)
        p1 = _map(0, value, plot, maximum)
        p2 = _map(maximum, value, plot, maximum)
        painter.drawLine(p1, p2)

    painter.setPen(QPen(QColor("#2375E8"), max(2, int(2 * scale)), Qt.PenStyle.DashLine))
    painter.drawLine(_map(0, first.with_turn_lane_capacity_p_prime_raw, plot, maximum), _map(second.with_turn_lane_capacity_p_prime_raw, 0, plot, maximum))
    painter.setPen(QPen(QColor("#15935B"), max(2, int(2 * scale)), Qt.PenStyle.SolidLine))
    painter.drawLine(_map(0, first.no_turn_lane_capacity_p_raw, plot, maximum), _map(second.no_turn_lane_capacity_p_raw, 0, plot, maximum))
    painter.setPen(QPen(QColor("#1E2A3A"), max(2, int(2 * scale))))
    painter.drawLine(plot.bottomLeft(), plot.bottomRight())
    painter.drawLine(plot.bottomLeft(), plot.topLeft())

    # 눈금
    painter.setFont(_font(25, scale, QFont.Weight.Medium))
    for index in range(6):
        value = int(maximum * index / 5)
        xp = _map(value, 0, plot, maximum)
        yp = _map(0, value, plot, maximum)
        # Noto Sans KR의 쉼표는 글자 기준선 아래로 내려간다. 눈금 영역이 짧으면
        # 아랫부분이 잘려 마침표처럼 보이므로 충분한 높이에 수직 중앙 배치한다.
        painter.drawText(
            QRectF(xp.x() - 50 * scale, plot.bottom() + 3 * scale, 100 * scale, 38 * scale),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{value:,}",
        )
        painter.drawText(QRectF(3 * scale, yp.y() - 14 * scale, left - 17 * scale, 28 * scale), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value:,}")

    current = _map(q2, q1, plot, maximum)

    # 영역 문자
    painter.setFont(_font(43, scale, QFont.Weight.Bold))
    labels = [
        ("A", second.no_turn_lane_capacity_p_raw * .23, first.no_turn_lane_capacity_p_raw * .23),
        ("B", second.with_turn_lane_capacity_p_prime_raw * .30, first.with_turn_lane_capacity_p_prime_raw * .45),
        ("C", second.segment_capacity_c * .74, first.segment_capacity_c * .66),
        ("D", maximum * .91, maximum * .91),
    ]
    for label, x, y in labels:
        point = _map(x, y, plot, maximum)
        if ((point.x() - current.x()) ** 2 + (point.y() - current.y()) ** 2) ** .5 < 72 * scale:
            point.setX(min(plot.right() - 34 * scale, point.x() + 78 * scale))
            point.setY(max(plot.top() + 30 * scale, point.y() - 48 * scale))
        painter.setPen(QColor("#4A5565"))
        painter.drawText(QRectF(point.x() - 32 * scale, point.y() - 28 * scale, 64 * scale, 56 * scale), Qt.AlignmentFlag.AlignCenter, label)

    # 현재 교통량 점
    painter.setPen(QPen(Qt.GlobalColor.white, max(3, int(4 * scale))))
    painter.setBrush(QColor("#E5484D"))
    painter.drawEllipse(current, 16 * scale, 16 * scale)
    painter.setFont(_font(28, scale, QFont.Weight.Bold))
    painter.setPen(QColor("#C9363E"))
    label_y = current.y() - 48 * scale
    if q2 < maximum * .2:
        label_rect = QRectF(current.x() + 20 * scale, label_y, 220 * scale, 32 * scale)
        label_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    elif q2 > maximum * .8:
        label_rect = QRectF(current.x() - 240 * scale, label_y, 220 * scale, 32 * scale)
        label_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    else:
        label_rect = QRectF(current.x() - 110 * scale, label_y, 220 * scale, 32 * scale)
        label_align = Qt.AlignmentFlag.AlignCenter
    painter.drawText(label_rect, label_align, f"({q2:,.0f}, {q1:,.0f})")

    # 제목과 축
    painter.setPen(QColor("#172033"))
    painter.setFont(_font(39, scale, QFont.Weight.Bold))
    painter.drawText(QRectF(30 * scale, 12 * scale, size - 60 * scale, 42 * scale), Qt.AlignmentFlag.AlignCenter, f"{pair.name}  ·  영역 {pair.classification.area.value}")
    painter.setFont(_font(25, scale, QFont.Weight.Medium))
    painter.setPen(QColor("#596579"))
    painter.drawText(QRectF(30 * scale, 53 * scale, size - 60 * scale, 29 * scale), Qt.AlignmentFlag.AlignCenter, "교차로 교통 처리 능력  |  단위: 대/시")
    painter.drawText(QRectF(plot.left(), plot.bottom() + 42 * scale, plot.width(), 30 * scale), Qt.AlignmentFlag.AlignCenter, f"② {second.name} 교통량")
    painter.save()
    painter.translate(25 * scale, plot.center().y())
    painter.rotate(-90)
    painter.drawText(QRectF(-plot.height()/2, -14 * scale, plot.height(), 28 * scale), Qt.AlignmentFlag.AlignCenter, f"① {first.name} 교통량")
    painter.restore()

    # 하단 요약. 선 색뿐 아니라 실선/점선 문구로 식별 가능.
    painter.setFont(_font(24, scale, QFont.Weight.DemiBold))
    painter.setPen(QColor("#354052"))
    summary = (
        f"P  {first.no_turn_lane_capacity_p_display:,}/{second.no_turn_lane_capacity_p_display:,}   "
        f"P′  {first.with_turn_lane_capacity_p_prime_display:,}/{second.with_turn_lane_capacity_p_prime_display:,}   "
        f"C  {first.segment_capacity_c:,.0f}/{second.segment_capacity_c:,.0f}"
    )
    painter.drawText(QRectF(20 * scale, size - 48 * scale, size - 40 * scale, 26 * scale), Qt.AlignmentFlag.AlignCenter, summary)
    painter.end()
    return image


def save_pair_chart(pair: PairResult, path: str | Path, detailed: bool = False) -> bool:
    image = render_pair_chart(pair, 1800 if detailed else 839, detailed=detailed)
    return image.save(str(path), "PNG", 100)


class CapacityChart(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pair: PairResult | None = None
        self.setMinimumSize(400, 400)

    def set_pair(self, pair: PairResult | None) -> None:
        self.pair = pair
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        if self.pair is None:
            painter.setPen(QColor("#8994A5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "검토 결과를 선택하세요")
            return
        image = render_pair_chart(self.pair, max(839, min(1200, self.width() * 2)))
        target = QRectF(self.rect())
        side = min(target.width(), target.height())
        target = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter.drawImage(target, image)
