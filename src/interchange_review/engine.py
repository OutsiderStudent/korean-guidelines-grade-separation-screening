"""입체교차 개략 검토의 지침 기반 계산 코어.

근거 범위는 「교차로 설계 지침(국토교통부, 2025.06)」 PDF 244~247쪽
(문서 인쇄면 235~238쪽)의 식과 예제이다.

지침은 회전 및 대형차 보정계수의 일반 산정식을 이 범위에 제시하지 않고
예제 계수만 제시한다. 따라서 계수를 교통량 비율로부터 임의 추정하지 않고
명시적인 입력값으로 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


SATURATION_FLOW_PER_LANE = 1_800.0
SECONDS_PER_HOUR = 3_600.0


class Area(str, Enum):
    """지침 <그림 1-2>의 용량 영역."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


@dataclass(frozen=True)
class CorrectionFactors:
    """회전차로가 없을 때 P 산정에 사용하는 보정계수.

    일반식이 지침 해당 범위에 없으므로 세 계수는 반드시 출처를 확인하여
    입력해야 한다. 2025 지침 예제에서는 방향 1에 0.910/0.905/0.850,
    방향 2에 0.820/0.905/0.850을 사용한다.
    """

    left_turn: float
    right_turn: float
    heavy_vehicle: float

    def __post_init__(self) -> None:
        for name, value in (
            ("left_turn", self.left_turn),
            ("right_turn", self.right_turn),
            ("heavy_vehicle", self.heavy_vehicle),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"{name} 보정계수는 0 초과 1 이하여야 합니다: {value}")


@dataclass(frozen=True)
class SignalAssumptions:
    """회전차로 설치 시 P' 산정 가정.

    기본값은 지침 예제의 80초 주기(36+4+36+4), 좌회전 2대/주기,
    우회전 부가용량 600대/녹색시간, 유입부 용량 90%를 재현한다.
    """

    cycle_seconds: float = 80.0
    effective_green_seconds: float = 36.0
    left_turn_vehicles_per_cycle: float = 2.0
    added_right_turn_capacity: float = 600.0
    utilization_factor: float = 0.9

    def __post_init__(self) -> None:
        if self.cycle_seconds <= 0:
            raise ValueError("신호주기는 0보다 커야 합니다.")
        if not 0 < self.effective_green_seconds < self.cycle_seconds:
            raise ValueError("유효녹색시간은 0보다 크고 신호주기보다 작아야 합니다.")
        if self.left_turn_vehicles_per_cycle < 0:
            raise ValueError("주기당 좌회전 통행 대수는 음수일 수 없습니다.")
        if self.added_right_turn_capacity < 0:
            raise ValueError("우회전 부가용량은 음수일 수 없습니다.")
        if not 0 < self.utilization_factor <= 1:
            raise ValueError("유입부 이용계수는 0 초과 1 이하여야 합니다.")


@dataclass(frozen=True)
class DirectionInput:
    """한 도로 방향의 계획교통량 및 용량 입력.

    `daily_traffic`과 `total_lanes`는 양방향 합계이다. `directional_factor`는
    한쪽 방향 배분율이며 지침 예제의 `÷ 2`는 0.5에 해당한다.
    회전율과 대형차 혼입률은 계산 근거 표시 및 입력 검증용이며, 보정계수로
    자동 변환하지 않는다.
    """

    name: str
    daily_traffic: float
    peak_hour_factor_k: float
    directional_factor: float
    total_lanes: int
    left_turn_percent: float
    right_turn_percent: float
    heavy_vehicle_percent: float
    correction_factors: CorrectionFactors

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("방향 이름이 필요합니다.")
        if self.daily_traffic < 0:
            raise ValueError("설계 기준 일교통량은 음수일 수 없습니다.")
        if not 0 < self.peak_hour_factor_k <= 1:
            raise ValueError("시간계수 K는 0 초과 1 이하여야 합니다.")
        if not 0 < self.directional_factor <= 1:
            raise ValueError("방향배분계수는 0 초과 1 이하여야 합니다.")
        if self.total_lanes <= 0 or self.total_lanes % 2:
            raise ValueError("현재 개략 검토의 양방향 총 차로수는 양의 짝수여야 합니다.")
        for label, value in (
            ("좌회전율", self.left_turn_percent),
            ("우회전율", self.right_turn_percent),
            ("대형차 혼입률", self.heavy_vehicle_percent),
        ):
            if not 0 <= value <= 100:
                raise ValueError(f"{label}은 0~100% 범위여야 합니다: {value}")
        if self.left_turn_percent + self.right_turn_percent > 100:
            raise ValueError("좌회전율과 우회전율의 합은 100%를 넘을 수 없습니다.")


@dataclass(frozen=True)
class DirectionResult:
    """한 방향의 계산 결과. 판정에는 `raw` 값을 사용한다."""

    name: str
    hourly_design_traffic_q: float
    one_direction_lanes: int
    segment_capacity_c: float
    no_turn_lane_capacity_p_raw: float
    no_turn_lane_capacity_p_display: int
    with_turn_lane_capacity_p_prime_raw: float
    with_turn_lane_capacity_p_prime_display: int


@dataclass(frozen=True)
class Classification:
    area: Area
    message: str
    a_utilization: float
    b_utilization: float
    exceeds_segment_capacity: bool


def round_to_hundred(value: float) -> int:
    """지침 예제의 `2,268 ≒ 2,300` 방식으로 백 단위 반올림한다."""

    rounded = Decimal(str(value)).quantize(Decimal("1E2"), rounding=ROUND_HALF_UP)
    return int(rounded)


def calculate_direction(
    data: DirectionInput,
    signal: SignalAssumptions | None = None,
) -> DirectionResult:
    """지침 예제의 q, C, P, P'를 계산한다.

    P'의 좌회전 항은 지침의
    `7,200 / 80 * 80 / 36 = 200`을 일반화한 것이다. 7,200은
    `2대/주기 * 3,600초/시간`이며, 따라서 녹색 1시간 환산값은
    `주기당 좌회전 대수 * 3,600 / 유효녹색시간`이다.
    """

    signal = signal or SignalAssumptions()
    q = data.daily_traffic * data.peak_hour_factor_k * data.directional_factor
    one_direction_lanes = data.total_lanes // 2
    c = one_direction_lanes * SATURATION_FLOW_PER_LANE

    factors = data.correction_factors
    p_raw = (
        c
        * factors.left_turn
        * factors.right_turn
        * factors.heavy_vehicle
        * signal.utilization_factor
    )

    through_and_right = (
        one_direction_lanes * SATURATION_FLOW_PER_LANE
        + signal.added_right_turn_capacity
    ) * signal.utilization_factor
    left_turn_component = (
        signal.left_turn_vehicles_per_cycle
        * SECONDS_PER_HOUR
        / signal.effective_green_seconds
    )
    p_prime_raw = through_and_right + left_turn_component

    return DirectionResult(
        name=data.name,
        hourly_design_traffic_q=q,
        one_direction_lanes=one_direction_lanes,
        segment_capacity_c=c,
        no_turn_lane_capacity_p_raw=p_raw,
        no_turn_lane_capacity_p_display=round_to_hundred(p_raw),
        with_turn_lane_capacity_p_prime_raw=p_prime_raw,
        with_turn_lane_capacity_p_prime_display=round_to_hundred(p_prime_raw),
    )


def classify_capacity_area(
    direction_1: DirectionResult,
    direction_2: DirectionResult,
    *,
    tolerance: float = 1e-9,
) -> Classification:
    """점 P(q2, q1)를 지침의 A, B, C, D 영역으로 분류한다.

    표시용 반올림값이 아닌 원시 용량을 사용하며, A/B 판정보다 먼저 지침의
    `q2 <= C2, q1 <= C1` 단로부 용량 상한을 적용한다.
    """

    q1 = direction_1.hourly_design_traffic_q
    q2 = direction_2.hourly_design_traffic_q
    c1 = direction_1.segment_capacity_c
    c2 = direction_2.segment_capacity_c
    p1 = direction_1.no_turn_lane_capacity_p_raw
    p2 = direction_2.no_turn_lane_capacity_p_raw
    pp1 = direction_1.with_turn_lane_capacity_p_prime_raw
    pp2 = direction_2.with_turn_lane_capacity_p_prime_raw

    if min(p1, p2, pp1, pp2) <= 0:
        raise ValueError("P와 P' 용량은 모두 0보다 커야 합니다.")

    a_utilization = q2 / p2 + q1 / p1
    b_utilization = q2 / pp2 + q1 / pp1
    exceeds_segment = q2 > c2 + tolerance or q1 > c1 + tolerance

    if exceeds_segment:
        return Classification(
            Area.D,
            "단로부 용량을 초과하므로 단로부 확폭 또는 추가 도로계획이 필요합니다.",
            a_utilization,
            b_utilization,
            True,
        )
    if a_utilization <= 1 + tolerance:
        return Classification(
            Area.A,
            "회전차로를 부가하지 않고 신호처리가 가능합니다.",
            a_utilization,
            b_utilization,
            False,
        )
    if b_utilization <= 1 + tolerance:
        return Classification(
            Area.B,
            "회전차로를 부가하면 평면 신호처리가 가능합니다.",
            a_utilization,
            b_utilization,
            False,
        )
    return Classification(
        Area.C,
        "직진 부가차로 설치 또는 입체교차 처리가 필요합니다.",
        a_utilization,
        b_utilization,
        False,
    )

