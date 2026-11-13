import pytest

from meomulmeong.data import synthetic
from meomulmeong.tools import stage1


@pytest.mark.parametrize("resd,work,visit,expected", [
    (0.05, 0.01, 0.00, "A"),
    (0.03, 0.00, -0.02, "A"),   # 경계값 포함 (거주 ≥ +τ, 근무 ≥ 0)
    (0.05, -0.01, 0.00, "유지"),  # 거주는 늘었지만 근무가 줄면 A가 아니에요
    (0.01, 0.04, 0.00, "B"),
    (-0.05, 0.04, 0.02, "B"),   # 위에서부터 먼저 맞는 유형: B가 C보다 먼저
    (-0.04, 0.00, 0.00, "C"),
    (-0.04, -0.01, -0.001, "D"),
    (-0.02, 0.02, 0.05, "유지"),
])
def test_classify_type(resd, work, visit, expected):
    assert stage1.classify_type(resd, work, visit, 0.03) == expected


def test_classify_needs_all_values():
    assert stage1.classify_type(None, 0.1, 0.1, 0.03) is None


def test_nearest_type():
    assert stage1.nearest_type(-0.025, 0.0, 0.05, 0.03) == "C"
    assert stage1.nearest_type(0.025, 0.01, 0.0, 0.03) == "A"


def test_all_types_match_planted_patterns(ctx, refs):
    """합성 데이터에 심어 둔 숨은 유형을 SQL 지표와 분류 규칙이 그대로 찾아내야 해요."""
    rows, period, _ = stage1.metrics_all(ctx, [20, 30], stage1._req(None, None))
    latent = synthetic.latent_types(refs)
    assert period.mode == "rolling" and len(rows) == 43
    assert {r["emd_nm"]: r["type"] for r in rows} == latent


def test_trend_seongsan(ctx, refs):
    emd = refs.find_emd("성산읍").emd_cd
    t = stage1.s1_trend(ctx, emd)
    assert t.ok and len(t.charts[0].x) == 24
    resd = t.fact("youth_resd_chg").value
    p1, p0 = t.fact("youth_resd_p1").value, t.fact("youth_resd_p0").value
    assert resd == pytest.approx(p1 / p0 - 1) and -0.09 <= resd <= -0.05  # 심어 둔 C형 범위
    assert 0.04 <= t.fact("visit_chg").value <= 0.10
    assert {"youth_share", "settle_ratio", "foreign_resd_chg", "weekend_ratio"} <= {f.key for f in t.facts}
    assert t.fact("weekend_ratio").flag == "proxy_zone"  # 성산읍은 카드 지구에 직접 속하지 않아요
    assert any("참고" in lim for lim in t.limits)
    assert all(e.sql for e in t.evidence)  # 모든 근거표에 SQL


def test_classify_and_peers(ctx, refs):
    emd = refs.find_emd("성산읍").emd_cd
    c = stage1.s1_classify(ctx, emd)
    assert c.data["type"] == "C" and c.badges[0].label == "유형 C"
    assert [r[2] for r in c.evidence[0].rows] == ["아니오", "아니오", "예", "아니오"]
    target = [p for p in c.maps[0].points if p.role == "target"]
    assert len(c.maps[0].points) == 43 and [p.name for p in target] == ["성산읍"]
    p = stage1.s1_peers(ctx, emd)
    peers = p.data["peers"]
    assert len(peers) == 3 and all(refs.emds[x["emd_cd"]].area_type == "읍면" for x in peers)
    assert "성산읍" not in [x["emd_nm"] for x in peers]


def test_small_sample_is_flagged_and_excluded(ctx, refs):
    chuja = refs.find_emd("추자면").emd_cd
    c = stage1.s1_classify(ctx, chuja)
    assert c.data["small"] and any(b.label == "작은 표본" for b in c.badges)
    rank = stage1.s1_classify(ctx, None, emd_type="읍면")
    names = [r[1] for r in rank.evidence[0].rows]
    assert "추자면" not in names and rank.data["excluded_small"] == ["추자면"]
    assert all(refs.find_emd(n).area_type == "읍면" for n in names)
    changes = [r[3] for r in rank.evidence[0].rows]
    assert changes == sorted(changes, reverse=True)


def test_age_subset_and_zone(ctx, refs):
    emd = refs.find_emd("한림읍").emd_cd
    t30 = stage1.s1_trend(ctx, emd, ages=[30])
    t2030 = stage1.s1_trend(ctx, emd, ages=[20, 30])
    assert t30.fact("youth_resd_p1").value < t2030.fact("youth_resd_p1").value
    assert "30대" in t30.fact("youth_resd_chg").label
    z = stage1.s1_zone(ctx, "서귀포시 구도심")
    assert z.ok and z.data["type"] in ("A", "B", "C", "D", "유지") and len(z.evidence[0].rows) == 5
    assert not stage1.s1_zone(ctx, "내국인 주요 관광지").ok  # 읍면동과 대응하지 않는 지구


def test_shorter_period_request(ctx, refs):
    emd = refs.find_emd("성산읍").emd_cd
    t = stage1.s1_trend(ctx, emd, last_n_months=6)
    assert t.period == "2026-05~2026-10 vs 2025-05~2025-10" and len(t.charts[0].x) == 18
