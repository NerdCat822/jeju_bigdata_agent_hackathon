"""최종 제안서: 세 단계 결과를 근거표·SQL·한계와 함께 한 문서(HTML)로 묶어요."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from .. import fmt
from ..schemas import STAGE_TITLE, Answer, EvidenceTable
from ..tools.base import ToolContext
from .svg import chart_svg, map_svg

CHECK_LABEL = {"numbers": "숫자 대조", "pairing": "숫자-지표 짝", "fidelity": "초안 충실도", "causal": "인과 표현 가드",
               "prediction": "예측·추측 가드", "references": "참조 대조", "suggestions": "제안 근거",
               "assumption": "가정치 표시", "periods": "기간 확인", "export": "반출 게이트"}
MAX_ROWS = 45


def format_cell(v: Any, kind: str | None) -> str:
    if v is None:
        return "-"
    if not fmt.is_num(v):
        return str(v)
    if kind == "pct":
        return fmt.pct(v)
    if kind == "share":  # 비중·구성비는 부호 없이
        return fmt.pct(v, signed=False)
    if kind == "int":
        return f"{round(v):,}"
    if kind == "num1":
        return f"{v:,.1f}"
    if kind == "num2":
        return f"{v:,.2f}"
    if kind == "won":  # 표가 넓어지지 않게 억·만 단위로
        a = abs(v)
        return f"{v / 1e8:,.2f}억" if a >= 1e8 else (f"{v / 1e4:,.0f}만" if a >= 1e4 else f"{round(v):,}")
    return f"{v:,}" if isinstance(v, int) else f"{v:,.2f}"


def table_view(e: EvidenceTable) -> dict[str, Any]:
    """근거표를 화면용으로: 값은 표기 문자열로, 글자 열은 왼쪽 정렬·줄바꿈, 숫자 열은 오른쪽 정렬."""
    shown = e.rows[:MAX_ROWS]
    text_col = [not any(fmt.is_num(r[i]) for r in shown if i < len(r)) for i in range(len(e.columns))]
    rows = [[{"v": format_cell(v, e.formats.get(c)), "t": text_col[i]} for i, (c, v) in enumerate(zip(e.columns, r, strict=False))]
            for r in shown]
    cols = [{"v": c + ("(원)" if e.formats.get(c) == "won" else ""), "t": text_col[i]} for i, c in enumerate(e.columns)]
    return {"title": e.title, "columns": cols, "rows": rows, "period": e.period, "note": e.note, "sql": e.sql,
            "truncated": len(e.rows) > MAX_ROWS}


def _answer_view(a: Answer) -> dict[str, Any]:
    return {
        "stage": a.stage, "stage_title": STAGE_TITLE.get(a.stage or 0, ""), "headline": a.headline,
        "explanation": a.explanation, "badges": [b for b in a.badges if b.tone != "data"], "notices": a.notices,
        "suggestions": a.suggestions,
        "charts": [{"title": c.title, "svg": chart_svg(c), "note": c.note} for c in a.charts],
        "maps": [{"title": m.title, "svg": map_svg(m), "note": m.note} for m in a.maps],
        "evidence": [table_view(e) for e in a.evidence], "limits": a.limits,
        "checks": [{"label": CHECK_LABEL.get(c.name, c.name), "passed": c.passed, "detail": c.detail}
                   for c in a.verification.checks],
        "fallback": a.verification.fallback,
    }


def build_report(answers: list[Answer], out_dir: Path, ctx: ToolContext, filename: str | None = None) -> Path:
    """Stage 1~3 답을 받아 제안서 HTML 파일을 만들고 경로를 돌려줘요."""
    answers = [a for a in answers if a.ok]
    if not answers:
        raise ValueError("제안서에 넣을 결과가 없어요.")
    place = next((a.query.place_name for a in answers if a.query.place_name), "제주")
    env = Environment(loader=PackageLoader("meomulmeong.report", "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    by = {a.explained_by for a in answers}
    explained = "템플릿" if by == {"template"} else f"LLM({answers[0].llm_model}) + 검증기"
    html = env.get_template("proposal.html.j2").render(
        place=place, issued=datetime.now().strftime("%Y-%m-%d %H:%M"), explained=explained,
        data_badge=ctx.wh.data_badge, sample=ctx.wh.data_badge == "샘플 데이터", center=ctx.wh.data_mode == "center",
        answers=[_answer_view(a) for a in sorted(answers, key=lambda a: a.stage or 9)])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_place = re.sub(r"[^0-9A-Za-z가-힣]+", "_", place)
    path = out_dir / (filename or f"머물멍_제안서_{safe_place}_{datetime.now():%Y%m%d_%H%M%S}.html")
    path.write_text(html, encoding="utf-8")
    return path
