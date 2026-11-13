"""테스트 공통 준비: 임시 폴더에 합성 데이터와 데이터 창고를 새로 만들어요 (개발용 data/ 는 건드리지 않아요)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from meomulmeong.data import synthetic
from meomulmeong.data.catalog import Catalog
from meomulmeong.data.refs import Refs
from meomulmeong.data.warehouse import build_warehouse
from meomulmeong.service import AgentService
from meomulmeong.settings import BACKEND_DIR, Settings, load_config


@pytest.fixture(scope="session")
def home(tmp_path_factory) -> Path:
    home = tmp_path_factory.mktemp("meomul_home")
    shutil.copytree(BACKEND_DIR / "config", home / "config")
    shutil.copytree(BACKEND_DIR / "data" / "ref", home / "data" / "ref")
    return home


@pytest.fixture(scope="session")
def settings(home: Path) -> Settings:
    return Settings(home=home, data_mode="synthetic", llm_mode="template", outputs=home / "outputs")


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
