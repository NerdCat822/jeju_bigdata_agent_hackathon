"""계획·실행: 단계별 분석 레시피를 도구로 실행하고 결과를 하나의 묶음(Bundle)으로 모아요.

연계 실행에서는 앞 단계 산출물(읍면동 유형 → 타깃 관광객·피크 요일)을 다음 단계의 입력으로 넘겨요.
앞 단계 결과가 없으면 먼저 실행해서 채워요.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .. import progress
from ..schemas import (
    Badge,
    ChartSpec,
    EvidenceTable,
    Fact,
    MapSpec,
    ParsedQuery,
    StepLog,
    Suggestion,
    ToolResult,
)
from ..tools import stage1 as t1
from ..tools.base import TOOLS, ToolContext
from .memory import Session


@dataclass
class Bundle:
    """한 번의 분석에서 나온 도구 결과 모음."""

    stage: int | None
    intent: str
    query: ParsedQuery
    results: list[ToolResult] = field(default_factory=list)
    steps: list[StepLog] = field(default_factory=list)
    stage_output: dict[str, Any] = field(default_factory=dict)
    prereq: dict[int, dict[str, Any]] = field(default_factory=dict)
    ok: bool = True
    message: str | None = None

    # ---- 합치기 (같은 키·ID는 먼저 나온 것을 써요)
    def facts(self) -> list[Fact]:
        seen: dict[str, Fact] = {}
        for r in self.results:
            for f in r.facts:
                seen.setdefault(f.key, f)
        return list(seen.values())

    def fact(self, key: str) -> Fact | None:
        return next((f for f in self.facts() if f.key == key), None)

    def value(self, key: str) -> Any:
        f = self.fact(key)
        return f.value if f else None

    def text(self, key: str, default: str = "-") -> str:
        f = self.fact(key)
        return f.text if f else default

    def evidence(self) -> list[EvidenceTable]:
        seen: dict[str, EvidenceTable] = {}
        for r in self.results:
            for e in r.evidence:
                seen.setdefault(e.id, e)
        return list(seen.values())

    def charts(self) -> list[ChartSpec]:
        return [c for r in self.results for c in r.charts]

    def maps(self) -> list[MapSpec]:
        return [m for r in self.results for m in r.maps]

    def suggestions(self) -> list[Suggestion]:
        return [s for r in self.results for s in r.suggestions]

    def limits(self) -> list[str]:
        out: list[str] = []
        for r in self.results:
            for lim in r.limits:
                if lim and lim not in out:
                    out.append(lim)
        return out

    def badges(self) -> list[Badge]:
        out: dict[str, Badge] = {}
        for r in self.results:
            for b in r.badges:
                out.setdefault(b.label, b)
        return list(out.values())

    def tables(self) -> list[str]:
        out: list[str] = []
        for r in self.results:
            for t in r.tables:
                if t not in out:
                    out.append(t)
        return out

    def period(self) -> str | None:
        ps = list(dict.fromkeys(r.period for r in self.results if r.period))
        return " / ".join(ps) if ps else None

    def result(self, tool: str) -> ToolResult | None:
        return next((r for r in self.results if r.tool == tool), None)


def call(bundle: Bundle | None, ctx: ToolContext, name: str, note: str = "", **kwargs: Any) -> ToolResult:
    """도구 하나를 실행하고 기록을 남겨요. 예외는 실패 결과로 바꿔요 (에이전트가 멈추지 않게)."""
    t0 = time.perf_counter()
    try:
        res = TOOLS[name].fn(ctx, **kwargs)
    except Exception as e:  # noqa: BLE001
        res = ToolResult(tool=name, ok=False, message=f"{name} 실행 중 오류가 났어요: {e}")
    seconds = round(time.perf_counter() - t0, 3)
    progress.emit("tool", tool=name, label=progress.TOOL_LABEL.get(name, name), ok=res.ok, seconds=seconds)
    if bundle is not None:
        bundle.steps.append(StepLog(tool=name, ok=res.ok, seconds=seconds, note=note or (res.message or "")))
        if res.ok or res.facts or res.evidence:
            bundle.results.append(res)
    return res


def _period_kw(q: ParsedQuery) -> dict[str, Any]:
    return {"last_n_months": q.last_n_months, "year": q.year}


# =========================================================================== Stage 1
def stage1_output_for(ctx: ToolContext, q: ParsedQuery, bundle: Bundle | None = None, note: str = "") -> dict[str, Any]:
    """Stage 2·3이 쓸 Stage 1 산출물(유형과 핵심 지표). 유형은 항상 청년(20·30대) 기준이에요."""
    ages = list(ctx.config.analysis.youth_age_bands)
    if q.place_kind == "emd" and q.place_key:
        c = call(bundle, ctx, "s1_classify", note=note, emd_cd=q.place_key, ages=ages, **_period_kw(q))
        if not c.ok:
            return {}
        t = call(bundle, ctx, "s1_trend", note=note, emd_cd=q.place_key, ages=ages, **_period_kw(q))
        row = c.data.get("row", {})
        out = {"place_key": q.place_key, "place_name": q.place_name, "type": c.data.get("type"),
               "near_type": c.data.get("near_type"), "small": c.data.get("small", False), "period": c.period}
        for k in ("youth_resd_chg", "youth_work_chg", "visit_chg", "youth_share", "settle_ratio"):
            out[k] = row.get(k)
        f = t.fact("foreign_resd_chg") if t.ok else None
        out["foreign_resd_chg"] = f.value if f else None
        return out
    if q.place_kind == "zone" and q.place_key:
        g = t1.group_type(ctx, ctx.refs.zone_emds(q.place_key), ages, q.last_n_months, q.year)
        if g:
            return {"place_key": q.place_key, "place_name": q.place_name, "type": g["type"], "near_type": g["near_type"],
                    "period": g["period"], "youth_resd_chg": g["youth_resd_chg"], "youth_work_chg": g["youth_work_chg"],
                    "visit_chg": g["visit_chg"]}
    return {}


def run_stage1(ctx: ToolContext, q: ParsedQuery) -> Bundle:
    b = Bundle(stage=1, intent=q.intent, query=q)
    kw = {"ages": q.ages, **_period_kw(q)}
    if q.place_kind == "emd" and q.place_key and q.intent != "recommend":
        emd = q.place_key
        if q.intent in ("diagnose", "trend", "chain"):
            tr = call(b, ctx, "s1_trend", emd_cd=emd, **kw)
            if not tr.ok:
                b.ok, b.message = False, tr.message
                return b
        c = call(b, ctx, "s1_classify", emd_cd=emd, **kw)
        peers: list[dict[str, Any]] = []
        if q.intent in ("diagnose", "peers", "chain") and c.ok:
            p = call(b, ctx, "s1_peers", emd_cd=emd, **kw)
            peers = p.data.get("peers", []) if p.ok else []
            for m in c.maps:  # 유형 지도에 비슷한 읍면 표시
                for pt in m.points:
                    if any(pt.key == x["emd_cd"] for x in peers):
                        pt.role = "peer"
                if peers:
                    m.title = f"유형 지도 · 비슷한 읍면 {len(peers)}곳" if ctx.refs.emd(emd).area_type == "읍면" else f"유형 지도 · 비슷한 동 {len(peers)}곳"
        if not c.ok and not b.results:
            b.ok, b.message = False, c.message
            return b
        row = c.data.get("row", {}) if c.ok else {}
        tr_res = b.result("s1_trend")
        ff = tr_res.fact("foreign_resd_chg") if tr_res else None
        b.stage_output = {
            "place_key": emd, "place_name": q.place_name, "type": c.data.get("type") if c.ok else None,
            "near_type": c.data.get("near_type") if c.ok else None, "small": c.data.get("small", False) if c.ok else False,
            "ages": q.ages, "period": c.period if c.ok else None, "peers": [x["emd_nm"] for x in peers],
            "foreign_resd_chg": ff.value if ff else None,
            **{k: row.get(k) for k in ("youth_resd_chg", "youth_work_chg", "visit_chg", "youth_share", "settle_ratio")},
        }
        return b
    if q.place_kind == "zone" and q.place_key and q.intent != "recommend":
        z = call(b, ctx, "s1_zone", zone=q.place_key, **kw)
        if not z.ok:
            b.ok, b.message = False, z.message
            return b
        b.stage_output = {"place_key": q.place_key, "place_name": q.place_name, "type": z.data["type"],
                          "near_type": z.data.get("near_type"), "period": z.period, **z.data["row"]}
        return b
    # 추천 순위 / 전체 비교
    city = q.place_key if q.place_kind == "city" else None
    c = call(b, ctx, "s1_classify", emd_cd=None, emd_type=q.emd_type, city=city, **kw)
    if not c.ok:
        b.ok, b.message = False, c.message
        return b
    if q.wants_cause:
        f = t1.overview_correlation(ctx, q.ages, q.last_n_months, q.year)
        if f:
            c.facts.append(f)
    b.intent = "recommend"
    b.stage_output = {"scope": c.data.get("scope"), "top": c.data.get("top", []), "counts": c.data.get("counts", {}),
                      "period": c.period}
    return b


# =========================================================================== Stage 2
def run_stage2(ctx: ToolContext, q: ParsedQuery, session: Session | None = None) -> Bundle:
    b = Bundle(stage=2, intent="shift", query=q)
    s1 = (session.stage_output(q.place_key, 1) if session else None)
    if not s1 or not s1.get("type"):
        s1 = stage1_output_for(ctx, q, b, note="앞 단계(Stage 1) 자동 실행")
        # 앞 단계 도구 결과는 근거로만 남기고 화면 묶음에서는 빼요.
        b.results = [r for r in b.results if not r.tool.startswith("s1_")]
    b.prereq[1] = s1 or {}
    sh = call(b, ctx, "s2_shift", place_kind=q.place_kind, place_key=q.place_key, theme=q.theme, **_period_kw(q))
    if not sh.ok:
        b.ok, b.message = False, sh.message
        return b
    pb = call(b, ctx, "s2_playbook", metrics=sh.data["metrics"], stage1=s1 or {}, spans=sh.data["spans"])
    m = sh.data["metrics"]
    growth = {k: v for k, v in (m.get("cn_growth") or {}).items() if k not in ("전체", "기타") and v is not None}
    top_theme = max(growth, key=growth.get) if growth else None
    b.stage_output = {
        "place_key": q.place_key, "place_name": q.place_name or sh.data["area"]["name"],
        "area_label": sh.data["area"]["area_label"], "type": (s1 or {}).get("type"),
        "target": pb.data.get("target") if pb.ok else None, "group": pb.data.get("group") if pb.ok else None,
        "fired": pb.data.get("fired", []) if pb.ok else [], "top_theme": top_theme,
        "top_theme_growth": growth.get(top_theme) if top_theme else None,
        "peak_dow_cn": m.get("peak_dow_cn"), "peak_dow_kr": m.get("peak_dow_kr"), "nat_top": m.get("nat_top"),
        "period": sh.period,
    }
    return b


# =========================================================================== Stage 3
def run_stage3(ctx: ToolContext, q: ParsedQuery, session: Session | None = None) -> Bundle:
    b = Bundle(stage=3, intent=q.intent if q.intent != "chain" else "plan", query=q)
    intent = b.intent
    emd = q.place_key if q.place_kind == "emd" else None
    s2 = session.stage_output(q.place_key, 2) if session else None
    if s2 is None and emd and intent == "plan":
        pre = run_stage2(ctx, q, session)
        b.steps += [StepLog(tool=s.tool, ok=s.ok, seconds=s.seconds, note="앞 단계(Stage 1·2) 자동 실행") for s in pre.steps]
        s2 = pre.stage_output if pre.ok else {}
        b.prereq[1] = pre.prereq.get(1, {})
    b.prereq[2] = s2 or {}
    kw = {"supply_change": q.supply_change, "elasticity": q.elasticity}
    if intent in ("plan", "forecast"):
        f = call(b, ctx, "s3_forecast", target_month=q.target_month, group=(s2 or {}).get("group"), **kw)
        if not f.ok and intent == "forecast":
            b.ok, b.message = False, f.message
            return b
    sensitive: list[dict[str, Any]] = []
    if emd and intent in ("plan", "routes"):
        r = call(b, ctx, "s3_route_beta", emd_cd=emd, **kw)
        sensitive = r.data.get("sensitive", []) if r.ok else []
        if not r.ok and intent == "routes":
            b.ok, b.message = False, r.message
            return b
    courses: list[dict[str, Any]] = []
    gaps: list[str] = []
    if emd and intent in ("plan", "courses"):
        c = call(b, ctx, "s3_courses", emd_cd=emd, hub_id=q.hub_id)
        courses, gaps = c.data.get("courses", []), c.data.get("gaps", [])
    if not b.results:
        b.ok, b.message = False, "Stage 3 분석에 필요한 자료가 없어요."
        return b
    fc = b.result("s3_forecast")
    b.stage_output = {
        "place_key": q.place_key, "place_name": q.place_name, "target": (s2 or {}).get("target"),
        "supply_change": fc.data.get("supply_change") if fc else None, "elasticity": fc.data.get("elasticity") if fc else None,
        "sensitive_routes": [s["route_no"] for s in sensitive], "courses": [c["text"] for c in courses], "gaps": gaps,
    }
    return b
