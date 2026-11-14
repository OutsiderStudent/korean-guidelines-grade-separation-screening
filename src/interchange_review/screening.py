"""사용자 입력 중심의 입체교차 개략검토 모델.

판정 경계는 「교차로 설계 지침(2025.06)」의 A·B·C·D 식을 사용한다.
회전·중차량 자동 보정은 「도로용량편람(2026)」 제8장의 차로·이동류
보정식을 사용하며, 두 문헌의 역할을 결과와 부록에서 명확히 구분한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

from .engine import (
    Area,
    Classification,
    CorrectionFactors,
    DirectionResult,
    SignalAssumptions,
    classify_capacity_area,
    round_to_hundred,
)
from .khcm2013 import combined_turn_adjustment_factor, heavy_vehicle_adjustment_factor
from .khcm2026 import automatic_factors, right_turn_equivalent


# 진행방향 표기를 평면도의 북측 접근로부터 시계방향으로 정렬한다.
APPROACH_ORDER = ("SB", "SWB", "WB", "NWB", "NB", "NEB", "EB", "SEB")
OPPOSITES = {
    frozenset(("SB", "NB")),
    frozenset(("WB", "EB")),
    frozenset(("SEB", "NWB")),
    frozenset(("SWB", "NEB")),
}
AREA_RANK = {Area.A: 0, Area.B: 1, Area.C: 2, Area.D: 3}


@dataclass(frozen=True)
class CoefficientAssumptions:
    """자동 계수 산정에 쓰는 공개 가정.

    상세 신호현시를 입력하지 않는 입체화 개략검토의 자동 보정조건이다.
    기본값은 평지, 폭 3.0m, 보호좌회전, 녹색신호우회전 조건이다.
    """

    left_equivalent: float = 1.08
    right_equivalent: float = 1.2
    heavy_equivalent: float = 1.8
    lane_width_m: float = 3.0
    grade_percent: float = 0.0
    left_turn_mode: str = "protected"
    right_turn_mode: str = "green"
    legacy: bool = False
    red_right_percent: float | None = None

    @property
    def applied_right_equivalent(self) -> float:
        if self.legacy or self.right_turn_mode != "mixed":
            return self.right_equivalent
        ratio = None if self.red_right_percent is None else self.red_right_percent / 100
        return right_turn_equivalent("mixed", ratio)


@dataclass(frozen=True)
class ApproachInput:
    code: str
    lanes: int
    left: int
    through: int
    right: int
    heavy_percent: float
    direct_turn_factor: float | None = None
    direct_heavy_factor: float | None = None

    def __post_init__(self) -> None:
        if self.code not in APPROACH_ORDER:
            raise ValueError(f"지원하지 않는 접근로 코드입니다: {self.code}")
        if not 1 <= self.lanes <= 12:
            raise ValueError("편도 본선 차로수는 1~12의 정수여야 합니다.")
        if min(self.left, self.through, self.right) < 0:
            raise ValueError("방향별 교통량은 음수일 수 없습니다.")
        if not 0 <= self.heavy_percent <= 100:
            raise ValueError("중차량 비율은 0~100% 범위여야 합니다.")
        for label, value in (
            ("직접 회전 보정계수", self.direct_turn_factor),
            ("직접 중차량 보정계수", self.direct_heavy_factor),
        ):
            if value is not None and not 0 < value <= 1:
                raise ValueError(f"{label}는 0 초과 1 이하여야 합니다.")
        if (self.direct_turn_factor is None) != (self.direct_heavy_factor is None):
            raise ValueError("직접 회전·중차량 보정계수는 함께 입력해야 합니다.")

    @property
    def total(self) -> int:
        return self.left + self.through + self.right

    @property
    def left_ratio(self) -> float:
        return self.left / self.total if self.total else 0.0

    @property
    def right_ratio(self) -> float:
        return self.right / self.total if self.total else 0.0

    @property
    def through_ratio(self) -> float:
        return self.through / self.total if self.total else 0.0


@dataclass(frozen=True)
class ApproachResult:
    input: ApproachInput
    turn_factor: float
    heavy_factor: float
    factor_mode: str
    direction: DirectionResult
    movement_factor: float = 1.0
    grade_factor: float = 1.0
    lane_width_factor: float = 1.0


@dataclass(frozen=True)
class PairResult:
    first: ApproachResult
    second: ApproachResult
    classification: Classification

    @property
    def name(self) -> str:
        return f"{self.first.input.code}–{self.second.input.code}"


@dataclass(frozen=True)
class IntersectionResult:
    approaches: tuple[ApproachResult, ...]
    pairs: tuple[PairResult, ...]
    critical_pair: PairResult
    area: Area
    total_traffic: int
    is_extended_method: bool


def calculate_approach(
    data: ApproachInput,
    assumptions: CoefficientAssumptions | None = None,
    signal: SignalAssumptions | None = None,
) -> ApproachResult:
    assumptions = assumptions or CoefficientAssumptions()
    signal = signal or SignalAssumptions()
    if data.direct_turn_factor is not None:
        turn_factor = data.direct_turn_factor
        heavy_factor = data.direct_heavy_factor
        factor_mode = "직접 입력"
        movement_factor = turn_factor
        grade_factor = 1.0
        lane_width_factor = 1.0
    elif assumptions.legacy:
        turn_factor = movement_factor = combined_turn_adjustment_factor(
            data.left_ratio, assumptions.left_equivalent,
            data.right_ratio, assumptions.right_equivalent,
        )
        heavy_factor = heavy_vehicle_adjustment_factor(data.heavy_percent / 100, assumptions.heavy_equivalent)
        grade_factor = lane_width_factor = 1.0
        factor_mode = "기존 자동식"
    else:
        factors = automatic_factors(
            left_proportion=data.left_ratio,
            through_proportion=data.through_ratio if data.total else 1.0,
            right_proportion=data.right_ratio,
            heavy_proportion=data.heavy_percent / 100.0,
            lane_width_m=assumptions.lane_width_m,
            grade_percent=assumptions.grade_percent,
            left_equivalent_value=assumptions.left_equivalent,
            right_equivalent_value=assumptions.applied_right_equivalent,
            heavy_equivalent=assumptions.heavy_equivalent,
        )
        movement_factor = factors.movement
        grade_factor = factors.grade
        lane_width_factor = factors.lane_width
        turn_factor = factors.roadway_and_movement
        heavy_factor = factors.heavy_vehicle
        factor_mode = "개략 보정"
    capacity_c = 1_800.0 * data.lanes
    p_raw = capacity_c * turn_factor * heavy_factor * signal.utilization_factor
    p_prime_raw = (
        (capacity_c + signal.added_right_turn_capacity) * signal.utilization_factor
        + signal.left_turn_vehicles_per_cycle * 3_600.0 / signal.effective_green_seconds
    )
    direction = DirectionResult(
        name=data.code,
        hourly_design_traffic_q=float(data.total),
        one_direction_lanes=data.lanes,
        segment_capacity_c=capacity_c,
        no_turn_lane_capacity_p_raw=p_raw,
        no_turn_lane_capacity_p_display=round_to_hundred(p_raw),
        with_turn_lane_capacity_p_prime_raw=p_prime_raw,
        with_turn_lane_capacity_p_prime_display=round_to_hundred(p_prime_raw),
    )
    return ApproachResult(
        input=data,
        turn_factor=turn_factor,
        heavy_factor=heavy_factor,
        factor_mode=factor_mode,
        direction=direction,
        movement_factor=movement_factor,
        grade_factor=grade_factor,
        lane_width_factor=lane_width_factor,
    )


def conflict_pairs(codes: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    """동일 축의 마주보는 접근로를 제외한 충돌 접근로 쌍을 만든다."""

    order = {code: index for index, code in enumerate(APPROACH_ORDER)}
    unique = sorted(set(codes), key=order.__getitem__)
    return [
        (first, second)
        for first, second in combinations(unique, 2)
        if frozenset((first, second)) not in OPPOSITES
    ]


def analyze_intersection(
    approaches: list[ApproachInput] | tuple[ApproachInput, ...],
    assumptions: CoefficientAssumptions | None = None,
    signal: SignalAssumptions | None = None,
) -> IntersectionResult:
    if not 3 <= len(approaches) <= 6:
        raise ValueError("3~6지 교차로만 검토할 수 있습니다.")
    results = tuple(calculate_approach(item, assumptions, signal) for item in approaches)
    by_code = {item.input.code: item for item in results}
    pairs = tuple(
        PairResult(by_code[a], by_code[b], classify_capacity_area(by_code[a].direction, by_code[b].direction))
        for a, b in conflict_pairs(tuple(by_code))
    )
    if not pairs:
        raise ValueError("검토 가능한 충돌 접근로 쌍이 없습니다.")
    critical = max(
        pairs,
        key=lambda item: (
            AREA_RANK[item.classification.area],
            max(item.classification.a_utilization, item.classification.b_utilization),
        ),
    )
    return IntersectionResult(
        approaches=results,
        pairs=pairs,
        critical_pair=critical,
        area=critical.classification.area,
        total_traffic=sum(item.input.total for item in results),
        is_extended_method=len(approaches) != 4,
    )


def approach_to_dict(value: ApproachInput) -> dict:
    return asdict(value)
