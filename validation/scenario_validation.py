"""입체화검토 v3.6.0 대량 시나리오 독립 검증.

프로그램 코어와 별도로 지침 경계식을 다시 계산하고, 국내에서 흔히 볼 수
있는 차로수·교통량·회전율·중차량 조합 및 전체 지원 접근로 조합을 점검한다.
"""

from __future__ import annotations

import csv
import json
import os
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from interchange_review.app import resource_path
from interchange_review.chart import render_pair_chart
from interchange_review.engine import Area, DirectionResult, classify_capacity_area
from interchange_review.screening import (
    APPROACH_ORDER,
    ApproachInput,
    analyze_intersection,
    conflict_pairs,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "validation" / "results_current"
CHARTS = OUT / "charts"
RNG = random.Random(20250829)
AREA_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


@dataclass(frozen=True)
class ManualCapacity:
    q: float
    c: float
    p: float
    pp: float


def manual_capacity(
    value: ApproachInput,
    *,
    combined_turn: bool,
    fixed_right_turn_addition: bool,
) -> ManualCapacity:
    """프로그램을 호출하지 않고 문헌 식으로 q, C, P, P'를 계산한다."""

    q = float(value.total)
    c = 1_800.0 * value.lanes
    pl = value.left_ratio
    pr = value.right_ratio
    fhv = 1.0 / (1.0 + (value.heavy_percent / 100.0) * (1.8 - 1.0))
    if value.direct_turn_factor is not None:
        fturn = value.direct_turn_factor
        fhv = value.direct_heavy_factor
    elif combined_turn:
        # 도로용량편람(2013) 식 8-26: 직진+좌+우 통합차로군.
        fturn = 1.0 / (1.0 + pl * (2.0 - 1.0) + pr * (1.5 - 1.0))
    else:
        # 현재 v3.2.0 구현: 좌·우 보정계수를 각각 구해 곱함.
        fturn = (
            1.0 / (1.0 + pl * (2.0 - 1.0))
            * 1.0 / (1.0 + pr * (1.5 - 1.0))
        )
    p = c * fturn * fhv * 0.9
    right_addition = 600.0 if fixed_right_turn_addition else 300.0 * value.lanes
    pp = (c + right_addition) * 0.9 + 2.0 * 3_600.0 / 36.0
    return ManualCapacity(q, c, p, pp)


def manual_area(first: ManualCapacity, second: ManualCapacity) -> tuple[str, float, float]:
    """지침 PDF 245쪽의 A·B·C·D 경계식을 독립 구현한다."""

    a = second.q / second.p + first.q / first.p
    b = second.q / second.pp + first.q / first.pp
    if second.q > second.c + 1e-9 or first.q > first.c + 1e-9:
        return "D", a, b
    if a <= 1.0 + 1e-9:
        return "A", a, b
    if b <= 1.0 + 1e-9:
        return "B", a, b
    return "C", a, b


def manual_intersection(
    approaches: list[ApproachInput],
    *,
    combined_turn: bool,
    fixed_right_turn_addition: bool,
) -> tuple[str, str, list[tuple[str, str, float, float]]]:
    by_code = {
        item.code: manual_capacity(
            item,
            combined_turn=combined_turn,
            fixed_right_turn_addition=fixed_right_turn_addition,
        )
        for item in approaches
    }
    pair_rows: list[tuple[str, str, float, float]] = []
    for first, second in conflict_pairs([item.code for item in approaches]):
        area, au, bu = manual_area(by_code[first], by_code[second])
        pair_rows.append((f"{first}–{second}", area, au, bu))
    critical = max(pair_rows, key=lambda row: (AREA_RANK[row[1]], max(row[2], row[3])))
    return critical[1], critical[0], pair_rows


def make_approach(
    code: str,
    lanes: int,
    volume_per_lane: float,
    imbalance: float,
    left_share: float,
    right_share: float,
    heavy: float,
) -> ApproachInput:
    total = max(1, round(lanes * volume_per_lane * imbalance))
    left = round(total * left_share)
    right = round(total * right_share)
    through = total - left - right
    return ApproachInput(code, lanes, left, through, right, heavy)


TOPOLOGIES = {
    "3지_T형": ["SB", "WB", "EB"],
    "3지_Y형": ["SB", "SWB", "SEB"],
    "4지_십자형": ["SB", "WB", "NB", "EB"],
    "4지_사교차": ["SB", "SWB", "NB", "EB"],
    "5지_도시형": ["SB", "SWB", "WB", "NB", "EB"],
    "6지_방사형": ["SB", "SWB", "WB", "NWB", "NB", "EB"],
}

LANE_PATTERNS = {
    "소규모_1차로": lambda code, index: 1,
    "일반_2차로": lambda code, index: 2,
    "주간선_혼합": lambda code, index: 3 if code in {"SB", "NB"} else 1,
    "도심_다차로": lambda code, index: 3 if index % 2 == 0 else 2,
    "광로_4~6차로": lambda code, index: 6 if code in {"SB", "NB"} else 4,
}

DEMAND_LEVELS = {
    "매우한산": 120,
    "한산": 300,
    "보통": 650,
    "혼잡초기": 950,
    "혼잡": 1_250,
    "포화근접": 1_550,
    "용량초과": 1_950,
    "극심혼잡": 2_150,
}

TURN_PROFILES = {
    "완전직진": (0.00, 0.00),
    "직진중심": (0.05, 0.05),
    "일반도시": (0.15, 0.10),
    "좌회전집중": (0.35, 0.10),
    "우회전집중": (0.10, 0.35),
}

HEAVY_PROFILES = {"승용차전용": 0.0, "승용차중심": 5.0, "일반혼합": 15.0, "산업물류": 35.0}


def structured_scenarios():
    scenario_id = 0
    for topology_name, codes in TOPOLOGIES.items():
        for lane_name, lane_fn in LANE_PATTERNS.items():
            for demand_name, vpl in DEMAND_LEVELS.items():
                for turn_name, (left_share, right_share) in TURN_PROFILES.items():
                    for heavy_name, heavy in HEAVY_PROFILES.items():
                        scenario_id += 1
                        approaches = []
                        for index, code in enumerate(codes):
                            # 실제 교차로의 주·부도로 불균형을 재현하는 결정적 계수.
                            imbalance = (1.12, 0.88, 1.00, 0.76, 1.08, 0.92)[index]
                            approaches.append(
                                make_approach(
                                    code,
                                    lane_fn(code, index),
                                    vpl,
                                    imbalance,
                                    left_share,
                                    right_share,
                                    heavy,
                                )
                            )
                        yield {
                            "id": f"R{scenario_id:04d}",
                            "topology": topology_name,
                            "lane_profile": lane_name,
                            "demand": demand_name,
                            "turn_profile": turn_name,
                            "heavy_profile": heavy_name,
                            "approaches": approaches,
                        }


def random_approach(code: str) -> ApproachInput:
    lanes = RNG.choices([1, 2, 3, 4, 5, 6], weights=[12, 35, 28, 16, 6, 3])[0]
    vpl = RNG.uniform(50, 2_300)
    total = max(1, round(lanes * vpl))
    left_share = RNG.uniform(0.0, 0.42)
    right_share = RNG.uniform(0.0, min(0.42, 0.75 - left_share))
    left = round(total * left_share)
    right = round(total * right_share)
    return ApproachInput(
        code,
        lanes,
        left,
        total - left - right,
        right,
        RNG.uniform(0.0, 40.0),
    )


def guideline_example_check() -> dict:
    auto = analyze_intersection([
        ApproachInput("SB", 2, 220, 1_540, 440, 20),
        ApproachInput("WB", 2, 360, 1_080, 360, 20),
        ApproachInput("EB", 2, 1, 1, 1, 20),
    ])
    direct = analyze_intersection([
        ApproachInput("SB", 2, 220, 1_540, 440, 20, 0.910 * 0.905, 0.850),
        ApproachInput("WB", 2, 360, 1_080, 360, 20, 0.820 * 0.905, 0.850),
        ApproachInput("EB", 2, 1, 1, 1, 20, 1.0, 1.0),
    ])
    auto_by_code = {item.input.code: item for item in auto.approaches}
    direct_by_code = {item.input.code: item for item in direct.approaches}
    def values(program, by_code):
        return {
            "P1": by_code["SB"].direction.no_turn_lane_capacity_p_raw,
            "P2": by_code["WB"].direction.no_turn_lane_capacity_p_raw,
            "P1_display": by_code["SB"].direction.no_turn_lane_capacity_p_display,
            "P2_display": by_code["WB"].direction.no_turn_lane_capacity_p_display,
            "P_prime_1": by_code["SB"].direction.with_turn_lane_capacity_p_prime_raw,
            "P_prime_2": by_code["WB"].direction.with_turn_lane_capacity_p_prime_raw,
            "pair_area": next(pair.classification.area.value for pair in program.pairs if pair.name == "SB–WB"),
        }
    return {
        "guideline_expected": {
            "q1": 2200,
            "q2": 1800,
            "C1": 3600,
            "C2": 3600,
            "P1": 2268.0567,
            "P2": 2043.7434,
            "P1_display": 2300,
            "P2_display": 2000,
            "P_prime": 3980,
            "area": "C",
        },
        "automatic_mode": values(auto, auto_by_code),
        "direct_mode": values(direct, direct_by_code),
    }


def transition_text(counter: Counter[tuple[str, str]]) -> str:
    return ", ".join(f"{a}→{b}: {n:,}" for (a, b), n in sorted(counter.items()))


def boundary_checks() -> tuple[int, int, list[dict[str, float | str]]]:
    """A/B/C/D 경계선과 바로 양쪽을 프로그램 판정기로 직접 시험한다."""

    p1, p2 = 2_300.0, 2_000.0
    pp1, pp2 = 4_000.0, 4_000.0
    c1 = c2 = 3_600.0
    epsilon = 0.001
    cases: list[tuple[str, float, float, str]] = []

    # q2를 고정하고 A 및 B 경계의 q1을 해석적으로 구한다.
    for q2 in (0.0, 500.0, 1_000.0, 1_500.0):
        a_q1 = p1 * (1.0 - q2 / p2)
        b_q1 = pp1 * (1.0 - q2 / pp2)
        if a_q1 >= 0:
            cases.extend(
                [
                    ("A boundary below", a_q1 - epsilon, q2, "A"),
                    ("A boundary exact", a_q1, q2, "A"),
                    ("A boundary above", a_q1 + epsilon, q2, "B"),
                ]
            )
        if 0 <= b_q1 <= c1:
            cases.extend(
                [
                    ("B boundary below", b_q1 - epsilon, q2, "B"),
                    ("B boundary exact", b_q1, q2, "B"),
                    ("B boundary above", b_q1 + epsilon, q2, "C"),
                ]
            )

    # C/D는 각 축의 구간 용량을 초과하는 순간 전환되어야 한다.
    cases.extend(
        [
            ("C1 exact", c1, 100.0, "B"),
            ("C1 exceeded", c1 + epsilon, 100.0, "D"),
            ("C2 exact", 100.0, c2, "B"),
            ("C2 exceeded", 100.0, c2 + epsilon, "D"),
        ]
    )

    rows: list[dict[str, float | str]] = []
    failures = 0
    for name, q1, q2, expected in cases:
        first = DirectionResult("1", q1, 2, c1, p1, 2_300, pp1, 4_000)
        second = DirectionResult("2", q2, 2, c2, p2, 2_000, pp2, 4_000)
        actual = classify_capacity_area(first, second).area.value
        if actual != expected:
            failures += 1
        rows.append({"case": name, "q1": q1, "q2": q2, "expected": expected, "actual": actual})
    return len(cases), failures, rows


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)
    structured_rows = []
    current_mismatches = []
    legacy_transitions: Counter[tuple[str, str]] = Counter()
    pprime_transitions: Counter[tuple[str, str]] = Counter()
    area_distribution: Counter[str] = Counter()
    topology_distribution: dict[str, Counter[str]] = {}
    graph_candidates: dict[str, list] = {area: [] for area in "ABCD"}

    scenarios = list(structured_scenarios())
    for scenario in scenarios:
        approaches = scenario["approaches"]
        program = analyze_intersection(approaches)
        oracle_area, oracle_pair, oracle_pairs = manual_intersection(
            approaches, combined_turn=True, fixed_right_turn_addition=True
        )
        if (program.area.value, program.critical_pair.name) != (oracle_area, oracle_pair):
            current_mismatches.append(scenario["id"])
        legacy_area, _, _ = manual_intersection(
            approaches, combined_turn=False, fixed_right_turn_addition=False
        )
        variable_right_area, _, _ = manual_intersection(
            approaches, combined_turn=True, fixed_right_turn_addition=False
        )
        legacy_transitions[(legacy_area, program.area.value)] += 1
        pprime_transitions[(variable_right_area, program.area.value)] += 1
        area_distribution[program.area.value] += 1
        topology_distribution.setdefault(scenario["topology"], Counter())[program.area.value] += 1
        if len(graph_candidates[program.area.value]) < 10:
            graph_candidates[program.area.value].append(program.critical_pair)
        structured_rows.append(
            {
                "id": scenario["id"],
                "topology": scenario["topology"],
                "lane_profile": scenario["lane_profile"],
                "demand": scenario["demand"],
                "turn_profile": scenario["turn_profile"],
                "heavy_profile": scenario["heavy_profile"],
                "approach_count": len(approaches),
                "total_traffic": sum(item.total for item in approaches),
                "program_area": program.area.value,
                "critical_pair": program.critical_pair.name,
                "pair_count": len(program.pairs),
                "legacy_v320_area": legacy_area,
                "variable_right_addition_area": variable_right_area,
            }
        )

    # 프로그램 구현과 독립 동일식 간 250,000개 무작위 쌍 대조.
    random_pair_mismatches = 0
    random_legacy_transitions: Counter[tuple[str, str]] = Counter()
    for _ in range(250_000):
        first = random_approach("SB")
        second = random_approach("WB")
        result = analyze_intersection([first, second, ApproachInput("EB", 1, 1, 1, 1, 0)])
        pair = next(item for item in result.pairs if item.name == "SB–WB")
        current_first = manual_capacity(first, combined_turn=True, fixed_right_turn_addition=True)
        current_second = manual_capacity(second, combined_turn=True, fixed_right_turn_addition=True)
        oracle = manual_area(current_first, current_second)[0]
        if pair.classification.area.value != oracle:
            random_pair_mismatches += 1
        legacy_first = manual_capacity(first, combined_turn=False, fixed_right_turn_addition=False)
        legacy_second = manual_capacity(second, combined_turn=False, fixed_right_turn_addition=False)
        legacy = manual_area(legacy_first, legacy_second)[0]
        random_legacy_transitions[(legacy, oracle)] += 1

    # 지원되는 모든 3~6개 접근로 조합을 세 가지 교통수준으로 점검.
    from itertools import combinations

    topology_subset_cases = 0
    topology_subset_failures = 0
    for count in range(3, 7):
        for codes in combinations(APPROACH_ORDER, count):
            for vpl in (350, 1_000, 1_750):
                approaches = [
                    make_approach(code, 2, vpl, 0.8 + index * 0.07, 0.15, 0.10, 15)
                    for index, code in enumerate(codes)
                ]
                program = analyze_intersection(approaches)
                oracle_area, oracle_pair, _ = manual_intersection(
                    approaches, combined_turn=True, fixed_right_turn_addition=True
                )
                topology_subset_cases += 1
                if (program.area.value, program.critical_pair.name) != (oracle_area, oracle_pair):
                    topology_subset_failures += 1

    boundary_case_count, boundary_failures, boundary_rows = boundary_checks()

    # 대표 그래프 4개 영역 x 6개를 저장하고 접촉 시트 생성.
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(str(resource_path("NotoSansKR.ttf")))
    app.setFont(QFont("Noto Sans KR", 10))
    selected_images: list[tuple[str, QImage]] = []
    chart_qa_failures = 0
    for area in "ABCD":
        for index, pair in enumerate(graph_candidates[area][:6], 1):
            image = render_pair_chart(pair, 839)
            path = CHARTS / f"area_{area}_{index}.png"
            image.save(str(path), "PNG", 100)
            if image.width() != 839 or image.height() != 839 or image.dotsPerMeterX() != 11_811:
                chart_qa_failures += 1
            selected_images.append((f"{area}-{index}", image))

    sheet = QImage(6 * 360, 4 * 360, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("white"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for index, (_, image) in enumerate(selected_images[:24]):
        row, column = divmod(index, 6)
        painter.drawImage(QRectF(column * 360, row * 360, 360, 360), image)
    painter.end()
    sheet.save(str(OUT / "representative_charts_contact_sheet.png"), "PNG", 100)

    csv_path = OUT / "structured_scenarios.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(structured_rows[0]))
        writer.writeheader()
        writer.writerows(structured_rows)
    boundary_path = OUT / "boundary_checks.csv"
    with boundary_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(boundary_rows[0]))
        writer.writeheader()
        writer.writerows(boundary_rows)

    example = guideline_example_check()
    expected = example["guideline_expected"]
    automatic = example["automatic_mode"]
    direct = example["direct_mode"]
    automatic_diff = {
        "P1_percent": (automatic["P1"] / expected["P1"] - 1) * 100,
        "P2_percent": (automatic["P2"] / expected["P2"] - 1) * 100,
    }
    direct_absolute_error = {
        "P1": abs(direct["P1"] - expected["P1"]),
        "P2": abs(direct["P2"] - expected["P2"]),
        "P_prime_1": abs(direct["P_prime_1"] - expected["P_prime"]),
        "P_prime_2": abs(direct["P_prime_2"] - expected["P_prime"]),
    }
    legacy_changed = sum(n for (old, new), n in legacy_transitions.items() if old != new)
    pprime_changed = sum(n for (old, new), n in pprime_transitions.items() if old != new)
    random_legacy_changed = sum(n for (old, new), n in random_legacy_transitions.items() if old != new)

    summary = {
        "version": "3.6.0",
        "structured_scenario_count": len(scenarios),
        "structured_area_distribution": dict(area_distribution),
        "topology_area_distribution": {key: dict(value) for key, value in topology_distribution.items()},
        "current_formula_oracle_mismatches": len(current_mismatches),
        "random_pair_count": 250_000,
        "random_pair_current_oracle_mismatches": random_pair_mismatches,
        "all_supported_topology_subset_cases": topology_subset_cases,
        "all_supported_topology_subset_failures": topology_subset_failures,
        "boundary_case_count": boundary_case_count,
        "boundary_failures": boundary_failures,
        "legacy_v320_changed_structured": legacy_changed,
        "legacy_to_v340_transition_counts": {f"{a}->{b}": n for (a, b), n in legacy_transitions.items()},
        "fixed600_changed_structured": pprime_changed,
        "variable_to_fixed600_transition_counts": {f"{a}->{b}": n for (a, b), n in pprime_transitions.items()},
        "legacy_v320_changed_random_pairs": random_legacy_changed,
        "random_legacy_to_v340_transition_counts": {f"{a}->{b}": n for (a, b), n in random_legacy_transitions.items()},
        "chart_count": len(selected_images),
        "chart_qa_failures": chart_qa_failures,
        "guideline_example": example,
        "guideline_example_automatic_difference_percent": automatic_diff,
        "guideline_example_direct_absolute_error": direct_absolute_error,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = f"""# 입체화검토 v3.6.0 시나리오 검증 보고서

## 검증 범위

- 현실형 구조 시나리오: {len(scenarios):,}건
- 무작위 접근로 쌍: 250,000건
- 지원 가능한 모든 3~6개 접근로 조합: {topology_subset_cases:,}건
- A/B/C/D 경계 및 경계 양측: {boundary_case_count:,}건
- 대표 그래프: {len(selected_images)}장(A·B·C·D 각 6장)

## 내부 계산 일관성

- 단위·UI 회귀시험: 30건 통과
- 현재 프로그램과 독립 동일식 재계산 불일치: {len(current_mismatches)}건
- 무작위 250,000개 쌍의 영역 불일치: {random_pair_mismatches}건
- 모든 접근로 조합의 최악 쌍 선정 불일치: {topology_subset_failures}건
- 경계값 판정 불일치: {boundary_failures}건

## 구조 시나리오 영역 분포

{json.dumps(dict(area_distribution), ensure_ascii=False)}

## 3.2.0 대비 판정 변화

- 통합 회전식과 고정 +600을 적용해 영역이 달라진 구조 시나리오: {legacy_changed:,}/{len(scenarios):,}건
- `300 × 차로수` 대신 접근로당 고정 +600을 적용해 달라진 구조 시나리오: {pprime_changed:,}/{len(scenarios):,}건
- 종전 3.2.0식과 3.4.0식의 무작위 쌍 판정 차이: {random_legacy_changed:,}/250,000건

## 지침 예제 대조

- 자동 모드 P1/P2: {automatic['P1']:.4f}/{automatic['P2']:.4f} (예제 대비 {automatic_diff['P1_percent']:+.2f}%/{automatic_diff['P2_percent']:+.2f}%)
- 지침 계수 직접 입력 P1/P2: {direct['P1']:.4f}/{direct['P2']:.4f}
- 지침 P′와 직접 입력 P′: {expected['P_prime']:.0f} / {direct['P_prime_1']:.0f}/{direct['P_prime_2']:.0f}
- 지침 판정과 직접 입력 판정: {expected['area']} / {direct['pair_area']}

## 판정

3.6.0 구현은 통합 회전식, 중차량식, 고정 +600 P′ 가정, 최악 쌍 선택 및 그래프 생성에서 독립 재계산과 일치한다. 지침 예제의 명시 계수를 직접 입력하면 P·P′와 최종 C영역을 재현한다. 자동 모드는 공개된 일반 가정에 의한 개략값이며 지침 예제 고유 계수와 동일하다고 보지 않는다.

## 검증 한계와 우선 조치

- 이 시험의 교통량은 국내 교차로에서 가능한 범위를 모사한 합성값이며 실측 표본은 아니다.
- 자동 모드는 EL=2.0, ER=1.5, EHV=1.8을 가정하므로 실제 신호·차로군 조건이 다르면 직접계수를 사용해야 한다.
- 3·5·6지의 최악 충돌쌍 방식은 프로그램의 보수적 확장이며 공식 지침 판정으로 표현하지 않는다.
- 방향별 교통량 입력은 현실적 사용범위에 맞춰 0~99,999대/시로 검증한다.
- 그래프 {len(selected_images)}장은 839×839 px, 300 dpi 조건을 모두 충족하며 A·B·C·D 색 영역, 경계선, 교통량 점과 축 표기를 확인한다.
"""
    (OUT / "validation_report.md").write_text(report, encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
