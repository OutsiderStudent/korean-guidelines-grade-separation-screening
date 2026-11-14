"""Check a specified signal plan against movement demand in one cycle."""

from dataclasses import dataclass
from math import isfinite


TURNS = {"left": "좌회전", "through": "직진", "right": "우회전", "uturn": "유턴"}


@dataclass(frozen=True)
class Movement:
    approach: str
    turn: str
    exit_leg: str
    demand: int
    saturation: float
    lane_group: str
    phases: tuple[int, ...]


@dataclass(frozen=True)
class Phase:
    green: float
    other: float


@dataclass(frozen=True)
class MovementResult:
    movement: Movement
    required_green: float
    available_green: float
    group_required_green: float

    @property
    def ratio(self) -> float:
        return self.group_required_green / self.available_green


@dataclass(frozen=True)
class PhaseResult:
    cycle: float
    phases: tuple[Phase, ...]
    movements: tuple[MovementResult, ...]

    @property
    def feasible(self) -> bool:
        return all(item.ratio <= 1 + 1e-9 for item in self.movements)


def check_phase_plan(approaches, data: dict) -> PhaseResult:
    """Use user-verified simultaneous service and adjusted discharge rates.

    A shared lane group consumes the sum of its movement service times.
    Require identical service phases for shared movements because queue order
    and blocking cannot be represented by independent green-time fractions.
    """
    cycle = float(data["cycle"])
    if not isfinite(cycle) or cycle <= 0:
        raise ValueError("신호주기를 입력하세요.")
    phases = [Phase(**item) for item in data["phases"]]
    if not phases or any(not isfinite(p.green) or not isfinite(p.other) or p.green <= 0 or p.other < 0 for p in phases):
        raise ValueError("현시별 유효녹색시간과 그 외 시간을 확인하세요.")
    if abs(sum(p.green + p.other for p in phases) - cycle) > 1e-7:
        raise ValueError("현시별 시간의 합이 신호주기와 일치해야 합니다.")
    if data.get("confirmed") is not True:
        raise ValueError("신호계획의 동시 통행과 차로 사용 조건을 확인하세요.")

    legs = {item.code for item in approaches}
    expected = {(item.code, turn): getattr(item, turn) for item in approaches for turn in ("left", "through", "right")}
    actual = dict.fromkeys(expected, 0)
    groups = {}
    by_route = set()
    for row in data["movements"]:
        movement = Movement(**{**row, "phases": tuple(sorted(row["phases"]))})
        code, turn, exit_leg = movement.approach, movement.turn, movement.exit_leg
        label = f"{code} {TURNS.get(turn, turn)}"
        if code not in legs or turn not in TURNS or exit_leg not in legs or (exit_leg == code) != (turn == "uturn"):
            raise ValueError(f"{label} 이동류의 진출 방향을 확인하세요.")
        if type(movement.demand) is not int or movement.demand <= 0:
            raise ValueError(f"{label} 교통량은 1대/시 이상이어야 합니다.")
        if not isfinite(movement.saturation) or movement.saturation <= 0:
            raise ValueError(f"{label}의 보정 포화교통류율을 입력하세요.")
        selected = movement.phases
        if not selected or len(set(selected)) != len(selected) or any(type(i) is not int or not 1 <= i <= len(phases) for i in selected):
            raise ValueError(f"{label}의 통행 현시를 확인하세요.")
        route = (code, turn, exit_leg, movement.lane_group.strip())
        if route in by_route:
            raise ValueError(f"{label}에 같은 진출 방향과 차로군이 중복되어 있습니다.")
        by_route.add(route)
        if turn != "uturn":
            actual[code, turn] += movement.demand
        key = (code, movement.lane_group.strip()) if movement.lane_group.strip() else route
        groups.setdefault(key, []).append(movement)
    for (code, turn), demand in expected.items():
        if actual[code, turn] != demand:
            raise ValueError(f"{code} {TURNS[turn]} 교통량 합계가 기본 입력({demand:,}대/시)과 다릅니다.")
    if not groups:
        raise ValueError("검토할 이동류를 입력하세요.")

    # Direction codes identify the actual legs in clockwise order. Interleaved
    # endpoints on four distinct legs indicate crossing paths in this layout.
    from .screening import APPROACH_ORDER
    positions = {code: i for i, code in enumerate(APPROACH_ORDER)}
    movements = [item for members in groups.values() for item in members]
    for i, first in enumerate(movements):
        lo, hi = sorted((positions[first.approach], positions[first.exit_leg]))
        for second in movements[i + 1:]:
            common = set(first.phases).intersection(second.phases)
            if not common or len({first.approach, first.exit_leg, second.approach, second.exit_leg}) != 4:
                continue
            if (lo < positions[second.approach] < hi) != (lo < positions[second.exit_leg] < hi):
                raise ValueError(f"현시 {min(common)}에서 {first.approach}→{first.exit_leg}와 "
                                 f"{second.approach}→{second.exit_leg}가 교차합니다. 통행 현시를 나눠 주세요.")

    results = []
    for movements in groups.values():
        selected = movements[0].phases
        if any(item.phases != selected for item in movements):
            raise ValueError(f"{movements[0].approach} 차로군 {movements[0].lane_group}의 이동류별 통행 현시가 다릅니다. 공용차로 차단을 반영한 별도 용량 검토가 필요합니다.")
        available = sum(phases[i - 1].green for i in selected)
        required = [cycle * item.demand / item.saturation for item in movements]
        total = sum(required)
        results.extend(MovementResult(item, needed, available, total) for item, needed in zip(movements, required))
    return PhaseResult(cycle, tuple(phases), tuple(results))
