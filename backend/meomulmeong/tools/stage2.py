"""Stage 2 「빈자리를 누가 채우나」 — 내국인/중국인·단체/개별·요일·국적 분석과 규칙 기반 제안."""

from __future__ import annotations

from datetime import date
from typing import Any

from .. import fmt
from ..data.periods import PeriodRequest, overlap
from ..schemas import TYPE_LABEL, ChartSpec, EvidenceTable, Fact, Series, Suggestion, ToolResult
from .base import ToolContext, sql_str, tool
from .shared import dow_profiles

CARD_CN = "card_cn_area_monthly"
SPEND = "spend_tour_type_monthly"
FV = "foreign_visitors_monthly"
ZONE = "card_zone_dow_monthly"

METRIC_LABEL = {
    "cn_growth": "중국인 {theme} 소비 증가율",
    "cn_share": "중국인 소비 중 {theme} 비중",
    "indiv_ratio_cn": "중국인 {theme} 개별여행 인당 배율",
    "indiv_ratio_kr": "내국인 {theme} 개별여행 인당 배율",
    "weekend_ratio_cn": "중국인 주말 소비비",
    "weekend_ratio_kr": "내국인 주말 소비비",
    "nat_growth_top": "{nationality} 방문자 성장률",
    "nat_share_top": "{nationality} 방문자 비중",
    "youth_resd_chg": "청년 거주 변화율",
    "youth_work_chg": "청년 근무 변화율",
    "visit_chg": "방문자 변화율",
    "youth_share": "청년 비중",
    "settle_ratio": "정주비",
    "foreign_resd_chg": "외국인 장기체류 거주 변화율",
}
_RATIO_METRICS = {"indiv_ratio_cn", "indiv_ratio_kr", "weekend_ratio_cn", "weekend_ratio_kr"}


def _req(last_n_months: int | None, year: int | None) -> PeriodRequest:
    return PeriodRequest(last_n_months=last_n_months, year=year)


def resolve_area(ctx: ToolContext, place_kind: str | None, place_key: str | None) -> dict[str, Any]:
    """장소를 카드 데이터의 단위(시군구 × 도심/읍면, 지구)로 올려요."""
    refs = ctx.refs
    if place_kind == "emd" and place_key in refs.emds:
        e = refs.emds[place_key]
        zones = refs.card_zones_for(e.emd_cd)
        return {"name": e.emd_nm, "city": e.city, "area_type": e.area_type, "zones": [z for z, _ in zones],
                "zone_direct": bool(zones and zones[0][1]), "emd_cds": [e.emd_cd],
                "area_label": f"{e.city} {'읍면' if e.area_type == '읍면' else '도심'} 지역"}
    if place_kind == "zone" and place_key in refs.zones:
        emds = refs.zone_emds(place_key)
        if emds:
            e = refs.emds[emds[0]]
            return {"name": place_key, "city": e.city, "area_type": e.area_type, "zones": [place_key],
                    "zone_direct": True, "emd_cds": emds,
                    "area_label": f"{e.city} {'읍면' if e.area_type == '읍면' else '도심'} 지역"}
        return {"name": place_key, "city": None, "area_type": None, "zones": [place_key], "zone_direct": True,
                "emd_cds": [], "area_label": "제주 전체"}
    if place_kind == "city" and place_key:
        zones = [z for z in refs.zones if z.startswith(place_key)]
        return {"name": place_key, "city": place_key, "area_type": None, "zones": zones, "zone_direct": True,
                "emd_cds": [e.emd_cd for e in refs.emds.values() if e.city == place_key], "area_label": place_key}
    return {"name": "제주 전체", "city": None, "area_type": None, "zones": list(refs.zones), "zone_direct": True,
            "emd_cds": [], "area_label": "제주 전체"}


def _span(p) -> tuple[date, date]:
    return (p.p1_start, p.p1_end)


# --------------------------------------------------------------------------- s2_shift
@tool("s2_shift", "Stage 2", "빈자리를 채우는 소비 분석: 중국인 테마별 소비 증가, 단체/개별 인당 배율, 요일 피크, 성장 국적.")
def s2_shift(ctx: ToolContext, place_kind: str | None, place_key: str | None, theme: str | None = None,
             last_n_months: int | None = None, year: int | None = None) -> ToolResult:
    area = resolve_area(ctx, place_kind, place_key)
    req = _req(last_n_months, year)
    cfg2 = ctx.config.stage2
    facts: list[Fact] = [Fact(key="place", label="장소", value=area["name"], unit="text", text=area["name"]),
                         Fact(key="area", label="카드 분석 단위", value=area["area_label"], unit="text", text=area["area_label"])]
    evidence: list[EvidenceTable] = []
    charts: list[ChartSpec] = []
    limits: list[str] = []
    tables: list[str] = []
    metrics: dict[str, Any] = {}
    spans: dict[str, tuple[date, date]] = {}
    periods: list[str] = []

    def add_limits(tbls: list[str]) -> None:
        for lim in ctx.limits(tbls):
            if lim not in limits:
                limits.append(lim)

    def note_period(title: str, p) -> None:
        """기간을 기본(최근 12개월 vs 직전)과 다르게 잡았으면 어떤 자료가 왜 그런지 알려요."""
        if p.note:
            msg = f"{title}: {p.note}"
            if msg not in limits:
                limits.append(msg)

    # ---- (a) 중국인 테마별 소비
    if ctx.wh.has(CARD_CN):
        p = ctx.period(CARD_CN, req)
        where = []
        if area["city"]:
            where.append(f"city = {sql_str(area['city'])}")
        if area["area_type"]:
            where.append(f"area_type = {sql_str(area['area_type'])}")
        w = (" AND ".join(where)) or "TRUE"

        def theme_sql(cond: str) -> str:
            return f"""
SELECT theme,
       SUM(use_amt) FILTER (WHERE {p.sql_p1()}) AS amt_p1,
       SUM(use_amt) FILTER (WHERE {p.sql_p0()}) AS amt_p0
FROM card_cn_area_monthly
WHERE {cond}
GROUP BY theme
ORDER BY amt_p1 DESC NULLS LAST"""

        res = ctx.wh.query(theme_sql(w))
        unit = "시군구 × 도심/읍면 × 테마"
        if w != "TRUE" and not any(a1 for _t, a1, _a0 in res.rows):
            # 허브의 '업종별 성별 카드 이용 정보'는 제주 전체 단위예요. 이 동네가 속한 지역의 값이 없으면 제주 전체 값을 써요
            limits.append(f"중국인 카드 자료가 제주 전체 단위라 {area['area_label']} 대신 제주 전체 값을 썼어요.")
            area["area_label"], unit = "제주 전체", "제주 전체 × 테마"
            facts[1] = Fact(key="area", label="카드 분석 단위", value="제주 전체", unit="text", text="제주 전체")
            res = ctx.wh.query(theme_sql("TRUE"))
        rows = [(t, float(a1 or 0), float(a0) if a0 else None) for t, a1, a0 in res.rows]
        tot1 = sum(r[1] for r in rows)
        tot0 = sum(r[2] for r in rows if r[2]) if p.comparable else None
        growth, share = {}, {}
        small: list[str] = []  # 직전 기간 비중이 아주 작은 테마는 증가율을 빼요 (작은 금액의 변화가 큰 증가율로 보여서예요)
        for t, a1, a0 in rows:
            base_ok = bool(a0) and (not tot0 or a0 / tot0 >= cfg2.min_share_for_theme_growth)
            growth[t] = (a1 / a0 - 1) if base_ok else None
            if a0 and not base_ok:
                small.append(t)
            share[t] = (a1 / tot1) if tot1 else None
        growth["전체"] = (tot1 / tot0 - 1) if tot0 else None
        if small:
            limits.append(f"중국인 {'·'.join(small)} 소비는 직전 기간 비중이 {cfg2.min_share_for_theme_growth:.0%}보다 작아 "
                          "증가율을 빼고 금액만 보여 줘요 (작은 금액의 변화가 큰 증가율로 보여서예요).")
        metrics["cn_growth"], metrics["cn_share"] = growth, share
        spans["cn_growth"] = spans["cn_share"] = _span(p)
        periods.append(p.label)
        evidence.append(EvidenceTable(
            id="s2_cn_theme", title=f"{area['area_label']} 중국인 테마별 카드 이용금액",
            columns=["테마", "최근(P1) 이용금액", "직전(P0) 이용금액", "증가율", "비중(P1)"],
            rows=[[t, round(a1), round(a0) if a0 else None, _r4(growth[t]), _r4(share[t])] for t, a1, a0 in rows]
                 + [["전체", round(tot1), round(tot0) if tot0 else None, _r4(growth["전체"]), 1.0]],
            formats={"최근(P1) 이용금액": "won", "직전(P0) 이용금액": "won", "증가율": "pct", "비중(P1)": "share"},
            sql=res.sql, tables=[CARD_CN], period=p.label,
            note=f"중국인 소비 증가율 = 이용금액 P1 ÷ P0 − 1 ({unit})"))
        for t, _a1, _a0 in rows:
            if growth[t] is not None:
                facts.append(Fact(key=f"cn_growth:{t}", label=f"중국인 {t} 소비 증가율", value=growth[t], unit="pct",
                                  text=fmt.pct(growth[t]), period=p.label))
            if share[t] is not None:
                facts.append(Fact(key=f"cn_share:{t}", label=f"중국인 소비 중 {t} 비중", value=share[t], unit="pct",
                                  text=fmt.pct(share[t], signed=False), period=p.p1_label))
        if growth["전체"] is not None:
            facts.append(Fact(key="cn_growth:전체", label="중국인 전체 소비 증가율", value=growth["전체"], unit="pct",
                              text=fmt.pct(growth["전체"]), period=p.label))
        ordered = [r for r in rows if growth[r[0]] is not None]
        if ordered:
            names = [r[0] for r in ordered]
            focus = theme if theme in names else max(names, key=lambda t: growth[t])
            charts.append(ChartSpec(
                id="s2_cn_growth", kind="bar", title=f"{area['area_label']} 중국인 테마별 소비 증가율",
                x=names, series=[Series(name="증가율", y=[_r4(growth[t]) for t in names])],
                y_title="증가율", y_format="pct", note=p.label, highlight=focus))
        note_period("중국인 카드", p)
        tables.append(CARD_CN)
        add_limits([CARD_CN])
    else:
        limits.append("중국인 카드 자료가 없어 테마별 소비는 보지 못했어요.")

    # ---- (b) 단체/개별 인당 배율
    if ctx.wh.has(SPEND):
        p = ctx.period(SPEND, req)
        sql = f"""
SELECT user_type, market, theme,
       AVG(amt_per_person) FILTER (WHERE tour_type = '개별') AS indiv,
       AVG(amt_per_person) FILTER (WHERE tour_type = '단체') AS grp
FROM spend_tour_type_monthly
WHERE {p.sql_p1()}
GROUP BY user_type, market, theme
ORDER BY user_type, market"""
        res = ctx.wh.query(sql)
        by: dict[str, dict[str, list[float]]] = {"중국인": {}, "내국인": {}}
        rows = []
        for user_type, market, th, indiv, grp in res.rows:
            r = (indiv / grp) if (indiv and grp) else None
            rows.append([user_type, market, th, round(indiv) if indiv else None, round(grp) if grp else None, _r4(r)])
            if r is not None and user_type in by:
                by[user_type].setdefault(th, []).append(r)
        for ut, key in (("중국인", "indiv_ratio_cn"), ("내국인", "indiv_ratio_kr")):
            metrics[key] = {t: sum(v) / len(v) for t, v in by[ut].items()}
            spans[key] = _span(p)
            for t, v in metrics[key].items():
                facts.append(Fact(key=f"{key}:{t}", label=f"{ut} {t} 개별여행 인당 배율", value=v, unit="ratio",
                                  text=fmt.ratio(v), period=p.p1_label))
        periods.append(p.p1_label)
        evidence.append(EvidenceTable(
            id="s2_indiv", title="단체/개별 관광객 인당 이용금액 (제주 전체)",
            columns=["관광객구분", "업종", "테마", "개별 인당", "단체 인당", "개별여행 인당 배율"], rows=rows,
            formats={"개별 인당": "won", "단체 인당": "won", "개별여행 인당 배율": "num2"},
            sql=res.sql, tables=[SPEND], period=p.p1_label,
            note="개별여행 인당 배율 = 개별 인당이용금액 ÷ 단체 인당이용금액. 테마 값은 속한 업종 배율의 평균이에요."))
        note_period("단체/개별 소비", p)
        tables.append(SPEND)
        add_limits([SPEND])

    # ---- (c) 요일 프로필
    if area["zones"] and ctx.wh.has(ZONE):
        p = ctx.period(ZONE, req)
        profiles, ev = dow_profiles(ctx, area["zones"], p)
        for ut, key in (("중국인", "cn"), ("내국인", "kr")):
            ps = [x for x in profiles if x.user_type == ut and x.weekend_ratio is not None]
            if not ps:
                continue
            val = sum(x.weekend_ratio for x in ps) / len(ps)
            total = {d: sum(x.per_day.get(d, 0.0) for x in ps) for d in ps[0].per_day}
            peak = max(total, key=total.get)
            metrics[f"weekend_ratio_{key}"], metrics[f"peak_dow_{key}"] = val, peak
            spans[f"weekend_ratio_{key}"] = _span(p)
            zl = fmt.join_names([x.zone for x in ps])
            facts += [
                Fact(key=f"weekend_ratio_{key}", label=f"{ut} 주말 소비비 (주말 하루 소비 ÷ 평일 하루 소비, {zl})", value=val, unit="ratio",
                     text=fmt.ratio(val), period=p.p1_label, flag=None if area["zone_direct"] else "proxy_zone"),
                Fact(key=f"peak_dow_{key}", label=f"{ut} 소비 피크 요일", value=peak, unit="text", text=f"{peak}요일",
                     period=p.p1_label),
            ]
        if ev:
            evidence.append(ev)
            periods.append(p.p1_label)
            tables.append(ZONE)
            add_limits([ZONE])
            note_period("요일별 카드", p)
        if not area["zone_direct"]:
            limits.append("이 읍면동은 카드 지구에 직접 속하지 않아 관광지 지구 값을 참고로 보여 줘요.")

    # ---- (d) 국적 성장률
    if ctx.wh.has(FV):
        p = ctx.period(FV, req)
        sql = f"""
SELECT nationality,
       SUM(visitors) FILTER (WHERE {p.sql_p1()}) AS v_p1,
       SUM(visitors) FILTER (WHERE {p.sql_p0()}) AS v_p0
FROM foreign_visitors_monthly
GROUP BY nationality
ORDER BY v_p1 DESC NULLS LAST"""
        res = ctx.wh.query(sql)
        rows = [(n, float(v1 or 0), float(v0) if v0 else None) for n, v1, v0 in res.rows]
        tot = sum(r[1] for r in rows)
        table_rows, cand = [], []
        for n, v1, v0 in rows:
            g = (v1 / v0 - 1) if v0 else None
            s = (v1 / tot) if tot else None
            table_rows.append([n, round(v1), round(v0) if v0 else None, _r4(g), _r4(s)])
            if g is not None and s is not None and s >= cfg2.min_share_for_growth:
                cand.append((g, n, s))
        evidence.append(EvidenceTable(
            id="s2_nationality", title="국적별 외국인 방문자와 성장률 (제주 전체)",
            columns=["국적", "최근(P1) 방문자", "직전(P0) 방문자", "성장률", "비중(P1)"], rows=table_rows,
            formats={"최근(P1) 방문자": "int", "직전(P0) 방문자": "int", "성장률": "pct", "비중(P1)": "share"},
            sql=res.sql, tables=[FV], period=p.label,
            note=f"국적 성장률 = 방문자 P1 ÷ P0 − 1. 성장 국적은 비중 {cfg2.min_share_for_growth:.0%} 이상에서 골라요."))
        if cand:
            g, n, s = max(cand)
            metrics.update({"nat_growth_top": g, "nat_share_top": s, "nat_top": n})
            spans["nat_growth_top"] = spans["nat_share_top"] = _span(p)
            facts += [
                Fact(key="nat_top", label="가장 빠르게 늘어난 국적", value=n, unit="text", text=n, period=p.label),
                Fact(key="nat_growth_top", label=f"{n} 방문자 성장률", value=g, unit="pct", text=fmt.pct(g), period=p.label),
                Fact(key="nat_share_top", label=f"{n} 방문자 비중", value=s, unit="pct", text=fmt.pct(s, signed=False),
                     period=p.p1_label),
            ]
        periods.append(p.label)
        note_period("외국인관광객현황", p)
        tables.append(FV)
        add_limits([FV])

    if not tables:
        return ToolResult(tool="s2_shift", ok=False, message="카드·관광객 자료가 없어 Stage 2 분석을 할 수 없어요.")
    if theme and metrics.get("cn_growth", {}).get(theme) is not None:
        facts.append(Fact(key="focus_theme", label="질문한 테마", value=theme, unit="text", text=theme))
    return ToolResult(
        tool="s2_shift", facts=facts, evidence=evidence, charts=charts, limits=limits, tables=tables,
        period=" / ".join(dict.fromkeys(periods)),
        data={"area": area, "metrics": metrics, "theme": theme,
              "spans": {k: (v[0].isoformat(), v[1].isoformat()) for k, v in spans.items()}})


def _r4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


# --------------------------------------------------------------------------- s2_playbook
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b}
_SHARE_METRICS = {"cn_share", "nat_share_top", "youth_share", "settle_ratio"}


def _fmt_metric(metric: str, value: float) -> str:
    if metric in _RATIO_METRICS:
        return fmt.ratio(value)
    return fmt.pct(value, signed=metric not in _SHARE_METRICS)


def _fmt_threshold(metric: str, op: str, value: float) -> str:
    sym = {">=": "≥", "<=": "≤"}.get(op, op)
    return f"{sym} {_fmt_metric(metric, value)}"


def _evi(metric: str, theme: str | None, value: float, op: str, threshold: float, nationality: str | None) -> str:
    label = METRIC_LABEL.get(metric, metric).format(theme=theme or "", nationality=nationality or "")
    label = " ".join(label.split())
    return f"{label} {_fmt_metric(metric, value)} (기준 {_fmt_threshold(metric, op, threshold)})"


@tool("s2_playbook", "Stage 2", "설정 파일의 제안 규칙 12개를 지표에 적용해 근거가 붙은 제안 후보를 만들어요.")
def s2_playbook(ctx: ToolContext, metrics: dict[str, Any], stage1: dict[str, Any] | None = None,
                spans: dict[str, tuple[str, str]] | None = None) -> ToolResult:
    """metrics: s2_shift 가 만든 지표, stage1: Stage 1 산출물(type, 변화율 등)."""
    stage1 = stage1 or {}
    spans = spans or {}
    place_type = stage1.get("type")
    near = stage1.get("near_type") if place_type == "유지" else None
    gate_types = {place_type, near} - {None}  # 유지형은 가장 가까운 유형의 규칙도 참고로 적용해요
    values = dict(metrics)
    for k in ("youth_resd_chg", "youth_work_chg", "visit_chg", "youth_share", "settle_ratio", "foreign_resd_chg"):
        if stage1.get(k) is not None:
            values[k] = stage1[k]
    themes = [t for t in ctx.refs.themes if t != "기타"]
    nationality = values.get("nat_top")
    fired: list[Suggestion] = []
    rows: list[list[Any]] = []
    skipped_period: list[str] = []

    for rule in ctx.playbook:
        rid, name = rule["id"], rule.get("name", "")
        types = rule.get("types") or []
        tlabel = "·".join(types)
        if place_type and types and not (gate_types & set(types)):
            rows.append([rid, name, tlabel, "유형이 달라 건너뜀", "-"])
            continue
        conds = rule.get("when") or []
        uses_any = any(c.get("theme") == "any" for c in conds)
        best: tuple[float, str | None, list[tuple[str, str | None, float, str, float]]] | None = None
        first_fail: tuple[str, str | None, float, str, float] | None = None
        missing = False
        for th in (themes if uses_any else [None]):
            got: list[tuple[str, str | None, float, str, float]] = []
            status = "ok"
            for c in conds:
                metric = c["metric"]
                ctheme = th if c.get("theme") == "any" else c.get("theme")
                raw = values.get(metric)
                val = raw.get(ctheme) if isinstance(raw, dict) else raw
                if val is None:
                    status = "missing"
                    break
                got.append((metric, ctheme, float(val), c["op"], float(c["value"])))
                if not _OPS[c["op"]](val, c["value"]):
                    status = "fail"
                    break
            if status == "ok":
                score = got[0][2] if got else 0.0
                if best is None or score > best[0]:
                    best = (score, th, got)
            elif status == "missing":
                missing = True
            elif first_fail is None:
                first_fail = got[-1]
        if best is None:
            if first_fail is not None and not uses_any:
                rows.append([rid, name, tlabel, "미충족", _evi(*first_fail, nationality)])
            else:
                rows.append([rid, name, tlabel, "자료 없음" if (missing and first_fail is None) else "미충족", "-"])
            continue
        _, th, got = best
        # 기간 확인: 함께 쓰는 지표의 P1 기간이 겹쳐야 해요.
        used = [spans[m] for m, *_ in got if m in spans]
        common: tuple[date, date] | None = None
        if used:
            common = (date.fromisoformat(used[0][0]), date.fromisoformat(used[0][1]))
            for sp in used[1:]:
                if common is None:
                    break
                common = overlap(common, (date.fromisoformat(sp[0]), date.fromisoformat(sp[1])))
            if common is None:
                skipped_period.append(rid)
                rows.append([rid, name, tlabel, "기간이 겹치지 않아 함께 볼 수 없음", "-"])
                continue
        fill = {"theme": th or "", "nationality": nationality or ""}
        evid = [_evi(m, t, v, o, x, nationality) for m, t, v, o, x in got]
        keys = [f"{m}:{t}" if t else m for m, t, *_ in got]
        target = rule.get("target")
        fired.append(Suggestion(rule_id=rid, name=name, text=str(rule["suggest"]).format(**fill),
                                target=str(target).format(**fill) if target else None,
                                evidence_keys=keys, evidence_text=evid))
        rows.append([rid, name, tlabel, "충족", "; ".join(evid)])

    shown = fired[: ctx.config.stage2.max_suggestions]
    target = next((s.target for s in shown if s.target), None)
    facts = [Fact(key="n_rules", label="검토한 제안 규칙 수", value=len(ctx.playbook), unit="count", text=f"{len(ctx.playbook)}개"),
             Fact(key="n_fired", label="조건을 충족한 규칙 수", value=len(fired), unit="count", text=f"{len(fired)}개")]
    if place_type:
        facts.append(Fact(key="type", label="읍면동 유형", value=place_type, unit="text",
                          text=f"{place_type} {TYPE_LABEL[place_type]}" if place_type != "유지" else TYPE_LABEL[place_type]))
    if target:
        facts.append(Fact(key="target", label="타깃 관광객", value=target, unit="text", text=target))
    limits = []
    if skipped_period:
        limits.append(f"규칙 {', '.join(skipped_period)}은(는) 지표의 기간이 겹치지 않아 적용하지 않았어요.")
    if not place_type:
        limits.append("읍면동 유형이 없어 유형 조건 없이 규칙을 적용했어요.")
    elif near:
        limits.append(f"유지형이라 가장 가까운 유형({near} {TYPE_LABEL[near]})의 규칙을 참고로 적용했어요.")
        facts.append(Fact(key="near_type", label="가장 가까운 유형(참고)", value=near, unit="text", text=f"{near} {TYPE_LABEL[near]}"))
    ev = EvidenceTable(
        id="s2_rules", title="제안 규칙 적용 결과",
        columns=["규칙 ID", "규칙", "적용 유형", "결과", "근거 지표"], rows=rows,
        note="규칙은 config/playbook.yaml 에서 관리해요. 제안마다 규칙 ID와 근거 지표를 함께 보여 줘요.")
    group = "개별" if target and "개별" in target else ("단체" if target and "단체" in target else None)
    return ToolResult(tool="s2_playbook", facts=facts, evidence=[ev], suggestions=shown, limits=limits,
                      data={"target": target, "fired": [s.rule_id for s in fired], "group": group})
