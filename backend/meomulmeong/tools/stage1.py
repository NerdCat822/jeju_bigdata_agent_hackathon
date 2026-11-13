"""Stage 1 「청년이 머무는 동네」 — 청년 인구 추이, 유형 분류·추천 순위, 유사 읍면."""

from __future__ import annotations

import math
from typing import Any

from .. import fmt
from ..data.periods import PeriodPair, PeriodRequest
from ..schemas import (
    TYPE_LABEL,
    TYPE_MEANING,
    Badge,
    ChartSpec,
    EvidenceTable,
    Fact,
    MapPoint,
    MapSpec,
    Series,
    ToolResult,
)
from .base import ToolContext, sql_in, sql_str, tool
from .shared import dow_profiles

POP = "pop_kor_emd_daily"
POP_FOR = "pop_for_long_emd_daily"
TYPE_ORDER = ["A", "B", "C", "D", "유지"]


def classify_type(resd: float | None, work: float | None, visit: float | None, tau: float) -> str | None:
    """읍면동 유형. 위에서부터 먼저 맞는 유형을 적용해요 (기획서 4.4)."""
    if resd is None or work is None or visit is None:
        return None
    if resd >= tau and work >= 0:
        return "A"
    if work >= tau:
        return "B"
    if resd <= -tau and visit >= 0:
        return "C"
    if resd <= -tau and visit < 0:
        return "D"
    return "유지"


def nearest_type(resd: float, work: float, visit: float, tau: float) -> str:
    """유지형일 때 참고로 보여 줄 가장 가까운 유형 (조건까지 모자란 정도의 합이 가장 작은 유형)."""
    gap = {
        "A": max(0.0, tau - resd) + max(0.0, -work),
        "B": max(0.0, tau - work),
        "C": max(0.0, resd + tau) + max(0.0, -visit),
        "D": max(0.0, resd + tau) + max(0.0, visit),
    }
    return min(gap, key=lambda k: (gap[k], k))


def _req(last_n_months: int | None, year: int | None) -> PeriodRequest:
    return PeriodRequest(last_n_months=last_n_months, year=year)


def metrics_all(ctx: ToolContext, ages: list[int], request: PeriodRequest) -> tuple[list[dict[str, Any]], PeriodPair, str]:
    """43개 읍면동의 Stage 1 지표를 한 번에 계산해요 (요청 안에서 캐시)."""
    key = f"s1:{sorted(ages)}:{request}"
    if key in ctx.cache:
        return ctx.cache[key]
    a = ctx.config.analysis
    period = ctx.period(POP, request)
    p1, p0 = period.sql_p1(), period.sql_p0()
    age_in = sql_in(sorted(ages))
    sql = f"""
WITH m AS (
  SELECT month, emd_cd, MAX(n_days) AS n_days,
         SUM(resd_sum) FILTER (WHERE age_band IN ({age_in})) AS resd_y,
         SUM(work_sum) FILTER (WHERE age_band IN ({age_in})) AS work_y,
         SUM(resd_sum) AS resd_all, SUM(work_sum) AS work_all, SUM(visit_sum) AS visit_all
  FROM m_pop_kor_emd_month
  GROUP BY month, emd_cd
  HAVING MAX(n_days) >= {a.min_month_days}
),
p AS (
  SELECT emd_cd,
         SUM(resd_y)    FILTER (WHERE {p1}) / SUM(n_days) FILTER (WHERE {p1}) AS resd_y_p1,
         SUM(resd_y)    FILTER (WHERE {p0}) / SUM(n_days) FILTER (WHERE {p0}) AS resd_y_p0,
         SUM(work_y)    FILTER (WHERE {p1}) / SUM(n_days) FILTER (WHERE {p1}) AS work_y_p1,
         SUM(work_y)    FILTER (WHERE {p0}) / SUM(n_days) FILTER (WHERE {p0}) AS work_y_p0,
         SUM(visit_all) FILTER (WHERE {p1}) / SUM(n_days) FILTER (WHERE {p1}) AS visit_p1,
         SUM(visit_all) FILTER (WHERE {p0}) / SUM(n_days) FILTER (WHERE {p0}) AS visit_p0,
         SUM(resd_all)  FILTER (WHERE {p1}) / SUM(n_days) FILTER (WHERE {p1}) AS resd_all_p1,
         SUM(work_all)  FILTER (WHERE {p1}) / SUM(n_days) FILTER (WHERE {p1}) AS work_all_p1
  FROM m
  GROUP BY emd_cd
)
SELECT e.emd_cd, e.emd_nm, e.city, e.emd_type, e.area_type,
       p.resd_y_p1, p.resd_y_p0, p.work_y_p1, p.work_y_p0, p.visit_p1, p.visit_p0,
       p.resd_y_p1 / NULLIF(p.resd_y_p0, 0) - 1 AS youth_resd_chg,
       p.work_y_p1 / NULLIF(p.work_y_p0, 0) - 1 AS youth_work_chg,
       p.visit_p1 / NULLIF(p.visit_p0, 0) - 1 AS visit_chg,
       p.resd_y_p1 / NULLIF(p.resd_all_p1, 0) AS youth_share,
       p.resd_all_p1 / NULLIF(p.resd_all_p1 + p.work_all_p1 + p.visit_p1, 0) AS settle_ratio
FROM p
JOIN ref_emd AS e USING (emd_cd)
ORDER BY e.emd_cd"""
    res = ctx.wh.query(sql)
    rows = res.dicts()
    for r in rows:
        r["type"] = classify_type(r["youth_resd_chg"], r["youth_work_chg"], r["visit_chg"], a.tau)
        r["near_type"] = (nearest_type(r["youth_resd_chg"], r["youth_work_chg"], r["visit_chg"], a.tau)
                          if r["type"] == "유지" else None)
        base = r["resd_y_p0"] if r["resd_y_p0"] is not None else r["resd_y_p1"]
        r["small"] = base is not None and base < a.min_base_pop
    ctx.cache[key] = (rows, period, res.sql)
    return ctx.cache[key]


def _row_of(rows: list[dict[str, Any]], emd_cd: str) -> dict[str, Any] | None:
    return next((r for r in rows if r["emd_cd"] == emd_cd), None)


def _no_data(tool_name: str, table: str) -> ToolResult:
    return ToolResult(tool=tool_name, ok=False, message=f"'{table}' 자료가 없어 이 분석을 할 수 없어요.")


def _core_facts(row: dict[str, Any], period: PeriodPair, ages: list[int]) -> list[Fact]:
    lab = fmt.ages_label(ages)
    pl = period.label
    f = [
        Fact(key="place", label="장소", value=row["emd_nm"], unit="text", text=row["emd_nm"]),
        Fact(key="ages", label="연령", value=lab, unit="text", text=lab),
        Fact(key="period", label="비교 기간", value=pl, unit="text", text=pl),
        Fact(key="youth_resd_p1", label=f"{lab} 거주인구 일평균 (P1)", value=row["resd_y_p1"], unit="people",
             text=fmt.people(row["resd_y_p1"]), period=period.p1_label),
        Fact(key="youth_resd_p0", label=f"{lab} 거주인구 일평균 (P0)", value=row["resd_y_p0"], unit="people",
             text=fmt.people(row["resd_y_p0"]), period=period.p0_label),
        Fact(key="youth_resd_chg", label=f"{lab} 거주 변화율", value=row["youth_resd_chg"], unit="pct",
             text=fmt.pct(row["youth_resd_chg"]), period=pl),
        Fact(key="youth_work_p1", label=f"{lab} 근무인구 일평균 (P1)", value=row["work_y_p1"], unit="people",
             text=fmt.people(row["work_y_p1"]), period=period.p1_label),
        Fact(key="youth_work_chg", label=f"{lab} 근무 변화율", value=row["youth_work_chg"], unit="pct",
             text=fmt.pct(row["youth_work_chg"]), period=pl),
        Fact(key="visit_p1", label="방문자 일평균 (P1)", value=row["visit_p1"], unit="people",
             text=fmt.people(row["visit_p1"]), period=period.p1_label),
        Fact(key="visit_chg", label="방문자 변화율", value=row["visit_chg"], unit="pct",
             text=fmt.pct(row["visit_chg"]), period=pl),
        Fact(key="youth_share", label=f"{lab} 비중 (거주 기준)", value=row["youth_share"], unit="pct",
             text=fmt.pct(row["youth_share"], signed=False), period=period.p1_label),
        Fact(key="settle_ratio", label="정주비", value=row["settle_ratio"], unit="pct",
             text=fmt.pct(row["settle_ratio"], signed=False), period=period.p1_label),
    ]
    if row["small"]:
        f.append(Fact(key="small_sample", label="작은 표본", value="Y", unit="text", flag="small_sample",
                      text="기준 인구가 100명 미만이라 변화율이 크게 흔들릴 수 있어요"))
    return f


# --------------------------------------------------------------------------- s1_trend
@tool("s1_trend", "Stage 1", "읍면동 하나의 청년 거주·근무·방문 추이와 핵심 지표(변화율·청년 비중·정주비)를 계산해요.")
def s1_trend(ctx: ToolContext, emd_cd: str, ages: list[int] | None = None,
             last_n_months: int | None = None, year: int | None = None) -> ToolResult:
    if not ctx.wh.has(POP):
        return _no_data("s1_trend", POP)
    a = ctx.config.analysis
    ages = ages or a.youth_age_bands
    lab = fmt.ages_label(ages)
    rows, period, sql_all = metrics_all(ctx, ages, _req(last_n_months, year))
    row = _row_of(rows, emd_cd)
    if row is None or row["resd_y_p1"] is None:
        return ToolResult(tool="s1_trend", ok=False, message=f"{ctx.refs.emd_name(emd_cd)}의 유동인구 자료가 없어요.")
    start, end = period.months_all()
    age_in = sql_in(sorted(ages))
    sql = f"""
SELECT month,
       SUM(resd_sum) FILTER (WHERE age_band IN ({age_in})) / MAX(n_days) AS youth_resd,
       SUM(work_sum) FILTER (WHERE age_band IN ({age_in})) / MAX(n_days) AS youth_work,
       SUM(visit_sum) / MAX(n_days) AS visit_all
FROM m_pop_kor_emd_month
WHERE emd_cd = {sql_str(emd_cd)} AND month BETWEEN DATE '{start}' AND DATE '{end}'
GROUP BY month
HAVING MAX(n_days) >= {a.min_month_days}
ORDER BY month"""
    res = ctx.wh.query(sql)
    x = [fmt.month_label(r[0]) for r in res.rows]
    resd = [float(r[1]) for r in res.rows]
    work = [float(r[2]) for r in res.rows]
    visit = [float(r[3]) for r in res.rows]

    def index(v: list[float]) -> list[float | None]:
        return [round(y / v[0] * 100, 1) if v and v[0] else None for y in v]

    chart = ChartSpec(
        id="s1_trend", kind="line", title=f"{row['emd_nm']} {lab} 거주·방문 추이",
        x=x, series=[Series(name=f"{lab} 거주", y=index(resd)), Series(name="방문자", y=index(visit))],
        y_title="지수 (첫 달 = 100)", y_format="index", note="각 계열의 첫 달 값을 100으로 놓은 지수예요.",
    )
    ev_month = EvidenceTable(
        id="s1_monthly", title=f"{row['emd_nm']} 월별 하루 평균 인구",
        columns=["월", f"{lab} 거주", f"{lab} 근무", "방문자(전체 연령)"],
        rows=[[m, round(r, 1), round(w, 1), round(v, 1)] for m, r, w, v in zip(x, resd, work, visit, strict=True)],
        formats={f"{lab} 거주": "num1", f"{lab} 근무": "num1", "방문자(전체 연령)": "num1"},
        sql=res.sql, tables=[POP], period=f"{x[0]}~{x[-1]}" if x else None,
        note=f"월 일수 {a.min_month_days}일 미만인 달은 제외해요. 값은 시간 평균 인구(명)예요.",
    )
    ev_sum = EvidenceTable(
        id="s1_summary", title=f"{row['emd_nm']} 핵심 지표",
        columns=["지표", "최근(P1)", "직전(P0)", "변화율"],
        rows=[
            [f"{lab} 거주인구 일평균", round(row["resd_y_p1"], 1), _r1(row["resd_y_p0"]), _r4(row["youth_resd_chg"])],
            [f"{lab} 근무인구 일평균", round(row["work_y_p1"], 1), _r1(row["work_y_p0"]), _r4(row["youth_work_chg"])],
            ["방문자 일평균", round(row["visit_p1"], 1), _r1(row["visit_p0"]), _r4(row["visit_chg"])],
        ],
        formats={"최근(P1)": "num1", "직전(P0)": "num1", "변화율": "pct"},
        sql=sql_all, tables=[POP], period=period.label,
        note="변화율 = P1 일평균 ÷ P0 일평균 − 1",
    )
    facts = _core_facts(row, period, ages)
    evidence = [ev_sum, ev_month]
    tables = [POP]
    limits = list(ctx.limits([POP]))
    if period.note:
        limits.append(period.note)

    # 지표 6: 외국인 장기체류 거주 변화율
    if ctx.wh.has(POP_FOR):
        pf = ctx.period(POP_FOR, _req(last_n_months, year))
        sql_f = f"""
WITH m AS (
  SELECT month, MAX(n_days) AS n_days, SUM(resd_sum) AS resd
  FROM m_pop_for_long_emd_month
  WHERE emd_cd = {sql_str(emd_cd)}
  GROUP BY month
  HAVING MAX(n_days) >= {a.min_month_days}
)
SELECT SUM(resd) FILTER (WHERE {pf.sql_p1()}) / SUM(n_days) FILTER (WHERE {pf.sql_p1()}) AS resd_p1,
       SUM(resd) FILTER (WHERE {pf.sql_p0()}) / SUM(n_days) FILTER (WHERE {pf.sql_p0()}) AS resd_p0
FROM m"""
        rf = ctx.wh.query(sql_f)
        f1, f0 = rf.rows[0] if rf.rows else (None, None)
        if f1 is not None:
            chg = (f1 / f0 - 1) if f0 else None
            facts += [
                Fact(key="foreign_resd_p1", label="외국인 장기체류 거주 일평균 (P1)", value=f1, unit="people",
                     text=fmt.people(f1), period=pf.p1_label),
                Fact(key="foreign_resd_chg", label="외국인 장기체류 거주 변화율", value=chg, unit="pct",
                     text=fmt.pct(chg), period=pf.label),
            ]
            ev_sum.rows.append(["외국인 장기체류 거주 일평균", round(f1, 1), _r1(f0), _r4(chg)])
            evidence.append(EvidenceTable(
                id="s1_foreign", title=f"{row['emd_nm']} 외국인 장기체류 거주인구",
                columns=["최근(P1) 일평균", "직전(P0) 일평균", "변화율"], rows=[[round(f1, 1), _r1(f0), _r4(chg)]],
                formats={"최근(P1) 일평균": "num1", "직전(P0) 일평균": "num1", "변화율": "pct"},
                sql=rf.sql, tables=[POP_FOR], period=pf.label))
            tables.append(POP_FOR)
            limits += [x_ for x_ in ctx.limits([POP_FOR]) if x_ not in limits]
            if pf.note:
                limits.append(f"외국인 장기체류 유동인구: {pf.note}")

    # 지표 7: 주말 소비비 (내국인, 읍면동이 속한 지구 또는 참고 지구)
    zones = ctx.refs.card_zones_for(emd_cd)
    if zones and ctx.wh.has("card_zone_dow_monthly"):
        pc = ctx.period("card_zone_dow_monthly", _req(last_n_months, year))
        profiles, ev_dow = dow_profiles(ctx, [z for z, _ in zones], pc)
        direct = zones[0][1]
        kr = [p for p in profiles if p.user_type == "내국인" and p.weekend_ratio is not None]
        if kr:
            val = sum(p.weekend_ratio for p in kr) / len(kr)
            zname = fmt.join_names([p.zone for p in kr])
            facts.append(Fact(
                key="weekend_ratio", label=f"내국인 주말 소비비 (주말 하루 소비 ÷ 평일 하루 소비, {zname}{'' if direct else ' · 참고 지구'})",
                value=val, unit="ratio", text=fmt.ratio(val), period=pc.p1_label,
                flag=None if direct else "proxy_zone"))
            if ev_dow:
                evidence.append(ev_dow)
                tables.append("card_zone_dow_monthly")
            if not direct:
                limits.append("이 읍면동은 카드 지구에 직접 속하지 않아 관광지 지구 값을 참고로 보여 줘요.")
            limits += [x_ for x_ in ctx.limits(["card_zone_dow_monthly"]) if x_ not in limits]
            if pc.note:
                limits.append(f"요일별 카드: {pc.note}")

    return ToolResult(tool="s1_trend", facts=facts, evidence=evidence, charts=[chart], limits=limits,
                      tables=tables, period=period.label,
                      data={"emd_cd": emd_cd, "emd_nm": row["emd_nm"], "ages": ages, "row": _jsonable(row),
                            "comparable": period.comparable})


def _r1(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}


# --------------------------------------------------------------------------- s1_classify
def _type_map(ctx: ToolContext, rows: list[dict[str, Any]], target: str | None, title: str) -> MapSpec:
    pts = []
    for r in rows:
        e = ctx.refs.emd(r["emd_cd"])
        pts.append(MapPoint(key=e.emd_cd, name=e.emd_nm, lat=e.lat, lon=e.lon, category=r["type"],
                            value=_r4(r["youth_resd_chg"]), role="target" if e.emd_cd == target else "other"))
    legend = {t: f"{t} {TYPE_LABEL[t]}" if t != "유지" else TYPE_LABEL[t] for t in TYPE_ORDER}
    return MapSpec(id="s1_type_map", title=title, points=pts, legend=legend,
                   note="읍면동 위치는 대략 좌표예요.")


@tool("s1_classify", "Stage 1", "43개 읍면동을 A 정착 성장·B 출퇴근·C 방문 의존·D 활력 저하로 분류하고, 추천 순위를 만들어요.")
def s1_classify(ctx: ToolContext, emd_cd: str | None = None, ages: list[int] | None = None,
                last_n_months: int | None = None, year: int | None = None,
                emd_type: str | None = None, city: str | None = None, top_n: int = 5) -> ToolResult:
    if not ctx.wh.has(POP):
        return _no_data("s1_classify", POP)
    a = ctx.config.analysis
    ages = ages or a.youth_age_bands
    lab = fmt.ages_label(ages)
    rows, period, sql_all = metrics_all(ctx, ages, _req(last_n_months, year))
    if not period.comparable:
        return ToolResult(tool="s1_classify", ok=False, period=period.label,
                          message=(period.note or "") + " 유형을 분류하려면 1년 전 자료가 필요해요.")
    rule_note = (f"임계값 τ = ±{a.tau * 100:.0f}%. 위에서부터 먼저 맞는 유형: "
                 f"A(거주 ≥ +τ, 근무 ≥ 0) → B(근무 ≥ +τ) → C(거주 ≤ −τ, 방문 ≥ 0) → D(거주 ≤ −τ, 방문 < 0) → 유지")
    counts = {t: sum(1 for r in rows if r["type"] == t) for t in TYPE_ORDER}
    limits = list(ctx.limits([POP]))
    if period.note:
        limits.append(period.note)
    facts: list[Fact] = [Fact(key="period", label="비교 기간", value=period.label, unit="text", text=period.label)]
    evidence: list[EvidenceTable] = []
    badges: list[Badge] = []
    data: dict[str, Any] = {"counts": counts, "ages": ages}

    if emd_cd:  # 읍면동 하나의 유형
        row = _row_of(rows, emd_cd)
        if row is None or row["type"] is None:
            return ToolResult(tool="s1_classify", ok=False, message=f"{ctx.refs.emd_name(emd_cd)}의 유형을 계산할 자료가 없어요.")
        t = row["type"]
        label = TYPE_LABEL[t]
        facts += [
            Fact(key="type", label="읍면동 유형", value=t, unit="text", text=f"{t} {label}" if t != "유지" else label),
            Fact(key="type_meaning", label="유형의 뜻", value=TYPE_MEANING[t], unit="text", text=TYPE_MEANING[t]),
        ]
        if row["near_type"]:
            nt = row["near_type"]
            facts.append(Fact(key="near_type", label="가장 가까운 유형(참고)", value=nt, unit="text",
                              text=f"{nt} {TYPE_LABEL[nt]}"))
        if row["small"]:
            limits.append(f"기준 인구가 {a.min_base_pop:.0f}명 미만인 작은 표본이라 변화율이 크게 흔들릴 수 있어요.")
            badges.append(Badge(label="작은 표본", tone="warn"))
        badges.insert(0, Badge(label=f"유형 {t}" if t != "유지" else "유지형", tone="type"))
        tau = a.tau
        checks = [
            ["A 정착 성장형", f"{lab} 거주 ≥ +{tau:.0%}, 근무 ≥ 0", row["youth_resd_chg"] >= tau and row["youth_work_chg"] >= 0],
            ["B 출퇴근형", f"{lab} 근무 ≥ +{tau:.0%}", row["youth_work_chg"] >= tau],
            ["C 방문 의존형", f"{lab} 거주 ≤ −{tau:.0%}, 방문 ≥ 0", row["youth_resd_chg"] <= -tau and row["visit_chg"] >= 0],
            ["D 활력 저하형", f"{lab} 거주 ≤ −{tau:.0%}, 방문 < 0", row["youth_resd_chg"] <= -tau and row["visit_chg"] < 0],
        ]
        evidence.append(EvidenceTable(
            id="s1_type_rule", title=f"{row['emd_nm']} 유형 판정",
            columns=["유형", "조건", "충족"], rows=[[n, c, "예" if ok else "아니오"] for n, c, ok in checks],
            tables=[POP], period=period.label, sql=sql_all,
            note=f"{rule_note}. 값: 거주 {fmt.pct(row['youth_resd_chg'])}, 근무 {fmt.pct(row['youth_work_chg'])}, "
                 f"방문 {fmt.pct(row['visit_chg'])}"))
        data.update({"emd_cd": emd_cd, "emd_nm": row["emd_nm"], "type": t, "near_type": row["near_type"],
                     "small": row["small"], "row": _jsonable(row)})

    # 추천 순위 (작은 표본 제외)
    pool = [r for r in rows if r["type"] is not None and not r["small"]]
    if emd_type == "읍면":
        pool = [r for r in pool if r["area_type"] == "읍면"]
    elif emd_type == "동":
        pool = [r for r in pool if r["area_type"] == "도심"]
    if city:
        pool = [r for r in pool if r["city"] == city]
    ranked = sorted(pool, key=lambda r: (-r["youth_resd_chg"], -r["youth_work_chg"], r["emd_cd"]))
    excluded = [r["emd_nm"] for r in rows if r["small"]]
    scope = "읍면" if emd_type == "읍면" else ("동 지역" if emd_type == "동" else "읍면동")
    if city:
        scope = f"{city} {scope}"
    evidence.append(EvidenceTable(
        id="s1_ranking", title=f"{lab} 거주 변화율 순위 ({scope} {len(ranked)}곳)",
        columns=["순위", "읍면동", "유형", f"{lab} 거주 변화율", f"{lab} 근무 변화율", "방문자 변화율", f"{lab} 비중"],
        rows=[[i + 1, r["emd_nm"], r["type"], _r4(r["youth_resd_chg"]), _r4(r["youth_work_chg"]),
               _r4(r["visit_chg"]), _r4(r["youth_share"])] for i, r in enumerate(ranked)],
        formats={f"{lab} 거주 변화율": "pct", f"{lab} 근무 변화율": "pct", "방문자 변화율": "pct", f"{lab} 비중": "share"},
        sql=sql_all, tables=[POP], period=period.label,
        note=rule_note + (f". 작은 표본이라 순위에서 뺀 곳: {fmt.join_names(excluded)}" if excluded else "")))
    top = ranked[:top_n]
    bottom = ranked[-min(3, len(ranked)):][::-1] if len(ranked) > top_n else []
    for i, r in enumerate(top, 1):
        facts.append(Fact(key=f"rank{i}", label=f"{i}위", value=r["youth_resd_chg"], unit="pct",
                          text=f"{r['emd_nm']} {fmt.pct(r['youth_resd_chg'])}", period=period.label))
    for t in TYPE_ORDER:
        facts.append(Fact(key=f"count_{t}", label=f"{TYPE_LABEL[t]} 수", value=counts[t], unit="count", text=f"{counts[t]}곳"))
    if excluded:
        facts.append(Fact(key="excluded_small", label="순위에서 뺀 작은 표본", value=fmt.join_names(excluded),
                          unit="text", text=fmt.join_names(excluded), flag="small_sample"))
    data.update({"scope": scope, "top": [{"emd_cd": r["emd_cd"], "emd_nm": r["emd_nm"], "type": r["type"],
                                         "youth_resd_chg": _r4(r["youth_resd_chg"])} for r in top],
                 "bottom": [{"emd_nm": r["emd_nm"], "type": r["type"], "youth_resd_chg": _r4(r["youth_resd_chg"])}
                            for r in bottom],
                 "excluded_small": excluded,
                 "types": {r["emd_cd"]: r["type"] for r in rows}})
    title = "유형 지도" if emd_cd else f"{lab} 거주 변화 유형 지도"
    return ToolResult(tool="s1_classify", facts=facts, evidence=evidence, maps=[_type_map(ctx, rows, emd_cd, title)],
                      limits=limits, badges=badges, tables=[POP], period=period.label, data=data)


# --------------------------------------------------------------------------- s1_peers
_PEER_FEATURES = ["youth_resd_chg", "youth_work_chg", "visit_chg", "youth_share", "settle_ratio"]
_PEER_LABELS = ["거주 변화율", "근무 변화율", "방문자 변화율", "청년 비중", "정주비"]


@tool("s1_peers", "Stage 1", "지표가 가장 비슷한 읍면동 3곳을 찾아 나란히 비교해요.")
def s1_peers(ctx: ToolContext, emd_cd: str, ages: list[int] | None = None,
             last_n_months: int | None = None, year: int | None = None) -> ToolResult:
    if not ctx.wh.has(POP):
        return _no_data("s1_peers", POP)
    a = ctx.config.analysis
    ages = ages or a.youth_age_bands
    lab = fmt.ages_label(ages)
    rows, period, sql_all = metrics_all(ctx, ages, _req(last_n_months, year))
    me = _row_of(rows, emd_cd)
    if me is None or any(me[f] is None for f in _PEER_FEATURES):
        return ToolResult(tool="s1_peers", ok=False, message="비교에 쓸 지표를 계산하지 못했어요.")
    # 같은 종류(읍면끼리, 동끼리) 안에서 비교하고, 작은 표본은 빼요.
    pool = [r for r in rows if r["area_type"] == me["area_type"] and not r["small"]
            and all(r[f] is not None for f in _PEER_FEATURES)]
    if me not in pool:
        pool.append(me)
    stats = {}
    for f in _PEER_FEATURES:
        vals = [r[f] for r in pool]
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1.0
        stats[f] = (mean, sd)

    def z(r: dict[str, Any]) -> list[float]:
        return [(r[f] - stats[f][0]) / stats[f][1] for f in _PEER_FEATURES]

    zme = z(me)
    dist = sorted(((math.dist(zme, z(r)), r) for r in pool if r["emd_cd"] != emd_cd), key=lambda t: (t[0], t[1]["emd_cd"]))
    peers = dist[: a.peers_k]
    kind = "읍면" if me["area_type"] == "읍면" else "동"
    table_rows = [[me["emd_nm"] + " (대상)", me["type"], *[_r4(me[f]) for f in _PEER_FEATURES], None]]
    table_rows += [[r["emd_nm"], r["type"], *[_r4(r[f]) for f in _PEER_FEATURES], round(d, 2)] for d, r in peers]
    cols = ["읍면동", "유형", *[f"{lab} {c}" if "변화율" in c and "방문" not in c else c for c in _PEER_LABELS], "거리"]
    ev = EvidenceTable(
        id="s1_peers", title=f"{me['emd_nm']}{'과' if fmt.has_batchim(me['emd_nm']) else '와'} 지표가 비슷한 {kind} {len(peers)}곳",
        columns=cols, rows=table_rows,
        formats={c: "pct" for c in cols[2:5]} | {c: "share" for c in cols[5:7]} | {"거리": "num2"},
        sql=sql_all, tables=[POP], period=period.label,
        note=f"다섯 지표를 같은 {kind} 집단 안에서 표준화한 뒤 거리가 가까운 순서예요. 작은 표본은 제외해요.")
    names = [r["emd_nm"] for _, r in peers]
    facts = [Fact(key="peers", label="지표가 비슷한 곳", value=fmt.join_names(names), unit="text", text=fmt.join_names(names))]
    for i, (_d, r) in enumerate(peers, 1):
        facts.append(Fact(key=f"peer{i}_resd_chg", label=f"{r['emd_nm']} {lab} 거주 변화율", value=r["youth_resd_chg"],
                          unit="pct", text=fmt.pct(r["youth_resd_chg"]), period=period.label))
    chart = ChartSpec(
        id="s1_peers", kind="bar", title=f"{lab} 거주 변화율 비교",
        x=[me["emd_nm"], *names], series=[Series(name=f"{lab} 거주 변화율", y=[_r4(me["youth_resd_chg"]),
                                                                        *[_r4(r["youth_resd_chg"]) for _, r in peers]])],
        y_title="변화율", y_format="pct")
    return ToolResult(tool="s1_peers", facts=facts, evidence=[ev], charts=[chart], tables=[POP], period=period.label,
                      data={"peers": [{"emd_cd": r["emd_cd"], "emd_nm": r["emd_nm"], "type": r["type"]} for _, r in peers]})


# --------------------------------------------------------------------------- 지구(여러 읍면동) 묶음 유형
def group_type(ctx: ToolContext, emd_cds: list[str], ages: list[int] | None = None,
               last_n_months: int | None = None, year: int | None = None) -> dict[str, Any] | None:
    """읍면동 여러 곳을 하나로 합쳐 유형을 판정해요 (예: '서귀포시 구도심' 지구)."""
    if not emd_cds or not ctx.wh.has(POP):
        return None
    a = ctx.config.analysis
    ages = ages or a.youth_age_bands
    period = ctx.period(POP, _req(last_n_months, year))
    if not period.comparable:
        return None
    p1, p0 = period.sql_p1(), period.sql_p0()
    age_in = sql_in(sorted(ages))
    sql = f"""
WITH m AS (
  SELECT month, emd_cd, MAX(n_days) AS n_days,
         SUM(resd_sum) FILTER (WHERE age_band IN ({age_in})) AS resd_y,
         SUM(work_sum) FILTER (WHERE age_band IN ({age_in})) AS work_y,
         SUM(visit_sum) AS visit_all
  FROM m_pop_kor_emd_month
  WHERE emd_cd IN ({sql_in(emd_cds)})
  GROUP BY month, emd_cd
  HAVING MAX(n_days) >= {a.min_month_days}
),
g AS (
  SELECT month, MAX(n_days) AS n_days, SUM(resd_y / n_days) AS resd_y, SUM(work_y / n_days) AS work_y,
         SUM(visit_all / n_days) AS visit_all
  FROM m GROUP BY month
)
SELECT AVG(resd_y) FILTER (WHERE {p1}) / NULLIF(AVG(resd_y) FILTER (WHERE {p0}), 0) - 1 AS youth_resd_chg,
       AVG(work_y) FILTER (WHERE {p1}) / NULLIF(AVG(work_y) FILTER (WHERE {p0}), 0) - 1 AS youth_work_chg,
       AVG(visit_all) FILTER (WHERE {p1}) / NULLIF(AVG(visit_all) FILTER (WHERE {p0}), 0) - 1 AS visit_chg
FROM g"""
    res = ctx.wh.query(sql)
    row = res.first()
    if not row or row["youth_resd_chg"] is None:
        return None
    row["type"] = classify_type(row["youth_resd_chg"], row["youth_work_chg"], row["visit_chg"], a.tau)
    row["near_type"] = (nearest_type(row["youth_resd_chg"], row["youth_work_chg"], row["visit_chg"], a.tau)
                        if row["type"] == "유지" else None)
    row["period"] = period.label
    row["sql"] = res.sql
    return row


@tool("s1_zone", "Stage 1", "지구(여러 읍면동 묶음)의 청년 거주·근무·방문 변화와 유형을 계산해요.")
def s1_zone(ctx: ToolContext, zone: str, ages: list[int] | None = None,
            last_n_months: int | None = None, year: int | None = None) -> ToolResult:
    emds = ctx.refs.zone_emds(zone)
    if not emds:
        return ToolResult(tool="s1_zone", ok=False,
                          message=f"'{zone}'은(는) 읍면동과 직접 대응하지 않는 지구라 인구 진단을 할 수 없어요. 읍면동을 골라 주세요.")
    a = ctx.config.analysis
    ages = ages or a.youth_age_bands
    lab = fmt.ages_label(ages)
    g = group_type(ctx, emds, ages, last_n_months, year)
    if g is None:
        return ToolResult(tool="s1_zone", ok=False, message="비교할 1년 전 자료가 없어 지구 유형을 계산하지 못했어요.")
    rows, period, _sql = metrics_all(ctx, ages, _req(last_n_months, year))
    members = [r for r in rows if r["emd_cd"] in emds]
    t = g["type"]
    label = TYPE_LABEL[t]
    facts = [
        Fact(key="place", label="장소", value=zone, unit="text", text=zone),
        Fact(key="ages", label="연령", value=lab, unit="text", text=lab),
        Fact(key="period", label="비교 기간", value=period.label, unit="text", text=period.label),
        Fact(key="members", label="지구에 속한 읍면동", value=fmt.join_names([r["emd_nm"] for r in members]), unit="text",
             text=fmt.join_names([r["emd_nm"] for r in members])),
        Fact(key="youth_resd_chg", label=f"{lab} 거주 변화율", value=g["youth_resd_chg"], unit="pct",
             text=fmt.pct(g["youth_resd_chg"]), period=period.label),
        Fact(key="youth_work_chg", label=f"{lab} 근무 변화율", value=g["youth_work_chg"], unit="pct",
             text=fmt.pct(g["youth_work_chg"]), period=period.label),
        Fact(key="visit_chg", label="방문자 변화율", value=g["visit_chg"], unit="pct", text=fmt.pct(g["visit_chg"]),
             period=period.label),
        Fact(key="type", label="지구 유형", value=t, unit="text", text=f"{t} {label}" if t != "유지" else label),
        Fact(key="type_meaning", label="유형의 뜻", value=TYPE_MEANING[t], unit="text", text=TYPE_MEANING[t]),
    ]
    ev = EvidenceTable(
        id="s1_zone", title=f"{zone} 지구와 속한 읍면동의 변화율",
        columns=["구분", "유형", f"{lab} 거주 변화율", f"{lab} 근무 변화율", "방문자 변화율"],
        rows=[[f"{zone} (합계)", t, _r4(g["youth_resd_chg"]), _r4(g["youth_work_chg"]), _r4(g["visit_chg"])]]
             + [[r["emd_nm"], r["type"], _r4(r["youth_resd_chg"]), _r4(r["youth_work_chg"]), _r4(r["visit_chg"])]
                for r in members],
        formats={f"{lab} 거주 변화율": "pct", f"{lab} 근무 변화율": "pct", "방문자 변화율": "pct"},
        sql=g["sql"], tables=[POP], period=period.label,
        note="지구 값은 속한 읍면동의 하루 평균 인구를 합쳐 계산해요. 지구와 읍면동의 연결은 잠정 참조표 기준이에요.")
    limits = [*ctx.limits([POP]), "지구와 읍면동의 연결은 잠정 참조표 기준이에요."]
    return ToolResult(tool="s1_zone", facts=facts, evidence=[ev], limits=limits,
                      badges=[Badge(label=f"유형 {t}" if t != "유지" else "유지형", tone="type")],
                      tables=[POP], period=period.label,
                      data={"zone": zone, "type": t, "near_type": g["near_type"], "emd_cds": emds,
                            "row": {k: g[k] for k in ("youth_resd_chg", "youth_work_chg", "visit_chg")}})


def overview_correlation(ctx: ToolContext, ages: list[int] | None = None, last_n_months: int | None = None,
                         year: int | None = None) -> Fact | None:
    """읍면동 전체에서 방문자 변화율과 청년 거주 변화율이 함께 움직였는지 (상관계수). 원인을 뜻하지 않아요."""
    ages = ages or ctx.config.analysis.youth_age_bands
    rows, period, _ = metrics_all(ctx, ages, _req(last_n_months, year))
    pts = [(r["visit_chg"], r["youth_resd_chg"]) for r in rows
           if not r["small"] and r["visit_chg"] is not None and r["youth_resd_chg"] is not None]
    if len(pts) < 5:
        return None
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    syy = sum((y - my) ** 2 for _, y in pts)
    if sxx <= 0 or syy <= 0:
        return None
    r = sum((x - mx) * (y - my) for x, y in pts) / math.sqrt(sxx * syy)
    return Fact(key="corr_visit_resd", label=f"방문자 변화율과 {fmt.ages_label(ages)} 거주 변화율의 상관계수 (읍면동 {len(pts)}곳)",
                value=round(r, 2), unit="ratio", text=f"{r:+.2f}", period=period.label)
