"""2026 도로용량편람 제8장 신호교차로의 핵심 보정계수.

입체화 A·B·C·D 판정식은 ``engine`` 모듈의 2025 교차로 설계지침
계산을 그대로 사용한다. 이 모듈은 그 판정에 필요한 자동 보정계수를
2026 편람의 차로·이동류 보정 방식으로 산정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


BASE_SATURATION_FLOW = 2_200.0
HEAVY_VEHICLE_EQUIVALENT = 1.8


class LeftTurnMode(str, Enum):
    PROTECTED = "protected"
    PERMISSIVE = "permissive"
    PROTECTED_PERMISSIVE = "protected_permissive"


class RightTurnMode(str, Enum):
    GREEN = "green"
    RED = "red"
    RIGHT_SIGNAL = "right_signal"
    MIXED = "mixed"


def _fraction(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}은 0~1 범위여야 합니다: {value}")


def grade_adjustment_factor(grade_percent: float) -> float:
    """표 8-4의 접근경사 보정계수 ``min(1, 1-0.012gr)``."""

    value = min(1.0, 1.0 - 0.012 * grade_percent)
    if value <= 0:
        raise ValueError("접근경사 보정계수가 0 이하가 되는 값은 사용할 수 없습니다.")
    return value


def lane_width_adjustment_factor(width_m: float) -> float:
    """표 8-4의 차로폭 보정계수 ``min(1, 1-0.35(3-w))``."""

    if width_m <= 0:
        raise ValueError("차로폭은 0보다 커야 합니다.")
    value = min(1.0, 1.0 - 0.35 * (3.0 - width_m))
    if value <= 0:
        raise ValueError("차로폭 보정계수가 0 이하가 되는 값은 사용할 수 없습니다.")
    return value


def heavy_vehicle_adjustment_factor(
    proportion: float,
    equivalent: float = HEAVY_VEHICLE_EQUIVALENT,
) -> float:
    """표 8-4의 중차량 보정계수."""

    _fraction("중차량 비율", proportion)
    if equivalent < 1:
        raise ValueError("중차량 승용차환산계수는 1 이상이어야 합니다.")
    return 1.0 / ((1.0 - proportion) + proportion * equivalent)


def protected_left_equivalent(
    *, radius_m: float | None = None, opposing_lanes_plus_lane_order: int | None = None
) -> float:
    """표 8-14의 녹색신호 좌회전 직진환산계수.

    곡선반경을 알면 이를 우선 사용하고, 모르면 ``대향차로수+차로순서``를
    이용한다. 두 자료가 모두 없을 때는 일반적인 2차로 대향 조건 1.08을
    적용한다.
    """

    if radius_m is not None:
        if radius_m <= 0:
            raise ValueError("좌회전 곡선반경은 0보다 커야 합니다.")
        if radius_m <= 13:
            return 1.11
        if radius_m <= 16:
            return 1.08
        if radius_m <= 19:
            return 1.05
        return 1.00
    if opposing_lanes_plus_lane_order is None:
        return 1.08
    if opposing_lanes_plus_lane_order <= 2:
        return 1.11
    if opposing_lanes_plus_lane_order == 3:
        return 1.08
    if opposing_lanes_plus_lane_order == 4:
        return 1.05
    return 1.00


def permissive_left_equivalent(
    opposing_through_flow: float,
    opposing_through_lanes: int = 2,
) -> float:
    """식 8-18의 비보호좌회전 직진환산계수.

    대향 직진교통류가 없으면 편람이 제시한 1.53을 적용한다.
    """

    if opposing_through_flow < 0:
        raise ValueError("대향 직진교통류율은 음수일 수 없습니다.")
    if opposing_through_lanes < 1:
        raise ValueError("대향 직진차로수는 1 이상이어야 합니다.")
    if opposing_through_flow == 0:
        return 1.53
    import math

    critical_gap = 4.2 if opposing_through_lanes == 1 else 4.9
    follow_up = 2.5
    permitted_capacity = opposing_through_flow * (
        math.exp(-opposing_through_flow * critical_gap / 3_600.0)
        / (1.0 - math.exp(-opposing_through_flow * follow_up / 3_600.0))
    )
    if permitted_capacity <= 0:
        return 1.53
    return max(1.0, 2_200.0 / permitted_capacity)


def left_turn_equivalent(
    mode: LeftTurnMode | str = LeftTurnMode.PROTECTED,
    *,
    radius_m: float | None = None,
    opposing_through_flow: float = 0.0,
    opposing_through_lanes: int = 2,
) -> float:
    mode = LeftTurnMode(mode)
    protected = protected_left_equivalent(radius_m=radius_m)
    if mode is LeftTurnMode.PROTECTED:
        return protected
    permissive = permissive_left_equivalent(opposing_through_flow, opposing_through_lanes)
    if mode is LeftTurnMode.PERMISSIVE:
        return permissive
    # 보호·비보호 겸용의 정확한 이동류 구성비가 없을 때 불리한 값을 적용한다.
    return max(protected, permissive)


def right_turn_equivalent(
    mode: RightTurnMode | str = RightTurnMode.GREEN,
    red_proportion: float | None = None,
) -> float:
    mode = RightTurnMode(mode)
    if mode is RightTurnMode.MIXED:
        if red_proportion is None:
            raise ValueError("적색에 통과한 우회전 차량 비율을 입력해 주세요.")
        _fraction("적색 우회전 차량 비율", red_proportion)
        return (1 - red_proportion) * 1.2 + red_proportion * 2.0
    if mode is RightTurnMode.RED:
        return 2.0
    return 1.2


def movement_adjustment_factor(
    left_proportion: float,
    through_proportion: float,
    right_proportion: float,
    *,
    left_equivalent_value: float,
    right_equivalent_value: float,
) -> float:
    """표 8-4의 이동류 보정계수 ``1 / sum(pM*EM)``."""

    for name, value in (
        ("좌회전 비율", left_proportion),
        ("직진 비율", through_proportion),
        ("우회전 비율", right_proportion),
    ):
        _fraction(name, value)
    total = left_proportion + through_proportion + right_proportion
    if abs(total - 1.0) > 1e-9:
        raise ValueError("이동류 구성비의 합은 1이어야 합니다.")
    if left_equivalent_value < 1 or right_equivalent_value < 1:
        raise ValueError("이동류 직진환산계수는 1 이상이어야 합니다.")
    return 1.0 / (
        left_proportion * left_equivalent_value
        + through_proportion
        + right_proportion * right_equivalent_value
    )


@dataclass(frozen=True)
class AutomaticFactors:
    movement: float
    heavy_vehicle: float
    grade: float
    lane_width: float

    @property
    def roadway_and_movement(self) -> float:
        return self.movement * self.grade * self.lane_width

    @property
    def total(self) -> float:
        return self.roadway_and_movement * self.heavy_vehicle


def automatic_factors(
    *,
    left_proportion: float,
    through_proportion: float,
    right_proportion: float,
    heavy_proportion: float,
    lane_width_m: float = 3.0,
    grade_percent: float = 0.0,
    left_equivalent_value: float = 1.08,
    right_equivalent_value: float = 1.2,
    heavy_equivalent: float = HEAVY_VEHICLE_EQUIVALENT,
) -> AutomaticFactors:
    return AutomaticFactors(
        movement=movement_adjustment_factor(
            left_proportion,
            through_proportion,
            right_proportion,
            left_equivalent_value=left_equivalent_value,
            right_equivalent_value=right_equivalent_value,
        ),
        heavy_vehicle=heavy_vehicle_adjustment_factor(heavy_proportion, heavy_equivalent),
        grade=grade_adjustment_factor(grade_percent),
        lane_width=lane_width_adjustment_factor(lane_width_m),
    )


def lane_saturation_flow(factors: AutomaticFactors) -> float:
    """식 8-4의 차로 포화교통류율."""

    return BASE_SATURATION_FLOW * factors.total


def lane_capacity(saturation_flow: float, effective_green: float, cycle: float) -> float:
    """식 8-2의 차로 용량 ``c=s*g/C``."""

    if saturation_flow <= 0 or cycle <= 0:
        raise ValueError("포화교통류율과 신호주기는 0보다 커야 합니다.")
    if not 0 < effective_green <= cycle:
        raise ValueError("유효진입신호시간은 0보다 크고 신호주기 이하여야 합니다.")
    return saturation_flow * effective_green / cycle
