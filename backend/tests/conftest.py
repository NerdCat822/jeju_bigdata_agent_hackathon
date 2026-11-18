"""테스트 공통 준비: 임시 폴더에 합성 데이터를 만들고, PostgreSQL 의 테스트 전용 스키마에 데이터 창고를 올려요.

개발용 스키마(synthetic · hub · center)는 건드리지 않아요. 테스트가 만드는 스키마는 모두 `mt<프로세스 번호>_` 로
시작하고, 끝나면 지워요. PostgreSQL 이 떠 있어야 해요: `docker compose up -d db`
"""

from __future__ import annotations

import itertools
import os
import shutil
from pathlib import Path

import pytest

from meomulmeong.data import synthetic
from meomulmeong.data.catalog import Catalog
from meomulmeong.data.refs import Refs
from meomulmeong.data.warehouse import WarehouseUnreachable, build_warehouse, connect
from meomulmeong.service import AgentService
from meomulmeong.settings import BACKEND_DIR, Settings, load_config

_PREFIX = f"mt{os.getpid()}_"
_counter = itertools.count(1)
# 접두어 없이 만든 Settings 도 개발용 스키마를 건드리지 못하게, 아무도 만들지 않는 스키마를 가리키게 해요.
os.environ["MEOMUL_PG_SCHEMA_PREFIX"] = f"{_PREFIX}0_"
# 이 PC 의 .env 에 지도 키가 있어도 테스트는 네이버를 부르지 않아요 (지도 테스트는 가짜 전송 계층을 써요)
os.environ["MEOMUL_NAVER_MAPS"] = "false"


def make_settings(home: Path, **kw) -> Settings:
    """데이터 폴더(home)마다 따로 쓰는 스키마 접두어를 붙인 설정을 만들어요."""
    return Settings(home=home, pg_schema_prefix=f"{_PREFIX}{next(_counter)}_", **kw)


def _drop_schemas(pattern: str) -> None:
    con = connect(Settings())
    try:
        with con.cursor() as cur:
            cur.execute("SELECT nspname FROM pg_namespace WHERE nspname ~ %s", [pattern])
            for (name,) in cur.fetchall():
                cur.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    finally:
        con.close()


@pytest.fixture(scope="session", autouse=True)
def _test_schemas():
    try:
        _drop_schemas(r"^mt[0-9]+_")  # 지난 실행이 남긴 스키마
    except WarehouseUnreachable as e:
        pytest.exit(f"테스트에는 PostgreSQL 이 필요해요.\n{e}", returncode=2)
    yield
    _drop_schemas(f"^{_PREFIX}")


@pytest.fixture(scope="session")
def home(tmp_path_factory) -> Path:
    home = tmp_path_factory.mktemp("meomul_home")
    shutil.copytree(BACKEND_DIR / "config", home / "config")
    shutil.copytree(BACKEND_DIR / "data" / "ref", home / "data" / "ref")
    return home


@pytest.fixture(scope="session")
def settings(home: Path) -> Settings:
    return make_settings(home, data_mode="synthetic", llm_mode="template", outputs=home / "outputs")


@pytest.fixture(scope="session")
def refs(settings: Settings) -> Refs:
    return Refs(settings.ref_dir)


@pytest.fixture(scope="session")
def manifest(settings: Settings, refs: Refs) -> dict:
    m = synthetic.generate(settings.raw_dir("synthetic"), refs)
    build_warehouse(settings, load_config(settings.config_dir), Catalog.load(settings.catalog_dir), "synthetic")
    return m


@pytest.fixture(scope="session")
def svc(settings: Settings, manifest: dict) -> AgentService:
    return AgentService.create("synthetic", "template", settings=settings)


@pytest.fixture()
def agent(svc: AgentService):
    return svc.agent


@pytest.fixture()
def ctx(svc: AgentService):
    return svc.agent.ctx.new_request()
