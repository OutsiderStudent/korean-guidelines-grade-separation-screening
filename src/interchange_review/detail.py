"""Validated detail inputs; guideline screening and lane capacity are separate.

KHCM 2026: printed pp.331–332 (8-2–4, table 8-4), pp.353–355
(tables 8-12–14). Lane capacity here is restricted to one common entry
signal per lane, observed lane demand, without blocking/channelization.
It is not the full chapter 8 demand-allocation or delay/LOS procedure.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

from .khcm2026 import (
    grade_adjustment_factor, lane_width_adjustment_factor,
    heavy_vehicle_adjustment_factor, protected_left_equivalent,
    right_turn_equivalent,
)


def number(label: str, value: float, low: float, high: float) -> None:
    if not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label}은 {low:g}~{high:g} 범위의 숫자로 입력해 주세요.")


@dataclass(frozen=True)
class RoadConditions:
    lane_width_m: float = 3.0
    grade_percent: float = 0.0
    left_geometry: str = "opposing"
    radius_m: float = 16.0
    opposing_lanes: int = 2
    lane_order: int = 1
    left_angle: float = 90.0
    right_turn_mode: str = "green"
    red_right_percent: float | None = None

    def __post_init__(self):
        number("차로폭(m)", self.lane_width_m, 2, 6)
        number("접근경사(%)", self.grade_percent, -20, 20)
        number("좌회전 교차각(°)", self.left_angle, 1, 179)
        if self.left_geometry not in ("radius", "opposing"):
            raise ValueError("좌회전 산정 기준을 선택해 주세요.")
        number("좌회전 곡선반경(m)", self.radius_m, 1, 500)
        for label, value in (("대향 차로수", self.opposing_lanes), ("차로순서", self.lane_order)):
            number(label, value, 1, 12)
            if int(value) != value:
                raise ValueError(f"{label}는 정수로 입력해 주세요.")
        if self.right_turn_mode not in ("green", "red", "mixed", "right_signal"):
            raise ValueError("우회전 통행방식을 선택해 주세요.")
        if self.right_turn_mode == "mixed":
            if self.red_right_percent is None:
                raise ValueError("적색에 실제 통과한 우회전 차량 비율을 입력해 주세요.")
            number("적색 우회전 차량 비율(%)", self.red_right_percent, 0, 100)

    @property
    def left_equivalent(self) -> float:
        if self.left_angle >= 120:
            return 1.0
        return protected_left_equivalent(
            radius_m=self.radius_m if self.left_geometry == "radius" else None,
            opposing_lanes_plus_lane_order=self.opposing_lanes + self.lane_order,
        )

    @property
    def right_equivalent(self) -> float:
        return right_turn_equivalent(
            self.right_turn_mode,
            None if self.red_right_percent is None else self.red_right_percent / 100,
        )


# Display order requested by the user. U-turn is an optional input.
LANE_TYPES = {
    "좌직우": ("left", "through", "right"),
    "좌회전": ("left",), "직좌": ("left", "through"),
    "직진": ("through",), "직우": ("through", "right"),
    "우회전": ("right",), "유턴": ("uturn",), "유좌": ("uturn", "left"),
}
MOVEMENTS = ("uturn", "left", "through", "right")


@dataclass(frozen=True)
class LaneInput:
    kind: str = "직진"
    width_m: float = 3.0
    left: float = 0.0
    through: float = 0.0
    right: float = 0.0
    uturn: float = 0.0
    heavy_left: float = 20.0
    heavy_through: float = 20.0
    heavy_right: float = 20.0
    heavy_uturn: float = 20.0
    green: float | None = None
    start_loss: float = 2.3
    extension: float = 2.0
    radius_m: float | None = None

    def __post_init__(self):
        if self.kind not in LANE_TYPES:
            raise ValueError("차로 진행방향을 선택해 주세요.")
        number("차로폭(m)", self.width_m, 2, 6)
        for movement in MOVEMENTS:
            flow = getattr(self, movement)
            number("차로별 교통량(대/시)", flow, 0, 99999)
            number("방향별 중차량 비율(%)", getattr(self, "heavy_" + movement), 0, 100)
            if flow and movement not in LANE_TYPES[self.kind]:
                raise ValueError(f"{self.kind} 차로에는 허용되지 않는 방향의 교통량이 있습니다.")
        if self.green is not None:
            number("진입신호시간(초)", self.green, 0, 600)
        number("출발손실시간(초)", self.start_loss, 0, 30)
        number("진입신호연장시간(초)", self.extension, 0, 30)
        if self.radius_m is not None:
            number("좌회전 곡선반경(m)", self.radius_m, 1, 500)

    @property
    def total(self):
        return sum(getattr(self, m) for m in MOVEMENTS)


@dataclass(frozen=True)
class LaneResult:
    demand: float
    effective_green: float
    saturation: float
    capacity: float
    saturation_ratio: float
    grade_factor: float
    width_factor: float
    heavy_factor: float
    movement_factor: float
    left_equivalent: float


def calculate_lane(lane: LaneInput, road: RoadConditions, *, cycle: float,
                   phf: float = 1.0, order: int = 1) -> LaneResult:
    """Same-entry-signal lane with observed movement demand (not allocated).

    Movement proportions use passenger-car-equivalent demand, table 8-4.
    Capacity and demand both use vehicles/hour. PHF applies only to demand.
    """
    number("신호주기(초)", cycle, 10, 600)
    number("첨두시간계수 PHF", phf, 0.25, 1)
    if lane.green is None:
        raise ValueError("차로의 진입신호시간을 입력해 주세요.")
    if not 0 < lane.green < cycle:
        raise ValueError("진입신호시간은 0보다 크고 신호주기보다 짧아야 합니다.")
    g = lane.green - lane.start_loss + lane.extension
    if not 0 < g <= cycle:
        raise ValueError("유효진입신호시간 G - 출발손실 + 연장이 0 초과, 주기 이하여야 합니다.")
    if "right" in LANE_TYPES[lane.kind] and road.right_turn_mode in ("red", "mixed"):
        raise ValueError("적색 우회전은 이동류 분리·대기행렬 분석이 필요하여 차로 용량을 산정하지 않습니다.")
    if road.right_turn_mode == "right_signal" and "right" in LANE_TYPES[lane.kind] and lane.kind != "우회전":
        raise ValueError("우회전신호 운영에는 우회전 전용차로가 필요합니다(표 8-15).")
    el = 1.0 if road.left_angle >= 120 else protected_left_equivalent(
        radius_m=lane.radius_m if lane.radius_m is not None else (
            road.radius_m if road.left_geometry == "radius" else None),
        opposing_lanes_plus_lane_order=road.opposing_lanes + order,
    )
    equivalents = {"uturn": 1.5, "left": el, "through": 1.0, "right": 1.2}
    pce = {m: getattr(lane, m) / heavy_vehicle_adjustment_factor(
        getattr(lane, "heavy_" + m) / 100) for m in MOVEMENTS}
    total_pce = sum(pce.values())
    if lane.total == 0:
        raise ValueError("교통량이 0인 차로는 이동류 비율을 정할 수 없어 용량을 산정하지 않습니다.")
    fhv = lane.total / total_pce
    fm = total_pce / sum(pce[m] * equivalents[m] for m in MOVEMENTS)
    fg = grade_adjustment_factor(road.grade_percent)
    fw = lane_width_adjustment_factor(lane.width_m)
    saturation = 2200 * fg * fw * fhv * fm
    capacity = saturation * g / cycle
    demand = lane.total / phf
    return LaneResult(demand, g, saturation, capacity, demand / capacity, fg, fw, fhv, fm, el)


def validate_lane_totals(lanes: list[LaneInput], expected: dict[str, float]) -> None:
    for key, label in (("left", "좌회전"), ("through", "직진"), ("right", "우회전")):
        actual = sum(getattr(lane, key) for lane in lanes)
        if abs(actual - expected[key]) > 0.01:
            raise ValueError(f"{label} 차로별 합계 {actual:,.0f}대/시가 기본 입력 {expected[key]:,.0f}대/시와 다릅니다.")


def road_defaults(settings: dict) -> dict:
    return {**asdict(RoadConditions()), **{k: settings[k] for k in (
        "lane_width_m", "grade_percent", "right_turn_mode", "red_right_percent") if k in settings}}
