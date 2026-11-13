"""데이터 모드: 원본이 없을 때와 센터 추출본(CP949 CSV)을 넣었을 때의 동작."""

import shutil

import pytest

from meomulmeong.data.catalog import Catalog
from meomulmeong.data.warehouse import Warehouse, build_warehouse
from meomulmeong.service import AgentService
from meomulmeong.settings import BACKEND_DIR, Settings, load_config


@pytest.fixture()
def empty_home(tmp_path):
    shutil.copytree(BACKEND_DIR / "config", tmp_path / "config")
    shutil.copytree(BACKEND_DIR / "data" / "ref", tmp_path / "data" / "ref")
    return tmp_path


def _build(home, mode):
    settings = Settings(home=home, data_mode=mode, llm_mode="template", outputs=home / "outputs")
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

    settings = Settings(home=empty_home, data_mode="synthetic")
    with pytest.raises(WarehouseMissing, match="build-data"):
        Warehouse(settings.warehouse_path("synthetic"))


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
    wh = Warehouse(settings.warehouse_path("center"))
    rows = wh.query("SELECT sex, age_band, resd_pop, work_pop, visit_pop FROM pop_kor_emd_daily ORDER BY sex, age_band").rows
    assert rows == [("남", 30, 60.0, 12.0, 0.0), ("여", 20, 360.0, 24.0, 48.0)]  # 시간대 → 하루 평균, 5세 단위 → 10세 단위
    assert wh.query("SELECT route_no, SUM(user_cnt) FROM bus_route_daily GROUP BY 1 ORDER BY 1").rows == [("111", 12), ("999-1", 2)]
    meta = wh.meta()
    assert meta["pop_kor_emd_daily"].source == "center" and meta["bus_route_daily"].source == "center"
    assert wh.data_badge == "센터 데이터" and wh.data_mode == "center"
    wh.close()
