"""Stage 3 「어떻게 오게 하나」 — 수요 기준선·시나리오, 노선 관광 민감도, 거점→동네 코스."""

from __future__ import annotations

from typing import Any

from .. import fmt
from ..data.periods import add_months
from ..schemas import Badge, ChartSpec, EvidenceTable, Fact, MapLine, MapPoint, MapSpec, Series, ToolResult
from .base import ToolContext, sql_in, tool

ARR = "arrivals_purpose_monthly"
BUS = "bus_route_daily"
INDIV = "개별여행"
_HUB_ORDER = {"공항": 0, "터미널": 1, "항만": 2}


def _assumption(supply_change: float, elasticity: float) -> str:
    return f"가정: 국내선 공급 {fmt.pct(supply_change, 0)} · 탄력성 ε {elasticity:.1f}"


# --------------------------------------------------------------------------- s3_forecast
@tool("s3_forecast", "Stage 3", "방문목적별 입도객 기준선(전년 동월)에 '국내선 공급 변화' 가정을 적용해 수요 시나리오를 계산해요.")
def s3_forecast(ctx: ToolContext, target_month: int | None = None, supply_change: float | None = None,
                elasticity: float | None = None, group: str | None = None) -> ToolResult:
    if not ctx.wh.has(ARR):
        return ToolResult(tool="s3_forecast", ok=False, message="방문목적별 입도객 자료가 없어 시나리오를 계산할 수 없어요.")
    c3 = ctx.config.stage3
    delta = c3.supply_change_default if supply_change is None else float(supply_change)
    eps = c3.elasticity_default if elasticity is None else float(elasticity)
    grid = sorted({*c3.elasticity_grid, eps})
    first, last = ctx.wh.period(ARR)  # type: ignore[misc]
    # 대상 월: 지정이 없으면 자료 마지막 달의 다음 달, 지정하면 그 뒤 처음 오는 해당 월
    target = add_months(last, 1)
    if target_month:
        while target.month != int(target_month):
            target = add_months(target, 1)
    base = add_months(target, -12)
    while base > last:
        base = add_months(base, -12)
    if base < first:
        return ToolResult(tool="s3_forecast", ok=False,
                          message=f"기준선으로 쓸 전년 동월 자료가 없어요 (수록 기간 {ctx.table_period_label(ARR)}).")
    sql = f"""
SELECT a.purpose, COALESCE(p.purpose_group, '기타') AS purpose_group, SUM(a.visitors) AS baseline
FROM arrivals_purpose_monthly AS a
LEFT JOIN ref_purpose AS p ON p.purpose = a.purpose
WHERE a.month = DATE '{base}'
GROUP BY 1, 2
ORDER BY baseline DESC"""
    res = ctx.wh.query(sql)
    if not res.rows:
        return ToolResult(tool="s3_forecast", ok=False, message=f"{fmt.month_label(base)} 입도객 자료가 없어요.")

    def scen(v: float, e: float) -> float:
        return v * max(0.0, 1.0 + e * delta)

    cols = ["방문목적", "구분", "기준선", *[f"ε {e:.1f}" for e in grid]]
    rows = [[p, g, int(b), *[round(scen(float(b), e)) for e in grid]] for p, g, b in res.rows]
    total = float(sum(float(b) for _, _, b in res.rows))
    rows.append(["합계", "-", round(total), *[round(scen(total, e)) for e in grid]])
    indiv = next((float(b) for p, _, b in res.rows if p == INDIV), None)
    t_lab, b_lab = fmt.month_label(target), fmt.month_label(base)
    facts = [
        Fact(key="target_month", label="대상 월", value=t_lab, unit="month", text=t_lab),
        Fact(key="baseline_month", label="기준선(전년 동월)", value=b_lab, unit="month", text=b_lab),
        Fact(key="supply_change", label="국내선 공급 변화율 (가정)", value=delta, unit="pct", text=fmt.pct(delta, 0), flag="assumption"),
        Fact(key="elasticity", label="수요 탄력성 ε (가정)", value=eps, unit="ratio", text=f"{eps:.1f}", flag="assumption"),
        Fact(key="baseline_total", label="기준선 입도객 합계", value=total, unit="people", text=fmt.people(total), period=b_lab),
        Fact(key="scenario_total", label="시나리오 입도객 합계", value=scen(total, eps), unit="people",
             text=fmt.people(scen(total, eps)), flag="assumption"),
        Fact(key="scenario_delta", label="기준선 대비 변화", value=scen(total, eps) - total, unit="people",
             text=fmt.people(scen(total, eps) - total), flag="assumption"),
        Fact(key="scenario_change", label="기준선 대비 변화율", value=(scen(total, eps) / total - 1) if total else None,
             unit="pct", text=fmt.pct((scen(total, eps) / total - 1) if total else None), flag="assumption"),
    ]
    for e in grid:
        facts.append(Fact(key=f"scenario_total_e{e:.1f}", label=f"시나리오 합계 (ε {e:.1f})", value=scen(total, e),
                          unit="people", text=fmt.people(scen(total, e)), flag="assumption"))
    if indiv is not None:
        facts += [
            Fact(key="baseline_indiv", label="기준선 개별여행 입도객", value=indiv, unit="people", text=fmt.people(indiv), period=b_lab),
            Fact(key="scenario_indiv", label="시나리오 개별여행 입도객", value=scen(indiv, eps), unit="people",
                 text=fmt.people(scen(indiv, eps)), flag="assumption"),
        ]
    ev = EvidenceTable(
        id="s3_scenario", title=f"{t_lab} 방문목적별 입도객 시나리오 (국내선 공급 {fmt.pct(delta, 0)} 가정)",
        columns=cols, rows=rows, formats={c: "int" for c in cols[2:]},
        sql=res.sql, tables=[ARR], period=f"기준선 {b_lab}",
        note=f"시나리오 입도객 = 기준선 × (1 + ε × 국내선 공급 변화율). 기준선은 전년 동월({b_lab}) 실적이에요. "
             f"ε는 사용자 가정이며 0.5 / 1.0 / 1.5 민감도를 함께 보여 줘요.")
    chart = ChartSpec(
        id="s3_scenario", kind="bar", title=f"{t_lab} 입도객 합계: 기준선과 시나리오",
        x=["기준선", *[f"ε {e:.1f}" for e in grid]],
        series=[Series(name="입도객 합계", y=[round(total), *[round(scen(total, e)) for e in grid]])],
        y_title="명", y_format="num", note=_assumption(delta, eps),
        highlight=next((f"ε {e:.1f}" for e in grid if abs(e - eps) < 1e-9), None))
    limits = [*ctx.limits([ARR]),
              "시나리오는 예측이 아니에요. 공급 변화율과 탄력성 ε는 가정값이고, 모든 방문목적에 같은 비율을 적용했어요."]
    return ToolResult(tool="s3_forecast", facts=facts, evidence=[ev], charts=[chart], limits=limits,
                      badges=[Badge(label=_assumption(delta, eps), tone="assumption")], tables=[ARR],
                      period=f"기준선 {b_lab}",
                      data={"supply_change": delta, "elasticity": eps, "target": t_lab, "baseline": b_lab, "group": group})


# --------------------------------------------------------------------------- s3_route_beta
def route_betas(ctx: ToolContext, routes: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    """노선별 관광 민감도 β: ln(노선 월 이용자) 를 ln(개별여행 입도객) 에 회귀한 기울기."""
    key = "s3:betas:" + ",".join(sorted(routes))
    if key in ctx.cache:
        return ctx.cache[key]
    sql = f"""
WITH bus AS (
  SELECT month, route_no,
         riders * 1.0 / n_days * date_part('day', last_day(month)) AS riders_month
  FROM m_bus_route_month
  WHERE n_days >= {ctx.min_month_days} AND route_no IN ({sql_in(sorted(routes))})
),
arr AS (
  SELECT month, SUM(visitors) AS visitors
  FROM arrivals_purpose_monthly
  WHERE purpose = '{INDIV}'
  GROUP BY month
)
SELECT b.route_no,
       regr_slope(ln(b.riders_month), ln(a.visitors)) AS beta,
       regr_r2(ln(b.riders_month), ln(a.visitors)) AS r2,
       regr_count(ln(b.riders_month), ln(a.visitors)) AS n_months,
       AVG(b.riders_month) AS riders_month_avg,
       MIN(b.month) AS first_month, MAX(b.month) AS last_month
FROM bus AS b
JOIN arr AS a USING (month)
WHERE b.riders_month > 0 AND a.visitors > 0
GROUP BY b.route_no
ORDER BY b.route_no"""
    res = ctx.wh.query(sql)
    out = {r["route_no"]: r for r in res.dicts()}
    ctx.cache[key] = (out, res.sql)
    return ctx.cache[key]


@tool("s3_route_beta", "Stage 3", "읍면동을 지나는 버스 노선 가운데 관광 수요에 민감한 노선(β, R² 0.5 이상)을 찾아요.")
def s3_route_beta(ctx: ToolContext, emd_cd: str, supply_change: float | None = None,
                  elasticity: float | None = None) -> ToolResult:
    if not (ctx.wh.has(BUS) and ctx.wh.has(ARR)):
        return ToolResult(tool="s3_route_beta", ok=False, message="버스 또는 입도객 자료가 없어 노선 민감도를 계산할 수 없어요.")
    c3 = ctx.config.stage3
    delta = c3.supply_change_default if supply_change is None else float(supply_change)
    eps = c3.elasticity_default if elasticity is None else float(elasticity)
    name = ctx.refs.emd_name(emd_cd)
    routes = ctx.refs.routes_through(emd_cd)
    if not routes:
        return ToolResult(tool="s3_route_beta", ok=True, message=f"참조표에 {name}을(를) 지나는 노선이 없어요.",
                          facts=[Fact(key="n_routes", label="경유 노선 수", value=0, unit="count", text="0개")],
                          limits=_route_limits(ctx), data={"routes": [], "sensitive": []})
    betas, sql = route_betas(ctx, routes)
    rows, sensitive = [], []
    demand = max(0.0, 1.0 + eps * delta)
    for rn in sorted(routes, key=lambda r: -(betas.get(r, {}).get("beta") or -9)):
        b = betas.get(rn)
        route = ctx.refs.routes[rn]
        if not b or b["beta"] is None:
            rows.append([rn, route.route_nm, None, None, 0, None, "자료 부족", None])
            continue
        ok = (b["r2"] or 0) >= c3.beta_min_r2 and b["n_months"] >= c3.beta_min_months and b["beta"] > 0
        implied = (demand ** b["beta"] - 1) if ok else None
        rows.append([rn, route.route_nm, round(b["beta"], 2), round(b["r2"], 2), int(b["n_months"]),
                     round(b["riders_month_avg"]), "채택" if ok else "미채택", _r4(implied)])
        if ok:
            sensitive.append({"route_no": rn, "route_nm": route.route_nm, "beta": round(b["beta"], 2),
                              "r2": round(b["r2"], 2), "implied": _r4(implied)})
    span = None
    if betas:
        lo = min(b["first_month"] for b in betas.values())
        hi = max(b["last_month"] for b in betas.values())
        span = f"{fmt.month_label(lo)}~{fmt.month_label(hi)}"
    facts = [
        Fact(key="n_routes", label=f"{name} 경유 노선 수", value=len(routes), unit="count", text=f"{len(routes)}개"),
        Fact(key="n_sensitive", label="관광 민감 노선 수", value=len(sensitive), unit="count", text=f"{len(sensitive)}개"),
    ]
    for i, s in enumerate(sensitive[:3], 1):
        facts += [
            Fact(key=f"route{i}", label=f"관광 민감 노선 {i}", value=s["route_no"], unit="text", text=f"{s['route_no']}번"),
            Fact(key=f"route{i}_beta", label=f"{s['route_no']}번 관광 민감도 β", value=s["beta"], unit="ratio", text=f"{s['beta']:.2f}", period=span),
            Fact(key=f"route{i}_r2", label=f"{s['route_no']}번 R²", value=s["r2"], unit="ratio", text=f"{s['r2']:.2f}", period=span),
            Fact(key=f"route{i}_implied", label=f"{s['route_no']}번 이용자 변화 (가정 적용)", value=s["implied"], unit="pct",
                 text=fmt.pct(s["implied"]), flag="assumption"),
        ]
    ev = EvidenceTable(
        id="s3_routes", title=f"{name} 경유 노선의 관광 민감도",
        columns=["노선", "노선명", "β", "R²", "월 수", "월평균 이용자", "판정", "이용자 변화(가정 적용)"], rows=rows,
        formats={"β": "num2", "R²": "num2", "월평균 이용자": "int", "이용자 변화(가정 적용)": "pct"},
        sql=sql, tables=[BUS, ARR], period=span,
        note=f"β = ln(노선 월 이용자)를 ln(개별여행 입도객)에 회귀한 기울기. R² {c3.beta_min_r2} 이상, "
             f"{c3.beta_min_months}개월 이상인 노선만 채택해요. 이용자 변화 = (1 + ε × 공급 변화율)^β − 1 ({_assumption(delta, eps)}).")
    limits = [*ctx.limits([BUS]), "노선 관광 민감도는 함께 움직인 정도를 요약한 값이에요. 원인을 뜻하지 않아요.", *_route_limits(ctx)]
    return ToolResult(tool="s3_route_beta", facts=facts, evidence=[ev], limits=limits,
                      badges=[Badge(label=_assumption(delta, eps), tone="assumption")], tables=[BUS, ARR], period=span,
                      data={"routes": routes, "sensitive": sensitive})


def _route_limits(ctx: ToolContext) -> list[str]:
    if ctx.refs.routes_are_sample:
        return ["노선과 경유 읍면동은 샘플 참조표 기준이에요. 실제 정류소 좌표로 다시 만들어야 해요."]
    return []


def _r4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


# --------------------------------------------------------------------------- s3_courses
def _hops(seq: list[str], a: str, b: str) -> int | None:
    if a in seq and b in seq:
        return abs(seq.index(a) - seq.index(b))
    return None


def find_courses(ctx: ToolContext, hub_emd: str, target: str, max_transfers: int = 1) -> list[dict[str, Any]]:
    """거점 읍면동에서 대상 읍면동까지 기존 노선으로 가는 경로 (직행 또는 환승 1회)."""
    refs = ctx.refs
    out: list[dict[str, Any]] = []
    for rn in refs.routes_through(hub_emd):
        h = _hops(refs.route_emds(rn), hub_emd, target)
        if h:
            out.append({"transfers": 0, "legs": [{"route_no": rn, "from": hub_emd, "to": target, "hops": h}], "cost": h})
    if max_transfers >= 1:
        for r1 in refs.routes_through(hub_emd):
            s1 = refs.route_emds(r1)
            if target in s1:
                continue
            for r2 in refs.routes_through(target):
                if r2 == r1:
                    continue
                s2 = refs.route_emds(r2)
                best = None
                for x in s1:
                    if x in (hub_emd, target) or x not in s2:
                        continue
                    h1, h2 = _hops(s1, hub_emd, x), _hops(s2, x, target)
                    if h1 and h2 and (best is None or h1 + h2 < best[0]):
                        best = (h1 + h2, x, h1, h2)
                if best:
                    out.append({"transfers": 1, "cost": best[0] + 3,
                                "legs": [{"route_no": r1, "from": hub_emd, "to": best[1], "hops": best[2]},
                                         {"route_no": r2, "from": best[1], "to": target, "hops": best[3]}]})
    out.sort(key=lambda c: (c["transfers"], c["cost"], [leg["route_no"] for leg in c["legs"]]))
    return out


@tool("s3_courses", "Stage 3", "공항·항만·터미널에서 대상 읍면동까지 직행 또는 환승 1회로 가는 기존 노선 코스 2~3개를 제안해요.")
def s3_courses(ctx: ToolContext, emd_cd: str, hub_id: str | None = None) -> ToolResult:
    refs = ctx.refs
    c3 = ctx.config.stage3
    target = refs.emd(emd_cd)
    # 관광 민감 노선(채택 기준 통과)을 먼저 추천해요.
    sensitive: dict[str, float] = {}
    if ctx.wh.has(BUS) and ctx.wh.has(ARR) and refs.routes:
        betas, _ = route_betas(ctx, sorted(refs.routes))
        for rn, b in betas.items():
            if b["beta"] and b["beta"] > 0 and (b["r2"] or 0) >= c3.beta_min_r2 and b["n_months"] >= c3.beta_min_months:
                sensitive[rn] = float(b["beta"])
    hubs = [refs.hubs[hub_id]] if hub_id and hub_id in refs.hubs else list(refs.hubs.values())
    hubs = sorted(hubs, key=lambda h: (_HUB_ORDER.get(h.hub_type, 9), h.hub_id))
    per_hub: list[tuple[Any, list[dict[str, Any]]]] = []
    gaps: list[str] = []
    for h in hubs:
        if h.emd_cd == emd_cd:
            continue  # 동네 안에 있는 거점
        found = find_courses(ctx, h.emd_cd, emd_cd, c3.max_transfers)
        found.sort(key=lambda c: (c["transfers"], -sensitive.get(c["legs"][0]["route_no"], 0.0), c["cost"],
                                  [leg["route_no"] for leg in c["legs"]]))
        if found:
            per_hub.append((h, found))
        else:
            gaps.append(h.hub_nm)

    # 거점마다 하나씩, 이미 쓴 노선과 겹치지 않는 코스를 우선해요. 자리가 남으면 다음 순위로 채워요.
    picked: list[tuple[Any, dict[str, Any]]] = []
    used: set[str] = set()
    for _round in range(3):
        for h, found in per_hub:
            if len(picked) >= c3.max_courses:
                break
            rest = [c for c in found if all((h.hub_id, c) != (ph.hub_id, pc) for ph, pc in picked)]
            fresh = [c for c in rest if not used & {leg["route_no"] for leg in c["legs"]}]
            choice = (fresh or (rest if _round > 0 else []))[:1]
            for c in choice:
                picked.append((h, c))
                used |= {leg["route_no"] for leg in c["legs"]}
    picked.sort(key=lambda t: (t[1]["transfers"], _HUB_ORDER.get(t[0].hub_type, 9), t[1]["cost"]))

    courses, rows, lines = [], [], []
    points: dict[str, MapPoint] = {
        emd_cd: MapPoint(key=emd_cd, name=target.emd_nm, lat=target.lat, lon=target.lon, role="target")}
    for i, (h, c) in enumerate(picked, 1):
        legs_txt, via, keys = [], [], [h.hub_id]
        points[h.hub_id] = MapPoint(key=h.hub_id, name=h.hub_nm, lat=h.lat, lon=h.lon, role="hub", category=h.hub_type)
        for leg in c["legs"]:
            to_nm = refs.emd_name(leg["to"])
            mark = " (관광 민감)" if leg["route_no"] in sensitive else ""
            legs_txt.append(f"{leg['route_no']}번{mark} → {to_nm}")
            if leg["to"] != emd_cd:
                via.append(to_nm)
                e = refs.emd(leg["to"])
                points.setdefault(e.emd_cd, MapPoint(key=e.emd_cd, name=e.emd_nm, lat=e.lat, lon=e.lon, role="via"))
            keys.append(leg["to"])
        kind = "직행" if c["transfers"] == 0 else f"환승 {c['transfers']}회"
        text = f"{h.hub_nm} → " + " → ".join(legs_txt)
        courses.append({"no": i, "hub_id": h.hub_id, "hub_nm": h.hub_nm, "hub_type": h.hub_type, "kind": kind,
                        "transfers": c["transfers"], "routes": [leg["route_no"] for leg in c["legs"]],
                        "via": via, "text": text})
        rows.append([i, h.hub_nm, kind, " → ".join(f"{leg['route_no']}번" for leg in c["legs"]),
                     fmt.join_names(via) if via else "-", text])
        lines.append(MapLine(label=f"코스 {i}", keys=keys))
    name = target.emd_nm
    facts = [Fact(key="n_courses", label="제안 코스 수", value=len(courses), unit="count", text=f"{len(courses)}개")]
    for c in courses:
        facts.append(Fact(key=f"course{c['no']}", label=f"코스 {c['no']} ({c['kind']})", value=c["text"], unit="text", text=c["text"]))
    if gaps:
        facts.append(Fact(key="access_gap", label="접근성 공백 거점", value=fmt.join_names(gaps), unit="text",
                          text=fmt.join_names(gaps), flag="access_gap"))
    ev = EvidenceTable(
        id="s3_courses", title=f"거점에서 {name}까지 가는 코스",
        columns=["코스", "출발 거점", "구분", "노선", "환승 읍면동", "경로"], rows=rows,
        tables=["ref_route", "ref_route_emd", "ref_hub"],
        note="참조표(ref_route_emd)의 기존 노선만 써요. 직행 또는 환승 1회로 닿지 않는 거점은 '접근성 공백'으로 표시해요."
             + (f" 접근성 공백: {fmt.join_names(gaps)}" if gaps else ""))
    limits = ["코스는 노선이 지나는 읍면동을 이은 것으로, 정류소 위치·배차 간격·소요 시간은 반영하지 않았어요.", *_route_limits(ctx)]
    badges = [Badge(label="접근성 공백", tone="warn")] if not courses else []
    m = MapSpec(id="s3_course_map", title=f"{name}까지 오는 코스", points=list(points.values()), lines=lines,
                note="거점과 읍면동 위치는 대략 좌표예요.")
    message = None if courses else f"거점에서 {name}까지 직행 또는 환승 1회로 가는 노선이 참조표에 없어요 (접근성 공백)."
    return ToolResult(tool="s3_courses", facts=facts, evidence=[ev], maps=[m], limits=limits, badges=badges,
                      message=message, tables=["ref_route_emd"], data={"courses": courses, "gaps": gaps})
