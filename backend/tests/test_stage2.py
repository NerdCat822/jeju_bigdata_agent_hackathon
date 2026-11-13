import pytest

from meomulmeong.tools import stage1, stage2


def _stage1_out(ctx, emd):
    c = stage1.s1_classify(ctx, emd)
    t = stage1.s1_trend(ctx, emd)
    out = dict(c.data["row"])
    out["type"] = c.data["type"]
    out["foreign_resd_chg"] = t.fact("foreign_resd_chg").value
    return out


def test_resolve_area(ctx, refs):
    a = stage2.resolve_area(ctx, "emd", refs.find_emd("성산읍").emd_cd)
    assert (a["city"], a["area_type"], a["zone_direct"]) == ("서귀포시", "읍면", False)
    z = stage2.resolve_area(ctx, "zone", "서귀포시 구도심")
    assert (z["city"], z["area_type"], z["zones"]) == ("서귀포시", "도심", ["서귀포시 구도심"]) and len(z["emd_cds"]) == 4
    assert stage2.resolve_area(ctx, None, None)["area_label"] == "제주 전체"


def test_shift_metrics(ctx, refs):
    sh = stage2.s2_shift(ctx, "emd", refs.find_emd("성산읍").emd_cd)
    m = sh.data["metrics"]
    assert sh.ok and set(m["cn_growth"]) == {"식음료", "숙박", "쇼핑·소매", "교통", "문화·레저", "기타", "전체"}
    assert m["cn_growth"]["식음료"] == pytest.approx(0.28, abs=0.03)  # 합성 데이터에 심은 서귀포시 읍면 식음료 +28%
    assert sum(v for k, v in m["cn_share"].items()) == pytest.approx(1.0, abs=1e-6)
    assert m["indiv_ratio_cn"]["식음료"] == pytest.approx(85000 / 60000, rel=0.03)
    assert m["weekend_ratio_kr"] > 1.2 > 1.0 > m["weekend_ratio_cn"]
    assert m["peak_dow_kr"] == "토" and m["nat_top"] == "대만"
    assert {e.id for e in sh.evidence} == {"s2_cn_theme", "s2_indiv", "dow", "s2_nationality"}
    assert all(e.sql for e in sh.evidence)
    assert any("참고" in lim for lim in sh.limits)  # 카드 지구에 직접 속하지 않는 읍면동


def test_cn_growth_matches_direct_sql(ctx, refs):
    """테마 증가율을 다른 경로(직접 SQL)로 다시 계산해 대조해요."""
    sh = stage2.s2_shift(ctx, "emd", refs.find_emd("구좌읍").emd_cd)
    p = ctx.period("card_cn_area_monthly")
    row = ctx.wh.query(f"""
        SELECT SUM(use_amt) FILTER (WHERE {p.sql_p1()}) * 1.0 / SUM(use_amt) FILTER (WHERE {p.sql_p0()}) - 1
        FROM card_cn_area_monthly WHERE city = '제주시' AND area_type = '읍면' AND theme = '숙박'""").scalar()
    assert sh.data["metrics"]["cn_growth"]["숙박"] == pytest.approx(row)


def test_playbook_for_type_c(ctx, refs):
    emd = refs.find_emd("성산읍").emd_cd
    sh = stage2.s2_shift(ctx, "emd", emd)
    pb = stage2.s2_playbook(ctx, sh.data["metrics"], _stage1_out(ctx, emd), sh.data["spans"])
    assert pb.data["fired"][0] == "R01" and pb.data["target"] == "중국인 개별관광객" and pb.data["group"] == "개별"
    assert len(pb.suggestions) == ctx.config.stage2.max_suggestions
    assert all(s.rule_id and s.evidence_text for s in pb.suggestions)  # 제안마다 규칙 ID와 근거
    assert len(pb.evidence[0].rows) == 12
    skipped = [r for r in pb.evidence[0].rows if r[3] == "유형이 달라 건너뜀"]
    assert {r[0] for r in skipped} >= {"R07", "R09", "R10", "R12"}


def test_playbook_for_type_a_and_d(ctx, refs):
    for name, expect in (("아라동", "R09"), ("남원읍", "R07")):
        emd = refs.find_emd(name).emd_cd
        sh = stage2.s2_shift(ctx, "emd", emd)
        pb = stage2.s2_playbook(ctx, sh.data["metrics"], _stage1_out(ctx, emd), sh.data["spans"])
        assert expect in pb.data["fired"], name


def test_rule_engine_any_theme_and_missing(ctx):
    metrics = {"indiv_ratio_kr": {"식음료": 1.1, "숙박": 1.6, "교통": 1.3}, "cn_growth": {"식음료": None}}
    pb = stage2.s2_playbook(ctx, metrics, {"type": "C"}, {})
    r08 = next(s for s in pb.suggestions if s.rule_id == "R08")
    assert "숙박" in r08.text and r08.evidence_keys == ["indiv_ratio_kr:숙박"]  # 조건을 만족하는 테마 중 값이 가장 큰 것
    rows = {r[0]: r[3] for r in pb.evidence[0].rows}
    assert rows["R01"] == "자료 없음" and rows["R04"] == "자료 없음" and rows["R08"] == "충족"


def test_rule_skipped_when_periods_do_not_overlap(ctx):
    metrics = {"cn_growth": {"식음료": 0.3}, "indiv_ratio_cn": {"식음료": 1.4}}
    spans = {"cn_growth": ("2016-09-01", "2018-12-01"), "indiv_ratio_cn": ("2024-01-01", "2025-07-01")}
    pb = stage2.s2_playbook(ctx, metrics, {"type": "C"}, spans)
    rows = {r[0]: r[3] for r in pb.evidence[0].rows}
    assert rows["R01"] == "기간이 겹치지 않아 함께 볼 수 없음" and "R01" not in pb.data["fired"]
    assert any("R01" in lim for lim in pb.limits)


def test_playbook_without_type_applies_all(ctx):
    pb = stage2.s2_playbook(ctx, {"cn_growth": {"숙박": 0.2}}, {}, {})
    assert "R02" in pb.data["fired"] and any("유형이 없어" in lim for lim in pb.limits)


def test_maintained_type_uses_nearest_type_rules(ctx):
    """유지형은 가장 가까운 유형의 규칙을 참고로 적용하고, 그 사실을 알려요."""
    metrics = {"cn_growth": {"숙박": 0.2}}
    none = stage2.s2_playbook(ctx, metrics, {"type": "유지"}, {})
    assert "R02" not in none.data["fired"]
    near = stage2.s2_playbook(ctx, metrics, {"type": "유지", "near_type": "C"}, {})
    assert "R02" in near.data["fired"] and any("가장 가까운 유형(C 방문 의존형)" in lim for lim in near.limits)
    assert near.fact("near_type").value == "C"
