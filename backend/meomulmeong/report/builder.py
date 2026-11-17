"""최종 제안서: 세 단계 결과를 근거표·SQL·한계와 함께 한 문서(HTML)로 묶어요."""

from __future__ import annotations

import base64
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from .. import fmt
from ..maps import MapsUnavailable, NaverMaps
from ..schemas import STAGE_TITLE, Answer, EvidenceTable, MapSpec
from ..tools.base import ToolContext
from .naver_figure import course_routes, map_figure
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


def _map_html(m: MapSpec, maps: NaverMaps | None) -> str:
    """지도 하나: 네이버 바탕 지도 위에 점·선 (키가 있고 인터넷이 될 때), 아니면 SVG 점 지도."""
    if maps is not None:
        try:
            return map_figure(m, maps, course_routes(m, maps) if m.lines else None)
        except MapsUnavailable:
            pass
    return map_svg(m)


def _answer_view(a: Answer, maps: NaverMaps | None = None) -> dict[str, Any]:
    return {
        "stage": a.stage, "stage_title": STAGE_TITLE.get(a.stage or 0, ""), "headline": a.headline,
        "explanation": a.explanation, "badges": [b for b in a.badges if b.tone != "data"], "notices": a.notices,
        "suggestions": a.suggestions,
        "charts": [{"title": c.title, "svg": chart_svg(c), "note": c.note} for c in a.charts],
        "maps": [{"title": m.title, "svg": _map_html(m, maps), "note": m.note} for m in a.maps],
        "evidence": [table_view(e) for e in a.evidence], "limits": a.limits,
        "checks": [{"label": CHECK_LABEL.get(c.name, c.name), "passed": c.passed, "detail": c.detail}
                   for c in a.verification.checks],
        "fallback": a.verification.fallback,
    }


def _location_map(answers: list[Answer], ctx: ToolContext) -> tuple[str | None, str]:
    """제안서 첫 쪽의 위치 지도 (네이버 Static Map). 대상 읍면동은 주황 핀, 3단계 코스의 출발 거점은 번호예요.

    지도 키가 없거나 인터넷이 없으면 (None, '') 이고, 제안서는 지도 없이 만들어요. 그림은 문서 안에 넣어서
    파일 하나로 열리고 인쇄돼요.
    """
    maps = NaverMaps.from_settings(ctx.settings)
    target = next((ctx.refs.emds.get(a.query.place_key or "") for a in answers if a.query.place_kind == "emd"), None)
    if maps is None or target is None:
        return None, ""
    hubs = []
    for a in answers:
        for m in a.maps:
            if m.id != "s3_course_map":
                continue
            for line in m.lines:  # 선마다 첫 점이 출발 거점이에요 (화면의 코스 번호와 같은 순서)
                h = ctx.refs.hubs.get(line.keys[0]) if line.keys else None
                if h and h not in hubs:
                    hubs.append(h)
    markers = [{"lat": target.lat, "lon": target.lon, "kind": "pin", "color": "0xF08A12"}]
    markers += [{"lat": h.lat, "lon": h.lon, "kind": "dot", "color": "0x2B211B", "label": str(i)} for i, h in enumerate(hubs, 1)]
    try:
        png = maps.static_map(markers)
    except MapsUnavailable:
        return None, ""
    caption = f"주황 핀: {target.emd_nm}"
    if hubs:
        caption += " · 숫자: 3단계 코스의 출발 거점 (" + ", ".join(f"{i} {h.hub_nm}" for i, h in enumerate(hubs, 1)) + ")"
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), caption + " · 지도 © NAVER Corp."


def build_report(answers: list[Answer], out_dir: Path, ctx: ToolContext, filename: str | None = None) -> Path:
    """Stage 1~3 답을 받아 제안서 HTML 파일을 만들고 경로를 돌려줘요."""
    answers = [a for a in answers if a.ok]
    if not answers:
        raise ValueError("제안서에 넣을 결과가 없어요.")
    place = next((a.query.place_name for a in answers if a.query.place_name), "제주")
    env = Environment(loader=PackageLoader("meomulmeong.report", "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    by = {a.explained_by for a in answers}
    explained = "기본 설명 (AI 없이)" if by == {"template"} else f"{fmt.model_name(answers[0].llm_model or '')} + 검증기"
    location_map, location_caption = _location_map(answers, ctx)
    html = env.get_template("proposal.html.j2").render(
        place=place, issued=datetime.now().strftime("%Y-%m-%d %H:%M"), explained=explained,
        location_map=location_map, location_caption=location_caption,
        data_badge=ctx.wh.data_badge, sample=ctx.wh.data_badge == "샘플 데이터", center=ctx.wh.data_mode == "center",
        answers=[_answer_view(a, NaverMaps.from_settings(ctx.settings)) for a in sorted(answers, key=lambda a: a.stage or 9)])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_place = re.sub(r"[^0-9A-Za-z가-힣]+", "_", place)
    path = out_dir / (filename or f"머물멍_제안서_{safe_place}_{datetime.now():%Y%m%d_%H%M%S}.html")
    path.write_text(html, encoding="utf-8")
    return path
