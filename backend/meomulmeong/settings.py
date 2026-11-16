"""실행 설정: 환경변수(.env)와 config/settings.yaml 을 읽어요."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(os.environ.get("MEOMUL_HOME") or Path(__file__).resolve().parents[1]).resolve()

DataMode = Literal["synthetic", "hub", "center"]
LlmMode = Literal["template", "anthropic"]

DATA_BADGE = {"synthetic": "샘플 데이터", "hub": "실데이터", "center": "센터 데이터"}


def _load_dotenv(path: Path) -> None:
    """.env 의 값을 프로세스 환경변수로 올려요. 빈 값과 이미 설정된 키는 건드리지 않아요.

    빈 ANTHROPIC_API_KEY 가 다른 인증 수단을 가리는 일을 막으려고 빈 값은 건너뛰어요.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BACKEND_DIR / ".env")


class AnalysisCfg(BaseModel):
    youth_age_bands: list[int] = Field(default_factory=lambda: [20, 30])
    tau: float = 0.03
    period_months: int = 12
    min_month_days: int = 20
    min_month_days_hub: int = 2  # 허브는 쿼터 때문에 달마다 며칠만 받아요 (fetch-hub --days)
    min_period_months: int = 9
    min_base_pop: float = 100.0
    peers_k: int = 3


class Stage2Cfg(BaseModel):
    min_share_for_growth: float = 0.03
    max_suggestions: int = 3


class Stage3Cfg(BaseModel):
    elasticity_default: float = 1.0
    elasticity_grid: list[float] = Field(default_factory=lambda: [0.5, 1.0, 1.5])
    supply_change_default: float = -0.10
    beta_min_r2: float = 0.5
    beta_min_months: int = 12
    max_courses: int = 3
    max_transfers: int = 1


class VerifyCfg(BaseModel):
    max_retries: int = 2
    number_rel_tol: float = 0.005


class LlmCfg(BaseModel):
    explain: bool = True  # False 면 해설은 항상 규칙 문장(템플릿), LLM은 질문 해석과 자유 질문에만 써요
    evidence_max_rows: int = 40
    explain_budget_seconds: float = 45.0  # 해설 쓰기에 이만큼 쓰고도 통과하지 못하면 더 다시 쓰지 않고 템플릿 해설로 대체 (0 이면 한도 없음)
    # 목록이 들어가는 답(추천 순위, 코스, 시나리오·노선·코스를 함께 보여 주는 Stage 3 전체 계획)은 LLM 모드에서도 규칙 문장을 써요.
    template_only_intents: list[str] = ["recommend", "courses", "plan"]


class SourcesCfg(BaseModel):
    pop_scale: float = 1.0 / 24.0


class AppConfig(BaseModel):
    """config/settings.yaml 내용. 센터 담당자가 코드 없이 바꾸는 값이에요."""

    analysis: AnalysisCfg = Field(default_factory=AnalysisCfg)
    stage2: Stage2Cfg = Field(default_factory=Stage2Cfg)
    stage3: Stage3Cfg = Field(default_factory=Stage3Cfg)
    verify: VerifyCfg = Field(default_factory=VerifyCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)
    sources: SourcesCfg = Field(default_factory=SourcesCfg)


class Settings(BaseSettings):
    """환경변수 MEOMUL_* 로 바꾸는 실행 설정."""

    model_config = SettingsConfigDict(
        env_prefix="MEOMUL_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # .env.example 을 그대로 복사해 값이 빈 항목은 기본값을 써요
        extra="ignore",
    )

    data_mode: DataMode = "synthetic"
    llm_mode: LlmMode = "template"

    anthropic_model: str = "claude-opus-5-5"

    hub_project_key: str = ""
    hub_base_url: str = "https://open.jejudatahub.net/api/proxy"

    # 웹 API 서버 (React 화면이 붙는 곳). 기본은 이 PC 안에서만 열려요.
    api_host: str = "127.0.0.1"
    api_port: int = 8501
    # 개발할 때 React 개발 서버(다른 포트)에서 API를 부를 수 있게 허용하는 주소 (쉼표로 구분)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
    web_dist: Path | None = None  # 빌드한 React 화면 폴더 (기본: ../frontend/dist)

    home: Path = BACKEND_DIR
    outputs: Path | None = None  # 제안서·실행 기록 폴더 (기본: home/outputs)

    # ---- 경로 ----
    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def catalog_dir(self) -> Path:
        return self.config_dir / "catalog"

    @property
    def ref_dir(self) -> Path:
        return self.home / "data" / "ref"

    def raw_dir(self, mode: DataMode | None = None) -> Path:
        return self.home / "data" / (mode or self.data_mode)

    def warehouse_path(self, mode: DataMode | None = None) -> Path:
        return self.home / "data" / "warehouse" / f"meomul_{mode or self.data_mode}.duckdb"

    @property
    def outputs_dir(self) -> Path:
        return self.outputs or (self.home / "outputs")

    @property
    def data_badge(self) -> str:
        return DATA_BADGE[self.data_mode]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_config(config_dir: Path | None = None) -> AppConfig:
    """config/settings.yaml 을 읽어요. 파일이 없으면 기본값을 써요."""
    path = (config_dir or get_settings().config_dir) / "settings.yaml"
    if not path.exists():
        return AppConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)
