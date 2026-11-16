import pytest

from meomulmeong.tools import stage3


def test_forecast_arithmetic(ctx):
    f = stage3.s3_forecast(ctx, target_month=12, supply_change=-0.10, elasticity=1.0)
    assert f.ok and f.fact("target_month").text == "2026-12" and f.fact("baseline_month").text == "2025-12"
    base = f.fact("baseline_total").value
    direct = ctx.wh.query("SELECT SUM(visitors) FROM arrivals_purpose_monthly WHERE month = DATE '2025-12-01'").scalar()
    assert base == direct
    assert f.fact("scenario_total").value == pytest.approx(base * 0.9)
    assert f.fact("scenario_total_e0.5").value == pytest.approx(base * 0.95)
    assert f.fact("scenario_total_e1.5").value == pytest.approx(base * 0.85)
    assert f.fact("scenario_indiv").value == pytest.approx(f.fact("baseline_indiv").value * 0.9)
    assert f.evidence[0].columns == ["방문목적", "구분", "기준선", "ε 0.5", "ε 1.0", "ε 1.5"]
    assert f.evidence[0].rows[-1][0] == "합계" and len(f.evidence[0].rows) == 10
    assert f.badges[0].tone == "assumption" and "예측이 아니" in " ".join(f.limits)


def test_forecast_defaults_and_custom_elasticity(ctx):
    f = stage3.s3_forecast(ctx)
    assert f.fact("target_month").text == "2026-11" and f.fact("supply_change").value == -0.10
    g = stage3.s3_forecast(ctx, supply_change=0.05, elasticity=2.0)
    assert "ε 2.0" in g.evidence[0].columns
    assert g.fact("scenario_total").value == pytest.approx(g.fact("baseline_total").value * 1.10)
    floor = stage3.s3_forecast(ctx, supply_change=-0.9, elasticity=1.5)
    assert floor.fact("scenario_total").value == 0  # 음수가 되지 않게


def test_route_beta(ctx, refs):
    emd = refs.find_emd("성산읍").emd_cd
    r = stage3.s3_route_beta(ctx, emd, -0.10, 1.0)
    rows = {row[0]: row for row in r.evidence[0].rows}
    assert set(rows) == {"101", "111", "112", "201"}
    assert rows["111"][6] == "채택" and rows["111"][2] == pytest.approx(0.9, abs=0.2)  # 심어 둔 β 0.9
    assert rows["111"][7] == pytest.approx(0.9 ** rows["111"][2] - 1, abs=1e-3)
    assert r.data["sensitive"][0]["route_no"] == "111"
    # 통근 노선(281)은 관광 민감 노선으로 채택되지 않아요
    ara = stage3.s3_route_beta(ctx, refs.find_emd("아라동").emd_cd)
    assert {row[0]: row[6] for row in ara.evidence[0].rows}["281"] == "미채택"
    assert any("원인을 뜻하지 않" in lim for lim in r.limits)


def test_route_beta_matches_numpy(ctx):
    """PostgreSQL 회귀(regr_slope) 결과를 numpy 로 다시 계산해 대조해요."""
    import numpy as np

    betas, _ = stage3.route_betas(ctx, ["111"])
    rows = ctx.wh.query("""
        SELECT b.riders * 1.0 / b.n_days * date_part('day', b.month + INTERVAL '1 month' - INTERVAL '1 day'), a.visitors
        FROM m_bus_route_month b JOIN arrivals_purpose_monthly a ON a.month = b.month AND a.purpose = '개별여행'
        WHERE b.route_no = '111' ORDER BY b.month""").rows
    y, x = np.log([r[0] for r in rows]), np.log([float(r[1]) for r in rows])
    slope = np.polyfit(x, y, 1)[0]
    assert betas["111"]["beta"] == pytest.approx(slope, rel=1e-6) and betas["111"]["n_months"] == 36


def test_courses_direct_and_diverse(ctx, refs):
    c = stage3.s3_courses(ctx, refs.find_emd("성산읍").emd_cd)
    courses = c.data["courses"]
    assert len(courses) == 3 and all(x["transfers"] == 0 for x in courses)
    assert courses[0]["hub_nm"] == "제주국제공항" and courses[0]["routes"] == ["111"]  # 관광 민감도가 가장 큰 노선 우선
    assert len({tuple(x["routes"]) for x in courses}) == 3  # 코스끼리 노선이 겹치지 않게
    assert c.data["gaps"] == ["제주항 여객터미널"]
    assert all(r in refs.routes for x in courses for r in x["routes"])
    assert len(c.maps[0].lines) == 3


def test_courses_with_transfer_and_gap(ctx, refs):
    seongsan, daejeong = refs.find_emd("성산읍").emd_cd, refs.find_emd("대정읍").emd_cd
    found = stage3.find_courses(ctx, daejeong, seongsan, 1)
    assert found and found[0]["transfers"] == 1 and len(found[0]["legs"]) == 2
    assert found[0]["legs"][0]["to"] == found[0]["legs"][1]["from"]
    assert stage3.find_courses(ctx, daejeong, seongsan, 0) == []
    udo = stage3.s3_courses(ctx, refs.find_emd("우도면").emd_cd)
    assert udo.data["courses"] == [] and "접근성 공백" in (udo.message or "") and udo.badges[0].label == "접근성 공백"


def test_courses_from_given_hub(ctx, refs):
    c = stage3.s3_courses(ctx, refs.find_emd("한경면").emd_cd, hub_id="JEJU_AIRPORT")
    assert [x["hub_id"] for x in c.data["courses"]] == ["JEJU_AIRPORT"] * len(c.data["courses"]) and c.data["courses"]


def test_charts_name_the_bar_that_matters(agent):
    """화면이 강조할 막대를 알 수 있게, 차트 사양에 주인공 항목을 적어 둬요."""
    chain = agent.ask("성산읍 처음부터 끝까지", agent.session())
    by_id = {c.id: c for a in chain.answers for c in a.charts}
    assert by_id["s1_peers"].highlight == "성산읍" and by_id["s1_peers"].x[0] == "성산읍"
    growth = by_id["s2_cn_growth"]
    assert growth.highlight == growth.x[max(range(len(growth.x)), key=lambda i: growth.series[0].y[i])]
    assert by_id["s3_scenario"].highlight == "ε 1.0" and "ε 1.0" in by_id["s3_scenario"].x
    assert by_id["s1_trend"].highlight is None  # 선 차트는 첫 계열이 주인공이에요
    asked = agent.ask("성산읍 숙박 중국인 소비 변화", agent.session())
    assert next(c for c in asked.charts if c.id == "s2_cn_growth").highlight == "숙박"
    eps = agent.ask("성산읍 감편 10% 탄력성 1.5면?", agent.session())
    assert next(c for c in eps.charts if c.id == "s3_scenario").highlight == "ε 1.5"
