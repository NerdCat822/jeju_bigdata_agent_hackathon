"""실데이터와 같은 수록 기간에서의 동작.

허브 공개 데이터는 수록 기간이 서로 달라요 (카드 2016-09~2018-12, 입도객 ~2025-07, 유동인구·버스는 최근까지).
합성 데이터의 날짜만 그 기간으로 옮긴 '허브 모드' 창고를 만들어, 기간이 어긋나도 멈추지 않고 사실대로 알리는지 확인해요.
"""

import shutil

import pandas as pd
import pytest

from meomulmeong.data import synthetic
from meomulmeong.data.catalog import Catalog
from meomulmeong.data.refs import Refs
from meomulmeong.data.warehouse import build_warehouse
from meomulmeong.schemas import ChainResult
from meomulmeong.service import AgentService
from meomulmeong.settings import BACKEND_DIR, Settings, load_config


def _shift(path, col: str, first: str, keep: int) -> None:
    """월 컬럼을 first(YYYYMM)부터 시작하도록 옮기고 앞의 keep 개월만 남겨요."""
    df = pd.read_parquet(path)
    months = sorted(df[col].astype(str).unique())[:keep]
    y, m = int(first[:4]), int(first[4:])
    new = {}
    for old in months:
        new[old] = f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    df = df[df[col].astype(str).isin(months)].copy()
    df[col] = df[col].astype(str).map(new)
    df.to_parquet(path, index=False)


@pytest.fixture(scope="module")
def hub_svc(tmp_path_factory):
    home = tmp_path_factory.mktemp("hub_home")
    shutil.copytree(BACKEND_DIR / "config", home / "config")
    shutil.copytree(BACKEND_DIR / "data" / "ref", home / "data" / "ref")
    settings = Settings(home=home, data_mode="hub", llm_mode="template", outputs=home / "outputs")
    hub = settings.raw_dir("hub")
    synthetic.generate(hub, Refs(settings.ref_dir))
    _shift(hub / "card_cn_area" / "synthetic.parquet", "dtYearMonth", "201609", 28)     # 2016-09~2018-12
    _shift(hub / "card_zone_dow" / "synthetic.parquet", "dtYearMonth", "201609", 15)    # 2016-09~2017-11
    _shift(hub / "spend_tour_type" / "synthetic.parquet", "dtYearMonth", "201609", 15)  # 2016-09~2017-11
    _shift(hub / "arrivals_purpose" / "synthetic.parquet", "dtYearMonth", "202208", 36)  # ~2025-07
    _shift(hub / "foreign_visitors" / "synthetic.parquet", "dtYearMonth", "202208", 36)
    build_warehouse(settings, load_config(settings.config_dir), Catalog.load(settings.catalog_dir), "hub")
    return AgentService.create("hub", "template", settings=settings)


def test_periods_are_reported_per_table(hub_svc):
    tables = {t["table"]: t["period"] for t in hub_svc.status()["tables"]}
    assert tables["card_cn_area_monthly"] == "2016-09-01~2018-12-01"
    assert tables["arrivals_purpose_monthly"] == "2022-08-01~2025-07-01"
    assert hub_svc.status()["data_badge"] == "실데이터"


def test_chain_survives_mismatched_periods(hub_svc):
    result = hub_svc.agent.ask("성산읍 처음부터 끝까지", hub_svc.agent.session())
    assert isinstance(result, ChainResult)
    a1, a2, a3 = result.answers
    assert all(a.ok and a.verification.passed for a in result.answers), [a.message for a in result.answers]
    assert a1.stage_output["type"] == "C" and a1.data_badge == "실데이터"
    # Stage 2: 카드(2018)와 단체/개별 소비(2017)의 기간이 겹치지 않으면 그 규칙은 적용하지 않고 알려요
    rules = {r[0]: r[3] for e in a2.evidence if e.id == "s2_rules" for r in e.rows}
    assert rules["R01"] == "기간이 겹치지 않아 함께 볼 수 없음"
    assert any("기간이 겹치지 않아" in lim for lim in a2.limits)
    assert "R02" in a2.stage_output["fired"]  # 한 테이블만 쓰는 규칙은 그대로 적용
    assert "2018-01~2018-12" in a2.data_period  # 답마다 데이터 기간을 밝혀요
    # 요일별 카드는 15개월뿐이라 전년 동월 비교로 바뀌어요
    assert any("전년 동월 비교" in lim for lim in a1.limits + a2.limits)
    # Stage 3: 기준선은 자료가 있는 전년 동월, 회귀는 버스와 입도객이 겹치는 달만
    assert a3.fact("target_month").text == "2025-08" and a3.fact("baseline_month").text == "2024-08"
    routes = next(e for e in a3.evidence if e.id == "s3_routes")
    assert all(row[4] == 21 for row in routes.rows)  # 2023-11~2025-07, 21개월


def test_short_history_gives_single_period(hub_svc, tmp_path):
    """1년 전 자료가 없으면 변화율과 유형을 지어내지 않고 이유를 알려요."""
    from meomulmeong.data.periods import resolve_period

    months = hub_svc.agent.ctx.wh.valid_months("pop_kor_emd_daily")[-8:]
    p = resolve_period(months)
    assert p.mode == "single" and "비교할 수 없어요" in p.note
