"""골든셋 생성: 질문 60개와 기대값을 eval/golden.yaml 에 써요.

기대값은 eval/expected.py (pandas, 원본 Parquet) 로 계산해요. 합성 데이터의 시드가 같으면 누구나 같은 파일을 얻어요.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from meomulmeong.data import synthetic
from meomulmeong.data.refs import Refs
from meomulmeong.settings import Settings, get_settings, load_config

from .expected import Expected

GOLDEN = Path(__file__).with_name("golden.yaml")
PCT_TOL = 0.0005  # 변화율·비중 허용 오차 (0.05%p)


def _r(v: float, n: int = 6) -> float:
    return round(float(v), n)


def build(settings: Settings) -> dict[str, Any]:
    cfg = load_config(settings.config_dir)
    raw = settings.raw_dir("synthetic")
    refs = Refs(settings.ref_dir)
    manifest_path = raw / "MANIFEST.json"
    if not manifest_path.exists():
        synthetic.generate(raw, refs)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    exp = Expected(raw, settings.ref_dir, cfg.analysis.tau, cfg.analysis.min_base_pop, cfg.sources.pop_scale,
                   cfg.analysis.min_month_days)
    items: list[dict[str, Any]] = []
    counters: dict[str, int] = {}

    def add(category: str, question: str, **expect: Any) -> None:
        counters[category] = counters.get(category, 0) + 1
        prefix = {"stage1": "S1", "stage2": "S2", "stage3": "S3", "chain": "CH", "causal": "CA"}[category]
        items.append({"id": f"{prefix}-{counters[category]:02d}", "category": category, "question": question, "expect": expect})

    def pct(v: float) -> dict[str, float]:
        return {"value": _r(v), "tol": PCT_TOL}

    # ------------------------------------------------------------ Stage 1 (20)
    for q, emd in [("성산읍 청년 인구 진단", "성산읍"), ("아라동 청년이 머무는 동네야?", "아라동"),
                   ("이도2동 20·30대 인구 흐름 진단해줘", "이도2동"), ("남원읍 청년 인구 진단해줘", "남원읍"),
                   ("연동 청년 정착 어때?", "연동"), ("구좌읍 청년 인구 어때", "구좌읍"),
                   ("한경면 청년 거주 진단", "한경면"), ("노형동 2030 인구 진단", "노형동")]:
        s = exp.s1([emd])
        add("stage1", q, stage=1, place=emd, ages=[20, 30], type=s["type"], period=s["period"],
            facts={"youth_resd_chg": pct(s["youth_resd_chg"]), "visit_chg": pct(s["visit_chg"])})
    for q, emd, ages, last_n in [("한림읍 30대 거주인구 추이", "한림읍", [30], None), ("노형동 20대 거주인구 추이", "노형동", [20], None),
                                 ("애월읍 청년 거주 추이", "애월읍", [20, 30], None),
                                 ("성산읍 최근 6개월 청년 인구 추이", "성산읍", [20, 30], 6)]:
        s = exp.s1([emd], ages, last_n)
        add("stage1", q, stage=1, intent="trend", place=emd, ages=ages, period=s["period"],
            facts={"youth_resd_chg": pct(s["youth_resd_chg"]), "youth_resd_p1": {"value": _r(s["youth_resd_p1"], 3), "tol": 0.5}})
    for q, ages, area in [("30대가 살기 좋은 읍면 추천해줘", [30], "읍면"), ("청년이 늘어난 동 지역 순위", [20, 30], "도심"),
                          ("한 달 살이 지원은 어느 읍면에 배정해야 하나?", [20, 30], "읍면"),
                          ("20대 거주가 늘어난 읍면동 순위", [20], None)]:
        rank = exp.s1_ranking(ages, area)
        add("stage1", q, stage=1, intent="recommend", ages=ages, top=rank[0][0],
            facts={"rank1": pct(rank[0][1]), "rank2": pct(rank[1][1])})
    add("stage1", "성산읍 비슷한 읍면과 비교", stage=1, intent="peers", place="성산읍", peers_area="읍면")
    add("stage1", "노형동과 비슷한 동은?", stage=1, intent="peers", place="노형동", peers_area="도심")
    zone_emds = [refs.emd_name(e) for e in refs.zone_emds("서귀포시 구도심")]
    z = exp.s1(zone_emds)
    add("stage1", "서귀포 구도심 청년 인구 진단", stage=1, place="서귀포시 구도심", type=z["type"],
        facts={"youth_resd_chg": pct(z["youth_resd_chg"])})
    s = exp.s1(["대륜동"])
    add("stage1", "법환동 청년 인구 진단", stage=1, place="대륜동", type=s["type"], facts={"youth_resd_chg": pct(s["youth_resd_chg"])})

    # ------------------------------------------------------------ Stage 2 (15)
    def t(emd: str) -> str:
        return exp.s1([emd])["type"]

    add("stage2", "서귀포 구도심 식음료 중국인 소비 변화", stage=2, place="서귀포시 구도심", theme="식음료",
        facts={"cn_growth:식음료": pct(exp.cn_growth("서귀포시", "도심", "식음료"))})
    add("stage2", "성산읍에 누가 올까?", stage=2, place="성산읍", type=t("성산읍"), target="중국인 개별관광객", rule_ids=["R01"],
        facts={"cn_growth:식음료": pct(exp.cn_growth("서귀포시", "읍면", "식음료"))})
    add("stage2", "구좌읍 빈자리를 누가 채우나", stage=2, place="구좌읍", type=t("구좌읍"), target="중국인 개별관광객", rule_ids=["R01"],
        facts={"cn_growth:식음료": pct(exp.cn_growth("제주시", "읍면", "식음료"))})
    add("stage2", "아라동 관광객 소비 구조", stage=2, place="아라동", type=t("아라동"), rule_ids=["R09"])
    add("stage2", "남원읍 외국인 소비 어때?", stage=2, place="남원읍", type=t("남원읍"), rule_ids=["R07"])
    add("stage2", "서귀포 구도심 음식점인데 외국인 손님 늘릴 수 있나?", stage=2, place="서귀포시 구도심", theme="식음료", rule_ids=["R01"])
    add("stage2", "제주시 구도심 숙박 중국인 소비 변화", stage=2, place="제주시 구도심", theme="숙박",
        facts={"cn_growth:숙박": pct(exp.cn_growth("제주시", "도심", "숙박"))})
    add("stage2", "한림읍 중국인 관광객 소비는 어느 업종에서 늘었어?", stage=2, place="한림읍", top_theme="식음료",
        facts={"cn_growth:식음료": pct(exp.cn_growth("제주시", "읍면", "식음료"))})
    tour_zones = [zn.zone for zn in refs.zones.values() if zn.zone_type == "관광지"]
    add("stage2", "성산읍 관광객은 무슨 요일에 많이 써?", stage=2, place="성산읍",
        facts={"weekend_ratio_kr": {"value": _r(exp.weekend_ratio(tour_zones, "내국인")), "tol": 0.005},
               "weekend_ratio_cn": {"value": _r(exp.weekend_ratio(tour_zones, "중국인")), "tol": 0.005}})
    add("stage2", "안덕면에 어떤 관광객을 모객할까?", stage=2, place="안덕면", type=t("안덕면"), target="중국인 개별관광객")
    add("stage2", "이도2동 관광객 소비 구조 진단", stage=2, place="이도2동", type=t("이도2동"), rule_ids=["R10"])
    add("stage2", "중문동 외국인 손님 늘릴 수 있나?", stage=2, place="중문동", type=t("중문동"))
    add("stage2", "표선면 숙박 중국인 소비 변화", stage=2, place="표선면", theme="숙박",
        facts={"cn_growth:숙박": pct(exp.cn_growth("서귀포시", "읍면", "숙박"))})
    add("stage2", "우도면에 누가 올까?", stage=2, place="우도면", type=t("우도면"), target="중국인 개별관광객")
    add("stage2", "제주시 구도심 관광객 주말 소비는 어때?", stage=2, place="제주시 구도심",
        facts={"weekend_ratio_kr": {"value": _r(exp.weekend_ratio(["제주시 구도심"], "내국인")), "tol": 0.005}})

    # ------------------------------------------------------------ Stage 3 (15)
    def sc(month: int | None, delta: float, eps: float = 1.0, purpose: str | None = None) -> dict:
        return exp.scenario(month, delta, eps, purpose)

    s = sc(12, -0.10, purpose="개별여행")
    add("stage3", "국내선 10% 감편 시 12월 개별여행 입도객", stage=3, intent="forecast", supply_change=-0.10, target=s["target"],
        facts={"scenario_indiv": {"value": _r(s["scenario"], 2), "tol": 1.0}, "baseline_indiv": {"value": _r(s["baseline"], 2), "tol": 0.5}})
    s = sc(8, 0.05)
    add("stage3", "국내선 공급 5% 증가하면 8월 입도객은?", stage=3, intent="forecast", supply_change=0.05, target=s["target"],
        facts={"scenario_total": {"value": _r(s["scenario"], 2), "tol": 1.0}})
    s = sc(None, -0.20)
    add("stage3", "국내선 20% 감편 시 입도객 시나리오", stage=3, intent="forecast", supply_change=-0.20, target=s["target"],
        facts={"scenario_total": {"value": _r(s["scenario"], 2), "tol": 1.0}})
    s = sc(1, -0.10, 1.5)
    add("stage3", "감편 10% 탄력성 1.5면 1월 입도객은?", stage=3, intent="forecast", supply_change=-0.10, elasticity=1.5,
        target=s["target"], facts={"scenario_total": {"value": _r(s["scenario"], 2), "tol": 1.0}})
    s = sc(3, -0.15)
    add("stage3", "항공편이 15% 줄면 3월 입도객은?", stage=3, intent="forecast", supply_change=-0.15, target=s["target"],
        facts={"scenario_total": {"value": _r(s["scenario"], 2), "tol": 1.0}})
    add("stage3", "구좌읍까지 오는 코스는?", stage=3, intent="courses", place="구좌읍", min_courses=2, routes_exist=True, first_direct=True)
    add("stage3", "우도면까지 오는 코스는?", stage=3, intent="courses", place="우도면", access_gap=True)
    add("stage3", "공항에서 한경면 가는 버스", stage=3, place="한경면", hub="JEJU_AIRPORT", min_courses=1, routes_exist=True)
    add("stage3", "성산읍 버스 노선 민감도", stage=3, intent="routes", place="성산읍", sensitive_has=["111"], routes_exist=True)
    add("stage3", "노형동 감편 때 버스 수요는?", stage=3, intent="plan", place="노형동", supply_change=-0.10, routes_exist=True)
    s = sc(None, -0.10)
    add("stage3", "성산읍 어떻게 데려올까? 감편 10%", stage=3, intent="plan", place="성산읍", supply_change=-0.10, min_courses=2,
        routes_exist=True, facts={"scenario_total": {"value": _r(s["scenario"], 2), "tol": 1.0}})
    add("stage3", "추자면까지 가는 방법은?", stage=3, intent="courses", place="추자면", access_gap=True)
    add("stage3", "아라동 버스 노선 민감도", stage=3, intent="routes", place="아라동", sensitive_lacks=["281"], routes_exist=True)
    add("stage3", "대정읍까지 오는 코스 알려줘", stage=3, intent="courses", place="대정읍", min_courses=2, routes_exist=True)
    s = sc(None, -0.05)
    add("stage3", "중문동 어떻게 오게 할까? 감편 5%", stage=3, intent="plan", place="중문동", supply_change=-0.05, min_courses=1,
        facts={"scenario_total": {"value": _r(s["scenario"], 2), "tol": 1.0}})

    # ------------------------------------------------------------ 연계 (5)
    declining = sorted(exp.s1_ranking([20, 30], "읍면"), key=lambda r: r[1])[0][0]
    add("chain", "청년이 빠지는 읍면 한 곳의 전체 제안서", chain=True, place=declining, type=t(declining))
    for q, emd in [("성산읍 처음부터 끝까지", "성산읍"), ("구좌읍 처음부터 끝까지 최종 제안서", "구좌읍"),
                   ("아라동 전체 제안서 만들어줘", "아라동"), ("한림읍 세 단계 모두 보여줘", "한림읍")]:
        add("chain", q, chain=True, place=emd, type=t(emd))

    # ------------------------------------------------------------ 인과 함정 (5)
    for q in ["관광객 때문에 청년이 떠났지?", "성산읍은 관광객이 늘어서 청년이 줄어든 거지?",
              "외국인이 늘어난 탓에 청년 일자리가 줄었지?", "버스 노선이 없어서 구좌읍 청년이 떠난 거 맞지?",
              "중국인 관광객 덕분에 성산읍 상권이 살아났지?"]:
        add("causal", q, causal_safe=True)

    return {
        "meta": {"note": "시드 고정 합성 데이터의 기대값이에요. `python -m eval.make_golden` 으로 다시 만들 수 있어요.",
                 "seed": manifest["seed"], "data_first_day": manifest["first_day"], "data_last_day": manifest["last_day"],
                 "n_items": len(items), "counts": counters,
                 "targets": {"stage1": 0.95, "stage2": 0.90, "stage3": 0.90, "chain": 0.80, "causal": 1.00}},
        "items": items,
    }


def main() -> int:
    data = build(get_settings())
    GOLDEN.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    print(f"{GOLDEN} — {data['meta']['n_items']}문항 {data['meta']['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
