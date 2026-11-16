import pytest

from meomulmeong.data.warehouse import SqlRejected


def test_tables_loaded(ctx, manifest):
    meta = ctx.wh.meta()
    assert set(meta) == {"pop_kor_emd_daily", "pop_for_long_emd_daily", "card_zone_dow_monthly", "card_cn_area_monthly",
                         "spend_tour_type_monthly", "foreign_visitors_monthly", "arrivals_purpose_monthly", "bus_route_daily"}
    assert all(m.n_rows > 0 and m.source == "synthetic" for m in meta.values())
    assert ctx.wh.data_badge == "샘플 데이터"
    assert meta["pop_kor_emd_daily"].n_rows == manifest["rows"]["pop_kor_emd"]
    assert ctx.wh.issues() == []  # 행정동으로 연결하지 못한 이름이 없어야 해요


def test_standardized_values(ctx):
    q = ctx.wh.query
    assert q("SELECT COUNT(DISTINCT emd_cd) FROM pop_kor_emd_daily").scalar() == 43
    assert {r[0] for r in q("SELECT DISTINCT age_band FROM pop_kor_emd_daily").rows} == {0, 10, 20, 30, 40, 50, 60, 70}
    assert {r[0] for r in q("SELECT DISTINCT sex FROM pop_kor_emd_daily").rows} == {"남", "여"}
    assert {r[0] for r in q("SELECT DISTINCT theme FROM card_cn_area_monthly").rows} == {
        "식음료", "숙박", "쇼핑·소매", "교통", "문화·레저", "기타"}  # '전체' 행은 빼고 6개 테마로 정렬
    assert {r[0] for r in q("SELECT DISTINCT user_type FROM card_zone_dow_monthly").rows} == {"내국인", "중국인"}
    assert q("SELECT COUNT(DISTINCT route_no) FROM bus_route_daily").scalar() == 13  # 방향(-1, -2)을 노선 번호로 합침
    assert len(ctx.wh.valid_months("pop_kor_emd_daily")) == 36


def test_weekday_calendar(ctx):
    rows = dict(ctx.wh.query("SELECT dow, n_days FROM ref_month_dow WHERE month = DATE '2026-10-01'").rows)
    assert sum(rows.values()) == 31 and rows["목"] == 5 and rows["월"] == 4  # 2026-10-01은 목요일


@pytest.mark.parametrize("sql", [
    "DROP TABLE ref_emd",
    "SELECT 1; SELECT 2",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM secret_table",
    "SELECT * FROM pg_settings",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT emd_nm INTO copy_of_emd FROM ref_emd",
    "SELECT * FROM ref_emd, pg_catalog.pg_user",
    "INSERT INTO ref_emd SELECT * FROM ref_emd",
    "COPY ref_emd TO 'out.csv'",
])
def test_guard_rejects(ctx, sql):
    with pytest.raises(SqlRejected):
        ctx.wh.run_guarded(sql)


def test_guard_allows_select_and_limits_rows(ctx):
    res = ctx.wh.run_guarded("WITH x AS (SELECT emd_nm FROM ref_emd) SELECT * FROM x ORDER BY 1", max_rows=5)
    assert len(res) == 5
    res = ctx.wh.run_guarded("SELECT emd_nm FROM ref_emd WHERE emd_nm = 'drop table x; --'")
    assert len(res) == 0  # 문자열 안의 키워드는 문제 삼지 않아요
