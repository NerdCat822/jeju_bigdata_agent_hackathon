"""출력 도구: 반출 규칙 검사(export_check). 차트·지도 사양은 분석 도구가 직접 만들어요 (schemas.ChartSpec/MapSpec)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .. import fmt
from ..schemas import Check, EvidenceTable


@lru_cache(maxsize=4)
def load_export_rules(config_dir: str) -> dict[str, Any]:
    path = Path(config_dir) / "export_rules.yaml"
    if not path.exists():
        return {"min_cell": 5, "max_rows": 200, "count_columns": [], "forbidden_columns": [], "grades": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def export_check(evidence: list[EvidenceTable], rules: dict[str, Any], data_mode: str) -> tuple[Check, list[EvidenceTable]]:
    """근거표가 반출 규칙을 지키는지 검사하고, 내보내도 되는 표(가림 처리 후)를 돌려줘요.

    - 식별 컬럼(사업자번호·기업명·태그번호 등)은 어떤 모드에서도 금지
    - '집계만' 등급(센터 데이터)에서는 사람 수·건수 열의 작은 셀(min_cell 미만)을 가려요
    - 행 수는 max_rows 까지만
    """
    grade = (rules.get("grades") or {}).get(data_mode, "open")
    min_cell = int(rules.get("min_cell", 5))
    max_rows = int(rules.get("max_rows", 200))
    forbidden = [re.compile(p, re.I) for p in rules.get("forbidden_columns") or []]
    count_pats = [re.compile(p, re.I) for p in rules.get("count_columns") or []]
    count_words = ("이용자", "방문자", "건수", "명", "인구")
    problems: list[str] = []
    safe: list[EvidenceTable] = []
    masked = 0
    for ev in evidence:
        bad_cols = [c for c in ev.columns if any(p.search(c) for p in forbidden)]
        if bad_cols:
            problems.append(f"{ev.id}: 식별 컬럼 {bad_cols}")
            continue
        rows = [list(r) for r in ev.rows[:max_rows]]
        if grade == "aggregate_only":
            idx = [i for i, c in enumerate(ev.columns)
                   if any(p.search(c) for p in count_pats) or (any(w in c for w in count_words) and "율" not in c and "비" not in c)]
            for r in rows:
                for i in idx:
                    if i < len(r) and fmt.is_num(r[i]) and 0 < r[i] < min_cell:
                        r[i] = None
                        masked += 1
        safe.append(ev.model_copy(update={"rows": rows}))
    detail = f"등급 {grade}"
    if masked:
        detail += f", 작은 셀 {masked}개 가림"
    if problems:
        detail += "; " + "; ".join(problems)
    return Check(name="export", passed=not problems, detail=detail), safe


# --------------------------------------------------------------------------- 도구 등록 (기획서 3.4 '출력' 도구)
def _register() -> None:
    from pathlib import Path as _Path

    from ..schemas import Answer, ChartSpec, MapSpec, ToolResult
    from .base import ToolContext, tool

    @tool("make_chart", "출력", "차트 사양(ChartSpec)을 화면용 Plotly 그림과 제안서용 SVG로 바꿔요.")
    def make_chart(ctx: ToolContext, spec: ChartSpec) -> ToolResult:
        from ..report.svg import chart_svg

        return ToolResult(tool="make_chart", charts=[spec], data={"plotly": spec.to_plotly(), "svg": chart_svg(spec)})

    @tool("make_map", "출력", "지도 사양(MapSpec: 읍면동 유형, 거점, 코스)을 제안서용 SVG로 바꿔요.")
    def make_map(ctx: ToolContext, spec: MapSpec) -> ToolResult:
        from ..report.svg import map_svg

        return ToolResult(tool="make_map", maps=[spec], data={"svg": map_svg(spec)})

    @tool("build_report", "출력", "Stage 1~3 답을 근거표·SQL·한계와 함께 최종 제안서(HTML) 한 문서로 묶어요.")
    def build_report_tool(ctx: ToolContext, answers: list[Answer], out_dir: str | None = None) -> ToolResult:
        from ..report.builder import build_report

        path = build_report(answers, _Path(out_dir) if out_dir else ctx.settings.outputs_dir / "reports", ctx)
        return ToolResult(tool="build_report", data={"path": str(path)})

    @tool("export_check", "출력", "근거표가 반출 규칙(식별 컬럼 금지, 최소 셀 크기, 행 수)을 지키는지 검사해요.")
    def export_check_tool(ctx: ToolContext, evidence: list[EvidenceTable]) -> ToolResult:
        check, safe = export_check(evidence, load_export_rules(str(ctx.settings.config_dir)), ctx.wh.data_mode)
        return ToolResult(tool="export_check", ok=check.passed, message=check.detail, evidence=safe)


_register()
