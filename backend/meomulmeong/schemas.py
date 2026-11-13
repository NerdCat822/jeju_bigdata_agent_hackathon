"""에이전트 공통 스키마 (pydantic).

화면(React)은 웹 API로 이 모델을 JSON 그대로 받아 그려요: 확인 카드(ConfirmCard) → 답(Answer: 한 줄 결론 · 해설 · 차트/지도 · 근거표 · 한계).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, Field


class BaseModel(_BaseModel):
    """공통 바탕 모델. 기본값이 있는 필드도 응답 명세에서는 '항상 있음'으로 적어요.

    그래야 화면(TypeScript) 쪽 타입에서 charts, evidence 같은 목록이 '없을 수도 있음'으로 나오지 않아요.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

Intent = Literal[
    "diagnose",  # Stage 1 진단 (추이 + 유형 + 유사 읍면)
    "trend",  # Stage 1 추이만
    "recommend",  # Stage 1 추천 순위
    "peers",  # Stage 1 유사 읍면 비교
    "shift",  # Stage 2 관광객 구조 전환 진단 + 제안
    "plan",  # Stage 3 시나리오 + 노선 + 코스
    "forecast",  # Stage 3 수요 시나리오만
    "routes",  # Stage 3 노선 관광 민감도
    "courses",  # Stage 3 코스
    "chain",  # 처음부터 끝까지
    "free",  # 자유 질문 (LLM SQL)
]

INTENT_LABEL: dict[str, str] = {
    "diagnose": "진단", "trend": "추이", "recommend": "추천 순위", "peers": "비슷한 읍면 비교",
    "shift": "관광객 구조 진단", "plan": "수요·노선·코스", "forecast": "수요 시나리오", "routes": "노선 민감도",
    "courses": "코스", "chain": "처음부터 끝까지", "free": "자유 질문",
}
STAGE_TITLE: dict[int, str] = {1: "청년이 머무는 동네", 2: "빈자리를 누가 채우나", 3: "어떻게 오게 하나"}
TYPE_LABEL: dict[str, str] = {"A": "정착 성장형", "B": "출퇴근형", "C": "방문 의존형", "D": "활력 저하형", "유지": "유지형"}
TYPE_MEANING: dict[str, str] = {
    "A": "청년이 살고 일하는 동네", "B": "일자리는 있으나 거주는 약함", "C": "사람은 오지만 머물지 않음",
    "D": "사람도 방문도 줄어듦", "유지": "변화가 작음",
}


class ParsedQuery(BaseModel):
    """질문 해석 결과 (확인 카드에서 고칠 수 있는 값)."""

    question: str = ""
    stage: Literal[1, 2, 3] | None = None
    intent: Intent = "diagnose"
    place_kind: Literal["emd", "zone", "city"] | None = None
    place_key: str | None = None  # 행정동 코드 / 지구명 / 시군구명
    place_name: str | None = None
    auto_place: Literal["declining", "growing"] | None = None  # '청년이 빠지는 읍면 한 곳'처럼 에이전트가 고를 때
    ages: list[int] = Field(default_factory=lambda: [20, 30])
    last_n_months: int | None = None
    year: int | None = None
    theme: str | None = None
    emd_type: Literal["읍면", "동"] | None = None  # 추천 범위
    supply_change: float | None = None  # 국내선 공급 변화율 (예: -0.10)
    elasticity: float | None = None
    target_month: int | None = None  # 1~12
    hub_id: str | None = None
    wants_cause: bool = False  # '왜 줄었어?' 같은 원인 질문
    stage_question: str | None = None  # 연계 실행에서 단계마다 LLM 해설에 넘기는 질문
    notes: list[str] = Field(default_factory=list)
    parsed_by: Literal["rule", "llm"] = "rule"


class Chip(BaseModel):
    label: str
    value: str


class ConfirmCard(BaseModel):
    """'이렇게 이해했어요' 카드."""

    query: ParsedQuery
    chips: list[Chip]
    warnings: list[str] = Field(default_factory=list)
    runnable: bool = True


class Fact(BaseModel):
    """해설에 쓸 수 있는 값 하나. 해설 속 숫자는 모두 여기 또는 근거표에 있어야 해요."""

    key: str
    label: str
    value: float | int | str | None = None
    unit: Literal["pct", "people", "won", "count", "ratio", "text", "index", "month"] = "text"
    text: str = ""
    period: str | None = None
    flag: str | None = None


class EvidenceTable(BaseModel):
    """근거표: 화면에는 표로, 제안서에는 표와 SQL로 들어가요."""

    id: str
    title: str
    columns: list[str]
    rows: list[list[Any]]
    formats: dict[str, str] = Field(default_factory=dict)  # 컬럼 → pct(변화율) / share(비중) / int / num1 / num2 / won
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)
    period: str | None = None
    note: str | None = None


class Series(BaseModel):
    name: str
    y: list[float | None]


class ChartSpec(BaseModel):
    id: str
    kind: Literal["line", "bar", "hbar"]
    title: str
    x: list[str]
    series: list[Series]
    y_title: str = ""
    y_format: Literal["num", "pct", "index", "won"] = "num"
    note: str | None = None
    highlight: str | None = None  # 강조할 가로축 항목 (예: 지금 보는 읍면동). 화면은 그 막대만 강조색으로 그려요

    def to_plotly(self) -> dict[str, Any]:
        """Plotly figure dict (plotly 를 불러오지 않고 만들어요). 화면에서 react-plotly.js 의 data · layout 으로 쓸 수 있어요.

        API 응답에는 차트 사양(x, series, kind, y_format)이 그대로 가요. 화면은 그 사양으로 원하는 차트 라이브러리에 그리면 돼요.
        """
        palette = ["#2f7de1", "#f7941d", "#3aa76d", "#d6453d", "#8e6bbf", "#6b7280"]
        data = []
        for i, s in enumerate(self.series):
            color = palette[i % len(palette)]
            if self.kind == "line":
                data.append({"type": "scatter", "mode": "lines", "name": s.name, "x": self.x, "y": s.y,
                             "line": {"color": color, "width": 3}})
            elif self.kind == "bar":
                data.append({"type": "bar", "name": s.name, "x": self.x, "y": s.y, "marker": {"color": color}})
            else:
                data.append({"type": "bar", "orientation": "h", "name": s.name, "y": self.x, "x": s.y,
                             "marker": {"color": color}})
        tickformat = {"pct": ".0%", "index": ".0f", "won": ",.0f", "num": ",.0f"}[self.y_format]
        value_axis = {"title": {"text": self.y_title}, "tickformat": tickformat}
        layout: dict[str, Any] = {
            "title": {"text": self.title}, "margin": {"l": 50, "r": 20, "t": 50, "b": 40},
            "legend": {"orientation": "h", "y": -0.2}, "template": "plotly_white",
        }
        if self.kind == "hbar":
            layout["xaxis"] = value_axis
            layout["yaxis"] = {"autorange": "reversed"}
        else:
            layout["yaxis"] = value_axis
        return {"data": data, "layout": layout}


class MapPoint(BaseModel):
    key: str
    name: str
    lat: float
    lon: float
    category: str | None = None  # 유형 A~D 등
    value: float | None = None
    role: Literal["target", "peer", "hub", "via", "other"] = "other"


class MapLine(BaseModel):
    label: str
    keys: list[str]  # MapPoint.key 순서


class MapSpec(BaseModel):
    id: str
    title: str
    points: list[MapPoint]
    lines: list[MapLine] = Field(default_factory=list)
    legend: dict[str, str] = Field(default_factory=dict)
    note: str | None = None


class Suggestion(BaseModel):
    rule_id: str
    name: str
    text: str
    target: str | None = None
    evidence_keys: list[str] = Field(default_factory=list)
    evidence_text: list[str] = Field(default_factory=list)


class Badge(BaseModel):
    label: str
    tone: Literal["type", "assumption", "data", "warn", "info"] = "info"


class NextQuestion(BaseModel):
    label: str
    question: str
    kind: Literal["next_stage", "follow_up", "report"] = "follow_up"
    stage: int | None = None


class Check(BaseModel):
    name: str  # numbers / causal / references / suggestions / periods / assumption / export
    passed: bool
    detail: str = ""


class Verification(BaseModel):
    passed: bool = True
    checks: list[Check] = Field(default_factory=list)
    retries: int = 0
    fallback: bool = False  # 검증 실패로 템플릿 해설을 썼는지


class StepLog(BaseModel):
    tool: str
    ok: bool = True
    seconds: float = 0.0
    note: str = ""


class ToolResult(BaseModel):
    """분석 도구 하나의 결과."""

    tool: str
    ok: bool = True
    message: str | None = None
    facts: list[Fact] = Field(default_factory=list)
    evidence: list[EvidenceTable] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    maps: list[MapSpec] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    badges: list[Badge] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    period: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)  # 다음 도구·단계가 쓰는 값

    def fact(self, key: str) -> Fact | None:
        return next((f for f in self.facts if f.key == key), None)


class Answer(BaseModel):
    """질문 하나에 대한 최종 답."""

    id: str
    ok: bool = True
    message: str | None = None
    stage: int | None = None
    intent: str = "diagnose"
    query: ParsedQuery
    headline: str = ""
    explanation: str = ""
    badges: list[Badge] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    evidence: list[EvidenceTable] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    maps: list[MapSpec] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    next_questions: list[NextQuestion] = Field(default_factory=list)
    data_period: str | None = None
    data_badge: str = ""
    llm_mode: str = "template"
    llm_model: str | None = None
    explained_by: Literal["llm", "template"] = "template"
    verification: Verification = Field(default_factory=Verification)
    stage_output: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepLog] = Field(default_factory=list)
    llm_payload: str | None = None  # 클라우드 모드의 '전송 미리보기'
    notices: list[str] = Field(default_factory=list)  # 자동 선택·앞 단계 자동 실행 같은 안내
    elapsed: float = 0.0

    def fact(self, key: str) -> Fact | None:
        return next((f for f in self.facts if f.key == key), None)


class ChainResult(BaseModel):
    """'처음부터 끝까지' 실행 결과: Stage 1 → 2 → 3."""

    place_name: str
    answers: list[Answer]
    report_path: str | None = None
    elapsed: float = 0.0
