"""LLM 공급자 공통 인터페이스. 모든 호출은 JSON 스키마(pydantic 모델)를 강제해요."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """LLM 호출 실패 (연결·인증·형식 오류, 거절). 에이전트는 이 오류를 받으면 템플릿으로 대체해요."""


class LLMFormatError(LLMError):
    """응답은 왔지만 형식(JSON 스키마)에 맞지 않을 때. 길이 제한에 걸려 잘린 경우가 많아요."""


@dataclass
class LLMUsage:
    calls: int = 0
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    log: list[dict] = field(default_factory=list)


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""
    is_cloud: bool = False

    def __init__(self) -> None:
        self.usage = LLMUsage()

    @abstractmethod
    def generate(self, system: str, user: str, out: type[T], *, purpose: str = "", model: str | None = None,
                 effort: str = "low") -> T:
        """system·user 프롬프트를 보내고 out 스키마에 맞는 객체를 돌려줘요. effort 는 모델의 사고 깊이예요."""

    @abstractmethod
    def check(self) -> tuple[bool, str]:
        """(사용 가능 여부, 설명)."""


# ---- LLM 출력 스키마 (모든 필드가 필수, 추가 필드 금지)
class ExplainOut(BaseModel):
    """준비된 분석의 해설. 한 줄 결론은 규칙이 만들고, LLM은 쉬운 해설만 써요."""

    model_config = ConfigDict(extra="forbid")
    explanation: str


class FreeExplainOut(BaseModel):
    """자유 질문(LLM SQL)의 결과 설명."""

    model_config = ConfigDict(extra="forbid")
    headline: str
    explanation: str


class ParseOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal[1, 2, 3] | None
    intent: Literal["diagnose", "trend", "recommend", "peers", "shift", "plan", "forecast", "routes", "courses", "chain", "free"]
    place: str | None
    ages: list[int]
    last_n_months: int | None
    year: int | None
    theme: str | None
    supply_change_pct: float | None
    elasticity: float | None
    target_month: int | None
    wants_cause: bool


class SqlOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    sql: str
