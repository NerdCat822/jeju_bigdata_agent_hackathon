"""실행 설정: 환경변수(.env)와 config/settings.yaml 을 읽어요."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field
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
        populate_by_name=True,  # 별칭이 있는 항목도 Settings(naver_map_client_id=...) 처럼 이름으로 넣을 수 있게
    )

    data_mode: DataMode = "synthetic"
    llm_mode: LlmMode = "template"

    anthropic_model: str = "claude-opus-5-5"

    hub_project_key: str = ""

    # 네이버 클라우드 Maps (선택). 화면의 지도, 주소 찾기, 코스 도로 경로, 제안서 위치 지도에만 써요. 비우면 기본 지도로 그려요.
    # 콘솔에서 복사한 이름(NAVER_CLOUD_PLATFORM_CLIENT_*)도 그대로 읽어요. Secret 은 서버 밖으로 내보내지 않아요.
    naver_maps: bool = True  # False 면 키가 있어도 쓰지 않아요 (테스트, 인터넷이 없는 센터 PC)
    naver_map_client_id: str = Field(default="", validation_alias=AliasChoices(
        "MEOMUL_NAVER_MAP_CLIENT_ID", "NAVER_CLOUD_PLATFORM_CLIENT_ID", "naver_map_client_id"))
    naver_map_client_secret: str = Field(default="", validation_alias=AliasChoices(
        "MEOMUL_NAVER_MAP_CLIENT_SECRET", "NAVER_CLOUD_PLATFORM_CLIENT_SECRET", "naver_map_client_secret"))
    hub_base_url: str = "https://open.jejudatahub.net/api/proxy"

    # 데이터 창고 (PostgreSQL). 기본값은 docker-compose.yml 의 db 서비스에 맞춰 두었어요.
    pg_host: str = "127.0.0.1"
    pg_port: int = 5434
    pg_db: str = "meomul"
    pg_user: str = "meomul"
    pg_password: str = "meomul"  # 이 PC 안에서만 여는 개발·시연용 기본값이에요. 바꾸려면 MEOMUL_PG_PASSWORD
    pg_schema_prefix: str = ""  # 스키마 이름 앞에 붙여요 (테스트가 개발용 데이터를 건드리지 않게)

    # 웹 API 서버 (React 화면이 붙는 곳). 기본은 이 PC 안에서만 열려요.
    api_host: str = "127.0.0.1"
    api_port: int = 8501
    # 개발할 때 React 개발 서버(다른 포트)에서 API를 부를 수 있게 허용하는 주소 (쉼표로 구분)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
    web_dist: Path | None = None  # 빌드한 React 화면 폴더 (기본: ../frontend/dist)
    # 여러 사람이 같은 주소로 들어오는 배포본에서 켜요. 모드 전환은 서버 전체에 걸려서, 한 사람이 바꾸면 모두의 화면이 바뀌어요.
    lock_modes: bool = False  # True 면 데이터·AI 설명 방식을 바꾸는 API 를 막고, 화면은 지금 모드를 읽기 전용으로 보여 줘요
    api_docs: bool = True  # False 면 /docs · /redoc · /openapi.json 을 열지 않아요 (공개 주소에 둘 때)

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

    def export_dir(self, mode: DataMode | None = None) -> Path:
        """export-csv 가 CSV 를 내보내는 폴더 (저장소에 올리지 않아요)."""
        return self.home / "data" / "export" / (mode or self.data_mode)

    # ---- 데이터 창고 ----
    def pg_schema(self, mode: DataMode | None = None) -> str:
        """데이터 모드마다 스키마 하나를 써요: synthetic · hub · center."""
        return f"{self.pg_schema_prefix}{mode or self.data_mode}"

    @property
    def pg_conninfo(self) -> str:
        from psycopg.conninfo import make_conninfo

        return make_conninfo(host=self.pg_host, port=self.pg_port, dbname=self.pg_db, user=self.pg_user,
                             password=self.pg_password, connect_timeout=5, application_name="meomulmeong")

    @property
    def pg_label(self) -> str:
        """화면과 안내 문구에 쓰는 접속 위치 (암호는 넣지 않아요)."""
        return f"PostgreSQL {self.pg_host}:{self.pg_port}/{self.pg_db}"

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
