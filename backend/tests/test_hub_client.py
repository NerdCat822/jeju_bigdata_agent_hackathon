"""허브 수집기: 가짜 HTTP 서버로 쪽 넘김·이어받기·쿼터 처리를 시험해요 (실제 API는 호출하지 않아요)."""

import json
from datetime import date

import httpx
import pandas as pd
import pytest
from conftest import make_settings

from meomulmeong.data.catalog import Catalog
from meomulmeong.data.hub_client import HubClient, HubError, _rows, month_windows, parse_days, sample_dates
from meomulmeong.settings import Settings


def make_client(tmp_path, home, handler, max_calls=900, limit=100) -> tuple[HubClient, Catalog, list]:
    settings = Settings(home=tmp_path, hub_project_key="PKEY", data_mode="hub")
    seen: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, **dict(request.url.params)})
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    client = HubClient(settings, max_calls=max_calls, limit=limit, pause=0, client=http, retry_pause=0)
    return client, Catalog.load(home / "config" / "catalog"), seen


def paged(total: int, limit: int, row):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["number"])
        start = (page - 1) * limit
        data = [row(i) for i in range(start, min(start + limit, total))]
        return httpx.Response(200, json={"totCnt": total, "hasMore": start + limit < total, "data": data})
    return handler


def test_requires_project_key(tmp_path):
    with pytest.raises(HubError):
        HubClient(Settings(home=tmp_path, hub_project_key=""))


def test_rows_parsing():
    assert _rows({"totCnt": 3, "hasMore": False, "data": [{"a": 1}]}) == ([{"a": 1}], 3, False)
    assert _rows([{"a": 1}]) == ([{"a": 1}], None, None)
    with pytest.raises(HubError):
        _rows({"message": "project key is invalid"})


def test_month_windows():
    w = month_windows(date(2026, 1, 15), date(2026, 3, 10))
    assert w == [(date(2026, 1, 15), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 28)), (date(2026, 3, 1), date(2026, 3, 10))]


def test_monthly_table_paging(tmp_path, home):
    row = lambda i: {"dtYearMonth": "202501", "visitPurpose": f"목적{i}", "visitorCnt": i}  # noqa: E731
    client, catalog, seen = make_client(tmp_path, home, paged(250, 100, row))
    st = client.fetch_table(catalog.get("arrivals_purpose_monthly"), end=date(2025, 7, 31))
    assert (st.calls, st.rows, st.files) == (3, 250, ["all.parquet"])
    assert seen[0]["path"].endswith("/DtaDa0555D801Da508DbDtt5t1bat1ta/PKEY")
    assert (seen[0]["startDate"], seen[0]["endDate"], seen[0]["limit"]) == ("201601", "202507", "100")
    assert [s["number"] for s in seen] == ["1", "2", "3"]
    df = pd.read_parquet(tmp_path / "data" / "hub" / "arrivals_purpose" / "all.parquet")
    assert len(df) == 250 and list(df.columns) == ["dtYearMonth", "visitPurpose", "visitorCnt"]


def test_daily_table_windows_and_resume(tmp_path, home):
    row = lambda i: {"baseDate": "20250101", "routeName": "111-1", "routeSubName": "x", "moveType": "승차",  # noqa: E731
                     "priceType": "일반", "payType": "카드", "userCount": i}
    client, catalog, seen = make_client(tmp_path, home, paged(150, 100, row), max_calls=3)
    spec = catalog.get("bus_route_daily")
    st = client.fetch_table(spec, date(2025, 1, 1), date(2025, 3, 31))
    assert st.calls == 3 and st.windows_done == 1 and "이어서" in st.stopped  # 호출 상한에서 멈추고 안내
    assert (seen[0]["startDate"], seen[0]["endDate"]) == ("20250101", "20250131")
    raw = tmp_path / "data" / "hub" / "_raw" / "bus_route"
    assert len(list(raw.rglob("*.json"))) == 3  # 받은 쪽은 남겨 둬요
    client2, _, seen2 = make_client(tmp_path, home, paged(150, 100, row))
    st2 = client2.fetch_table(spec, date(2025, 1, 1), date(2025, 3, 31))
    assert st2.windows_skipped == 1 and st2.windows_done == 2 and st2.calls == 3  # 1월은 건너뛰고 2월의 남은 쪽부터
    assert sorted(p.name for p in (tmp_path / "data" / "hub" / "bus_route").glob("*.parquet")) == [
        "202501.parquet", "202502.parquet", "202503.parquet"]


def test_flaky_proxy_is_retried_and_only_successes_count(tmp_path, home):
    """허브 프록시는 502·403 을 섞어 돌려줘요. 다시 보내서 받고, 쿼터에는 성공한 호출만 세요."""
    row = lambda i: {"dtYearMonth": "202501", "visitPurpose": f"목적{i}", "visitorCnt": i}  # noqa: E731
    ok = paged(150, 100, row)
    flips = iter([502, 403, 200, 502, 200])

    def handler(request):
        code = next(flips, 200)
        return ok(request) if code == 200 else httpx.Response(code, text="Internal Server Error")

    client, catalog, seen = make_client(tmp_path, home, handler)
    st = client.fetch_table(catalog.get("arrivals_purpose_monthly"), end=date(2025, 7, 31))
    assert (st.calls, st.failed, st.rows) == (2, 3, 150) and len(seen) == 5


def test_full_quota_stops_with_resume_hint(tmp_path, home):
    """쿼터가 차면 허브는 403 과 'Today's quota is full' 을 돌려줘요. 인증 실패가 아니라 내일 이어 받으라고 알려요."""
    client, catalog, seen = make_client(tmp_path, home, lambda r: httpx.Response(403, text="Today's quota is full"))
    st = client.fetch_table(catalog.get("bus_route_daily"), date(2025, 1, 1), date(2025, 1, 31), days=[9, 25])
    assert "쿼터" in st.stopped and "이어서" in st.stopped and len(seen) == 1


def test_sampled_days(tmp_path, home):
    assert parse_days("1,9,17,25") == [1, 9, 17, 25] and parse_days("1-3, 9") == [1, 2, 3, 9] and parse_days("") is None
    with pytest.raises(ValueError):
        parse_days("0,40")
    got = sample_dates(date(2025, 1, 5), date(2025, 2, 28), [1, 9, 30])
    assert got == [date(2025, 1, 9), date(2025, 1, 30), date(2025, 2, 1), date(2025, 2, 9)]  # 2월 30일은 없어요
    row = lambda i: {"baseDate": "20250109", "routeName": "111-1", "routeSubName": "x", "moveType": "승차",  # noqa: E731
                     "priceType": "일반", "payType": "카드", "userCount": i}
    client, catalog, seen = make_client(tmp_path, home, paged(5, 100, row))
    st = client.fetch_table(catalog.get("bus_route_daily"), date(2025, 1, 1), date(2025, 2, 28), days=[9])
    assert [(x["startDate"], x["endDate"]) for x in seen] == [("20250109", "20250109"), ("20250209", "20250209")]
    assert st.files == ["20250109.parquet", "20250209.parquet"]


def test_one_broken_day_does_not_stop_the_rest(tmp_path, home):
    """허브가 특정 날짜만 계속 500 을 내면 그날만 건너뛰고 나머지는 받아요."""
    row = lambda i: {"baseDate": "x", "routeName": "111-1", "routeSubName": "x", "moveType": "승차",  # noqa: E731
                     "priceType": "일반", "payType": "카드", "userCount": i}
    ok = paged(3, 100, row)

    def handler(request):
        if request.url.params["startDate"] == "20250109":
            return httpx.Response(500, text="Internal Server Error")
        return ok(request)

    client, catalog, _ = make_client(tmp_path, home, handler)
    st = client.fetch_table(catalog.get("bus_route_daily"), date(2025, 1, 1), date(2025, 2, 28), days=[9, 25])
    assert st.errors == ["20250109"] and st.files == ["20250125.parquet", "20250209.parquet", "20250225.parquet"]


def test_auth_error_message(tmp_path, home):
    client, catalog, _ = make_client(tmp_path, home, lambda r: httpx.Response(403, json={}))
    with pytest.raises(HubError, match="프로젝트 담기"):
        client.fetch_table(catalog.get("arrivals_purpose_monthly"))


def test_fetched_files_load_into_warehouse(tmp_path, home):
    """수집 → 적재가 이어지는지: 허브 형식 응답을 받아 표준 테이블로 올려요."""
    import shutil

    from meomulmeong.data.warehouse import Warehouse, build_warehouse
    from meomulmeong.settings import load_config

    shutil.copytree(home / "config", tmp_path / "config")
    shutil.copytree(home / "data" / "ref", tmp_path / "data" / "ref")
    rows = [{"baseDate": "20250105", "city": "서귀포시", "emd": "성산읍", "gender": "여", "ageGroup": "20대",
             "resdPop": "2400", "workPop": "240", "visitPop": "4800"},
            {"baseDate": "20250105", "city": "제주시", "emd": "회천동", "gender": "남", "ageGroup": "10세미만",
             "resdPop": 240, "workPop": 0, "visitPop": 24},
            {"baseDate": "20250105", "city": "제주시", "emd": "없는동", "gender": "남", "ageGroup": "30대",
             "resdPop": 1, "workPop": 1, "visitPop": 1}]
    client, catalog, _ = make_client(tmp_path, home, lambda r: httpx.Response(200, text=json.dumps({"totCnt": 3, "data": rows})))
    client.fetch_table(catalog.get("pop_kor_emd_daily"), date(2025, 1, 1), date(2025, 1, 31))
    settings = make_settings(tmp_path, data_mode="hub")
    report = build_warehouse(settings, load_config(settings.config_dir), catalog, "hub")
    wh = Warehouse(settings, "hub")
    got = wh.query("SELECT emd_cd, sex, age_band, resd_pop FROM pop_kor_emd_daily ORDER BY emd_cd").rows
    assert [(r[0], r[1], r[2], round(r[3])) for r in got] == [("50110620", "남", 0, 10), ("50130259", "여", 20, 100)]
    assert wh.data_badge == "실데이터"
    assert ("pop_kor_emd_daily", "행정동 미연결", "제주시 없는동", 1) in report.issues  # 연결하지 못한 이름은 보고
    assert any(issue == "원본 없음" for _t, issue, _d, _n in report.issues)
    wh.close()
