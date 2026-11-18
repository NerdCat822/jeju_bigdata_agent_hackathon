"""데이터 모드: 원본이 없을 때, 센터 추출본(CP949 CSV)을 넣었을 때, 내보낸 표(CSV)를 넣었을 때의 동작."""

import shutil

import pytest
from conftest import make_settings

from meomulmeong.data.catalog import Catalog
from meomulmeong.data.warehouse import Warehouse, build_warehouse, export_csv
from meomulmeong.service import AgentService
from meomulmeong.settings import BACKEND_DIR, load_config
from meomulmeong.tools import stage2


@pytest.fixture()
def empty_home(tmp_path):
    shutil.copytree(BACKEND_DIR / "config", tmp_path / "config")
    shutil.copytree(BACKEND_DIR / "data" / "ref", tmp_path / "data" / "ref")
    return tmp_path


def _build(home, mode):
    settings = make_settings(home, data_mode=mode, llm_mode="template", outputs=home / "outputs")
    report = build_warehouse(settings, load_config(settings.config_dir), Catalog.load(settings.catalog_dir), mode)
    return settings, report


def test_hub_mode_without_data_explains_itself(empty_home):
    settings, report = _build(empty_home, "hub")
    assert all(t.n_rows == 0 for t in report.tables) and len(report.issues) == 8
    assert "원본 없음" in report.summary()
    svc = AgentService.create("hub", "template", settings=settings)
    for q, word in (("성산읍 청년 인구 진단", "자료가 없어"), ("성산읍에 누가 올까?", "자료가 없어"),
                    ("국내선 10% 감편 시 입도객은?", "자료가 없어")):
        a = svc.agent.ask(q, svc.agent.session())
        assert not a.ok and word in a.message, q  # 멈추지 않고 무엇이 없는지 알려요
    chain = svc.run_chain("성산읍")
    assert [a.ok for a in chain.answers[:2]] == [False, False]
    courses = svc.agent.ask("성산읍까지 오는 코스는?", svc.agent.session())
    assert courses.ok and courses.stage_output["courses"]  # 코스는 참조표만으로 답할 수 있어요


def test_missing_warehouse_message(empty_home):
    from meomulmeong.data.warehouse import WarehouseMissing

    settings = make_settings(empty_home, data_mode="synthetic")
    with pytest.raises(WarehouseMissing, match="build-data"):
        Warehouse(settings, "synthetic")


def test_center_csv_is_loaded_with_column_mapping(empty_home):
    """센터 명세서(4-11 유동인구 v02, 3-02 버스 노선별 이용) 형식의 CP949 CSV를 표준 테이블로 올려요."""
    center = empty_home / "data" / "center"
    center.mkdir(parents=True)
    pop = ["base_date,pt_year,pt_month,time,dstrct_se,emd_cd,emd_nm,sex,age,resd_pop_cnt,work_pop_cnt,visit_pop_cnt,resd"]
    for hour in range(1, 25):  # 하루 24개 시각
        pop.append(f"20250601,2025,6,{hour},서귀포시 동부,50130259,서귀포시 성산읍,여성,2024,120.0,24.0,48.0,제주")
        pop.append(f"20250601,2025,6,{hour},서귀포시 동부,50130259,서귀포시 성산읍,여성,2529,240.0,0,0,제주")  # 25~29세 → 20대
        pop.append(f"20250601,2025,6,{hour},서귀포시 동부,50130259,서귀포시 성산읍,남성,30,60.0,12.0,0,그외")    # KT 10세 단위
    (center / "tb_population_korean_emd_new_202506.csv").write_text("\n".join(pop), encoding="cp949")
    bus = ["base_date,pt_year,pt_month,day_of_week,base_hour,bus_route_id,bus_route_name,get_on_off_type,user_category,pay_type,user_count",
           "20250601,2025,6,일,08,21270000,111-2(성산항~제주국제공항),승차,일반,카드,7",
           "20250601,2025,6,일,09,21270000,111-2(성산항~제주국제공항),승차,일반,카드,5",
           "20250601,2025,6,일,09,21279999,999-1(없는 노선),환승,경로,카드,2"]
    (center / "tb_bus_route_usage_202506.csv").write_text("\n".join(bus), encoding="cp949")
    settings, report = _build(empty_home, "center")
    wh = Warehouse(settings, "center")
    rows = wh.query("SELECT sex, age_band, resd_pop, work_pop, visit_pop FROM pop_kor_emd_daily ORDER BY sex, age_band").rows
    assert rows == [("남", 30, 60.0, 12.0, 0.0), ("여", 20, 360.0, 24.0, 48.0)]  # 시간대 → 하루 평균, 5세 단위 → 10세 단위
    assert wh.query("SELECT route_no, SUM(user_cnt) FROM bus_route_daily GROUP BY 1 ORDER BY 1").rows == [("111", 12), ("999-1", 2)]
    meta = wh.meta()
    assert meta["pop_kor_emd_daily"].source == "center" and meta["bus_route_daily"].source == "center"
    assert wh.data_badge == "센터 데이터" and wh.data_mode == "center"
    wh.close()


def test_exported_tables_are_loaded_as_they_are(empty_home, settings, manifest):
    """다른 PC 에서 export-csv 로 내보낸 폴더(data/export/hub/)를 그대로 옮기면, 수집본 없이도 같은 창고가 만들어져요."""
    export_csv(settings, "synthetic", empty_home / "data" / "export" / "hub")
    hub_settings, report = _build(empty_home, "hub")
    assert report.issues == [] and len(report.tables) == 8
    assert all(t.source == "hub" and t.n_rows > 0 and "내보낸 표" in t.note for t in report.tables)
    src, dst = Warehouse(settings, "synthetic"), Warehouse(hub_settings, "hub")
    try:
        for table in src.meta():  # 표준 테이블은 값 하나까지 같아요
            sql = f"SELECT COUNT(*), SUM(hashtext(t::text)::bigint) FROM {table} AS t"  # 행 순서와 상관없는 지문
            assert dst.query(sql).rows == src.query(sql).rows, table
        # 월 집계는 올린 표에서 다시 계산해요. 실수는 더하는 순서에 따라 끝자리가 달라질 수 있어 합계는 근삿값으로 봐요.
        for mart, cols in (("m_pop_kor_emd_month", "resd_sum, work_sum, visit_sum, n_days"),
                           ("m_pop_for_long_emd_month", "resd_sum, work_sum, visit_sum, n_days"),
                           ("m_bus_route_month", "riders, n_days")):
            sql = f"SELECT COUNT(*), {', '.join(f'SUM({c})' for c in cols.split(', '))} FROM {mart}"
            assert dst.query(sql).rows[0] == pytest.approx(src.query(sql).rows[0], rel=1e-9), mart
        assert dst.meta()["pop_kor_emd_daily"].max_date == src.meta()["pop_kor_emd_daily"].max_date
        assert dst.data_badge == "실데이터" and dst.data_mode == "hub"
    finally:
        src.close()
        dst.close()


def test_collected_data_wins_over_exported_tables(empty_home):
    """수집본과 내보낸 표가 둘 다 있으면 수집본을 써요."""
    out = empty_home / "data" / "export" / "hub"
    out.mkdir(parents=True)
    (out / "arrivals_purpose_monthly.csv").write_text("month,purpose,visitors\n2025-06-01,내보낸표,99\n", encoding="utf-8")
    raw = empty_home / "data" / "hub" / "arrivals_purpose"
    raw.mkdir(parents=True)
    (raw / "part.csv").write_text("dtYearMonth,visitPurpose,visitorCnt\n202506,관광,3\n202506,관광,4\n", encoding="utf-8")
    settings, report = _build(empty_home, "hub")
    meta = {t.table: t for t in report.tables}["arrivals_purpose_monthly"]
    assert meta.n_rows == 1 and meta.note == ""
    wh = Warehouse(settings, "hub")
    assert wh.query("SELECT purpose, visitors FROM arrivals_purpose_monthly").rows == [("관광", 7)]
    wh.close()


def test_exported_table_with_wrong_columns_is_rejected(empty_home):
    out = empty_home / "data" / "export" / "hub"
    out.mkdir(parents=True)
    (out / "arrivals_purpose_monthly.csv").write_text("month,purpose\n2025-06-01,관광\n", encoding="utf-8")
    with pytest.raises(ValueError, match="표준 컬럼이 빠졌어요.*visitors"):
        _build(empty_home, "hub")


def test_card_file_is_loaded_jeju_wide_and_stage2_uses_it(empty_home, refs):
    """허브 파일 '업종별 성별 카드 이용 정보'(data/hub/card_biz/)는 내보낸 표보다 먼저 쓰고, 제주 전체 단위로 올려요.
    동네가 속한 시군구·도심/읍면 값이 없으니 2단계는 제주 전체 값을 쓰고 그렇다고 밝혀요."""
    out = empty_home / "data" / "export" / "hub"
    out.mkdir(parents=True)
    (out / "card_cn_area_monthly.csv").write_text(
        "month,city,area_type,theme,user_cnt,use_cnt,use_amt\n2018-12-01,서귀포시,읍면,숙박,1,1,1\n", encoding="utf-8")
    raw = empty_home / "data" / "hub" / "card_biz"
    raw.mkdir(parents=True)
    rows = ["base_year_month,biz_nm,user_type,sex,user_count,use_count,use_amount"]
    for k in range(24):  # 2023-07 ~ 2025-06
        y, m = 2023 + (6 + k) // 12, (6 + k) % 12 + 1
        p1 = (y, m) >= (2024, 7)
        rows += [f"{y}{m:02d},면세점,중국,여성,10,10,{200 if p1 else 100}",
                 f"{y}{m:02d},면세점,중국,남성,10,10,{100 if p1 else 50}",
                 f"{y}{m:02d},한식 음식점업,중국,여성,5,5,{90 if p1 else 100}",
                 f"{y}{m:02d},여행사업,중국,여성,1,1,{50 if p1 else 1}",  # 직전 비중 0.4% → 증가율을 빼요
                 f"{y}{m:02d},면세점,일본,여성,10,10,999"]
    (raw / "업종별성별카드이용정보.csv").write_text("\ufeff" + "\n".join(rows) + "\n", encoding="utf-8")
    settings, report = _build(empty_home, "hub")
    meta = {t.table: t for t in report.tables}["card_cn_area_monthly"]
    assert (meta.n_rows, meta.note, meta.source_title) == (72, "", "업종별 성별 카드 이용 정보")
    svc = AgentService.create("hub", "template", settings=settings)
    ctx = svc.agent.ctx.new_request()
    assert ctx.wh.query("SELECT DISTINCT city, area_type FROM card_cn_area_monthly").rows == [("제주 전체", "전체")]
    sh = stage2.s2_shift(ctx, "emd", refs.find_emd("성산읍").emd_cd)
    assert sh.fact("area").text == "제주 전체"
    assert sh.fact("cn_growth:쇼핑·소매").value == pytest.approx(1.0)  # (200 + 100) ÷ (100 + 50) − 1
    assert sh.fact("cn_growth:식음료").value == pytest.approx(-0.1)
    assert sh.fact("cn_growth:전체").period == "2024-07~2025-06 vs 2023-07~2024-06"
    assert any("제주 전체 단위" in lim for lim in sh.limits)
    assert sh.fact("cn_growth:기타") is None and sh.fact("cn_share:기타") is not None  # 작은 비중: 증가율만 빼요
    assert any("기타 소비는 직전 기간 비중이 1%보다 작아" in lim for lim in sh.limits)
    assert "기타" not in sh.charts[0].x
    assert "제주 전체 × 테마" in sh.evidence[0].note
