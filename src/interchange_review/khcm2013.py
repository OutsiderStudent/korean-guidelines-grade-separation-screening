"""2013 도로용량편람 제8장 신호교차로의 보정계수 계산.

이 모듈은 2025 교차로 설계 지침의 A·B·C·D 개략검토 계산과 분리한다.
2013 편람은 기본 포화교통류율 2,200 pcphgpl과 차로군 단위 분석을 사용하며,
2025 지침 예제의 차로당 1,800대/시 단순식과 동일한 방법이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass


KHCM_BASE_SATURATION_FLOW = 2_200.0
KHCM_HEAVY_VEHICLE_EQUIVALENT = 1.8


def _validate_fraction(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name}은 0~1 범위의 비율이어야 합니다: {value}")


def turn_adjustment_factor(proportion: float, equivalent: float) -> float:
    """편람 식 8-26의 회전 보정계수 ``1 / (1 + P(E - 1))``."""

    _validate_fraction("회전교통량 비율 P", proportion)
    if equivalent < 1:
        raise ValueError("직진환산계수 E는 1 이상이어야 합니다.")
    return 1.0 / (1.0 + proportion * (equivalent - 1.0))


def combined_turn_adjustment_factor(
    left_proportion: float,
    left_equivalent: float,
    right_proportion: float,
    right_equivalent: float,
) -> float:
    """직진·좌·우회전 통합차로군의 편람 식 8-26."""

    _validate_fraction("좌회전 비율 PLT", left_proportion)
    _validate_fraction("우회전 비율 PRT", right_proportion)
    if left_proportion + right_proportion > 1:
        raise ValueError("통합차로군의 좌·우회전 비율 합은 1을 넘을 수 없습니다.")
    if left_equivalent < 1 or right_equivalent < 1:
        raise ValueError("좌·우회전 직진환산계수는 1 이상이어야 합니다.")
    return 1.0 / (
        1.0
        + left_proportion * (left_equivalent - 1.0)
        + right_proportion * (right_equivalent - 1.0)
    )


def heavy_vehicle_adjustment_factor(
    heavy_vehicle_proportion: float,
    equivalent: float = KHCM_HEAVY_VEHICLE_EQUIVALENT,
) -> float:
    """편람 식 8-39의 중차량 보정계수.

    기본 승용차환산계수는 편람이 제시한 1.8이다. 따라서 기본식은
    ``fHV = 1 / (1 + 0.8P)``가 된다.
    """

    _validate_fraction("중차량 혼입비율 P", heavy_vehicle_proportion)
    if equivalent < 1:
        raise ValueError("중차량 승용차환산계수는 1 이상이어야 합니다.")
    return 1.0 / (
        1.0 + heavy_vehicle_proportion * (equivalent - 1.0)
    )


def lane_width_adjustment_factor(width_m: float) -> float:
    """편람 표 8-15의 차로폭 보정계수."""

    if width_m <= 0:
        raise ValueError("차로폭은 0보다 커야 합니다.")
    if width_m <= 2.6:
        return 0.88
    if width_m <= 2.9:
        return 0.94
    return 1.00


def grade_adjustment_factor(grade_percent: float) -> float:
    """편람 표 8-16을 선형 보간한 접근로 경사 보정계수.

    하향 또는 평지(0% 이하)는 1.00, +3%는 0.96, +6% 이상은 0.93이다.
    표의 주기에 따라 중간값은 보간한다.
    """

    if grade_percent <= 0:
        return 1.00
    if grade_percent <= 3:
        return 1.00 + (0.96 - 1.00) * grade_percent / 3.0
    if grade_percent < 6:
        return 0.96 + (0.93 - 0.96) * (grade_percent - 3.0) / 3.0
    return 0.93


def left_turn_radius_equivalent(radius_m: float) -> float:
    """편람 표 8-9의 좌회전 곡선반경별 직진환산계수 Ep."""

    if radius_m <= 0:
        raise ValueError("좌회전 곡선반경은 0보다 커야 합니다.")
    if radius_m <= 9:
        return 1.14
    if radius_m <= 12:
        return 1.11
    if radius_m <= 15:
        return 1.09
    if radius_m <= 18:
        return 1.06
    if radius_m <= 20:
        return 1.05
    return 1.00


def _linear_table_interpolation(value: float, table: tuple[tuple[float, float], ...]) -> float:
    if value < table[0][0] or value > table[-1][0]:
        raise ValueError(f"값이 표의 적용범위 {table[0][0]}~{table[-1][0]}를 벗어났습니다: {value}")
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if value <= x1:
            if value == x0:
                return y0
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return table[-1][1]


def u_turn_equivalent(u_turn_percent: float, left_turn_lane_count: int) -> float:
    """편람 표 8-10·8-11의 U턴 영향 직진환산계수 Eu.

    표의 주기에 따라 표 사이 값은 선형 보간한다. 1개 좌회전 차로는
    U턴비율 0~60%, 2개 차로는 0~30% 범위만 허용한다.
    """

    if left_turn_lane_count == 1:
        table = (
            (0.0, 1.00),
            (10.0, 1.21),
            (20.0, 1.39),
            (30.0, 1.64),
            (40.0, 1.97),
            (50.0, 2.55),
            (60.0, 3.25),
        )
    elif left_turn_lane_count == 2:
        table = (
            (0.0, 1.00),
            (10.0, 1.17),
            (20.0, 1.30),
            (30.0, 1.48),
        )
    else:
        raise ValueError("U턴 표는 좌회전 차로 1개 또는 2개에만 적용됩니다.")
    return _linear_table_interpolation(u_turn_percent, table)


def left_turn_equivalent(
    base_equivalent: float,
    radius_equivalent: float,
    u_turn_effect: float,
) -> float:
    """편람 식 8-6의 종합 좌회전 직진환산계수 EL."""

    if min(base_equivalent, radius_equivalent, u_turn_effect) < 1:
        raise ValueError("좌회전 직진환산계수 구성값은 모두 1 이상이어야 합니다.")
    return base_equivalent * radius_equivalent * u_turn_effect


@dataclass(frozen=True)
class SaturationFlowInputs:
    """편람 식 8-28의 차로군 포화교통량 입력."""

    lane_count: int
    turn_factor: float
    lane_width_factor: float
    grade_factor: float
    heavy_vehicle_factor: float
    base_saturation_flow: float = KHCM_BASE_SATURATION_FLOW

    def __post_init__(self) -> None:
        if self.lane_count <= 0:
            raise ValueError("차로군 차로수는 1 이상이어야 합니다.")
        if self.base_saturation_flow <= 0:
            raise ValueError("기본 포화교통류율은 0보다 커야 합니다.")
        for name, value in (
            ("회전 보정계수", self.turn_factor),
            ("차로폭 보정계수", self.lane_width_factor),
            ("경사 보정계수", self.grade_factor),
            ("중차량 보정계수", self.heavy_vehicle_factor),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"{name}는 0 초과 1 이하여야 합니다: {value}")


def saturation_flow(inputs: SaturationFlowInputs) -> float:
    """편람 식 8-28에 따른 차로군 포화교통량 Si."""

    return (
        inputs.base_saturation_flow
        * inputs.lane_count
        * inputs.turn_factor
        * inputs.lane_width_factor
        * inputs.grade_factor
        * inputs.heavy_vehicle_factor
    )
