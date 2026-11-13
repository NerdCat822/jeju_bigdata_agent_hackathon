from datetime import date

import pytest

from meomulmeong.data.periods import PeriodRequest, add_months, month_range, overlap, resolve_period


# ---------------------------------------------------------------- 참조표·장소 표준화
def test_refs_cover_43_emds(refs):
    assert len(refs.emds) == 43
    assert sum(1 for e in refs.emds.values() if e.city == "제주시") == 26
    assert sum(1 for e in refs.emds.values() if e.area_type == "읍면") == 12
    assert {e.region7 for e in refs.emds.values()} == {
        "제주시 동부", "제주시 서부", "제주시 중부(동)", "제주시 중부(서)", "서귀포시 동부", "서귀포시 중부", "서귀포시 서부"}


@pytest.mark.parametrize("text,kind,name", [
    ("성산읍 청년 인구 왜 줄었어?", "emd", "성산읍"),
    ("서귀포 구도심 음식점인데 외국인 손님", "zone", "서귀포시 구도심"),
    ("법환동 어때", "emd", "대륜동"),  # 법정동 → 행정동
    ("일도일동 청년", "emd", "일도1동"),
    ("서귀포시 전체로 보면", "city", "서귀포시"),
])
def test_resolve_place(refs, text, kind, name):
    m = refs.resolve_place(text)
    assert m is not None and (m.kind, m.name) == (kind, name)


def test_place_false_positive_and_ambiguity(refs):
    assert refs.find_places("두 지표가 연동되나요?") == []  # '연동'은 동 이름이지만 여기서는 일반 단어
    assert [m.name for m in refs.find_places("연동 20대는?")] == ["연동"]
    assert refs.find_places("월평동")[0].ambiguous  # 제주시·서귀포시 양쪽에 있는 법정동
    m = [x for x in refs.find_places("서귀포 월평동") if x.kind == "emd"][0]
    assert (m.name, m.ambiguous) == ("대천동", False)


def test_zones_hubs_routes(refs):
    assert refs.zone_of(refs.find_emd("정방동").emd_cd) == "서귀포시 구도심"
    assert [direct for _, direct in refs.card_zones_for(refs.find_emd("성산읍").emd_cd)] == [False, False]
    assert refs.find_theme("음식점 손님") == "식음료" and refs.find_theme("호텔 예약") == "숙박"
    assert "111" in refs.routes_through(refs.find_emd("성산읍").emd_cd)
    assert all(e in refs.emds for r in refs.routes for e in refs.route_emds(r))
    assert all(h.emd_cd in refs.emds for h in refs.hubs.values())


# ---------------------------------------------------------------- 기간
def _months(start: date, n: int) -> list[date]:
    return [add_months(start, i) for i in range(n)]


def test_add_months_and_range():
    assert add_months(date(2025, 11, 1), 2) == date(2026, 1, 1)
    assert add_months(date(2026, 1, 1), -13) == date(2024, 12, 1)
    assert len(month_range(date(2024, 11, 1), date(2025, 10, 1))) == 12


def test_period_rolling_default():
    p = resolve_period(_months(date(2023, 11, 1), 36))
    assert p.mode == "rolling" and p.label == "2025-11~2026-10 vs 2024-11~2025-10"
    assert p.sql_p1() == "month BETWEEN DATE '2025-11-01' AND DATE '2026-10-01'"


def test_period_falls_back_to_yoy_when_short():
    p = resolve_period(_months(date(2025, 3, 1), 18))  # 18개월뿐
    assert p.mode == "yoy" and p.comparable
    assert (p.p1_start, p.p1_end) == (date(2026, 3, 1), date(2026, 8, 1))
    assert "전년 동월" in (p.note or "")


def test_period_single_when_no_prior_year():
    p = resolve_period(_months(date(2026, 1, 1), 8))
    assert p.mode == "single" and not p.comparable and p.sql_p0() == "FALSE"


def test_period_requests():
    months = _months(date(2023, 11, 1), 36)
    six = resolve_period(months, PeriodRequest(last_n_months=6))
    assert six.p1_label == "2026-05~2026-10" and six.p0_label == "2025-05~2025-10" and six.mode == "yoy"
    year = resolve_period(months, PeriodRequest(year=2025))
    assert year.p1_label == "2025-01~2025-12" and year.p0_label == "2024-01~2024-12"
    with pytest.raises(ValueError):
        resolve_period(months, PeriodRequest(year=2019))


def test_overlap():
    a = (date(2016, 9, 1), date(2018, 12, 1))
    assert overlap(a, (date(2018, 1, 1), date(2025, 7, 1))) == (date(2018, 1, 1), date(2018, 12, 1))
    assert overlap(a, (date(2021, 8, 1), date(2025, 7, 1))) is None  # 함께 볼 수 없음
