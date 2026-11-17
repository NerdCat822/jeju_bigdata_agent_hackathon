"""웹 API 서버. React 화면은 여기로 질문을 보내고 답(JSON)을 받아 그려요.

    python -m meomulmeong serve                 # http://127.0.0.1:8501  (API 문서: /docs)

    GET  /api/bootstrap                         첫 화면에 필요한 것 한 번에 (상태 · 읍면동 · 추천 질문 · 선택지)
    POST /api/understand   {question}           확인 카드 ("이렇게 이해했어요")
    POST /api/confirm      {query}              고친 해석으로 확인 카드 다시 만들기
    POST /api/run          {query}              확인 카드의 해석을 실행 → 답
    POST /api/ask          {question}           질문 한 줄을 바로 실행 (연계 실행 포함)
    POST /api/chain        {place}              읍면동 하나를 Stage 1 → 2 → 3
    POST /api/…/stream                          위 셋의 스트리밍판 (진행 상황과 단계별 답을 SSE 로 보내요)
    POST /api/reports      {session_id}         최종 제안서 만들기 → GET /api/reports/{filename}
    POST /api/modes        {data_mode, llm_mode}  데이터 · LLM 모드 바꾸기

분석은 한 번에 하나씩 실행해요. 센터 PC 한 대에서 한 사람이 쓰는 도구라서요.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import Field

from .. import fmt, progress
from ..agent.orchestrator import _INTENT_STAGE
from ..data.warehouse import WarehouseMissing, warehouse_exists
from ..maps import MapsUnavailable, NaverMaps, in_jeju
from ..schemas import (
    INTENT_LABEL,
    STAGE_TITLE,
    TYPE_LABEL,
    TYPE_MEANING,
    Answer,
    BaseModel,
    ChainResult,
    ConfirmCard,
    ParsedQuery,
)
from ..service import TEMPLATE_LABEL, AgentService
from ..settings import DATA_BADGE, DataMode, LlmMode, Settings, get_settings

SESSION_ID = r"^[A-Za-z0-9_-]{1,64}$"


# =========================================================================== 요청 · 응답 모양
class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str | None = Field(default=None, pattern=SESSION_ID)


class QueryIn(BaseModel):
    query: ParsedQuery
    session_id: str | None = Field(default=None, pattern=SESSION_ID)


class ChainIn(BaseModel):
    place: str = Field(min_length=1, max_length=40, description="읍면동 이름 (예: 성산읍)")
    session_id: str | None = Field(default=None, pattern=SESSION_ID)
    with_report: bool = False


class ReportIn(BaseModel):
    session_id: str = Field(pattern=SESSION_ID)
    place: str | None = Field(default=None, max_length=40)


class ConsentIn(BaseModel):
    consent: bool


class ModesIn(BaseModel):
    data_mode: DataMode | None = None
    llm_mode: LlmMode | None = None


class SessionOut(BaseModel):
    session_id: str


class ConsentOut(BaseModel):
    session_id: str
    consent: bool


class CardOut(BaseModel):
    session_id: str
    card: ConfirmCard


class AnswerOut(BaseModel):
    session_id: str
    answer: Answer


class ChainOut(BaseModel):
    session_id: str
    chain: ChainResult
    report_url: str | None = None


class AskOut(BaseModel):
    """kind 가 answer 면 answer 에, chain 이면 chain 에 결과가 있어요."""

    session_id: str
    kind: Literal["answer", "chain"]
    answer: Answer | None = None
    chain: ChainResult | None = None
    report_url: str | None = None


class ReportOut(BaseModel):
    filename: str
    url: str


class HealthOut(BaseModel):
    ok: bool = True
    ready: bool
    message: str | None = None


class TableInfo(BaseModel):
    table: str
    title: str
    rows: int
    source: str
    period: str


class DataIssue(BaseModel):
    table_name: str
    issue: str
    detail: str | None = None
    n: int | None = None


class ModeOption(BaseModel):
    mode: str
    label: str
    available: bool = Field(description="지금 고를 수 있는지 (클라우드 LLM은 API 키가 있어야 해요)")
    current: bool


class ModesOut(BaseModel):
    data: list[ModeOption]
    llm: list[ModeOption]
    locked: bool = Field(default=False, description="배포본처럼 모드가 정해져 있어 바꿀 수 없는지 (MEOMUL_LOCK_MODES)")


class StatusOut(BaseModel):
    data_mode: str
    data_badge: str
    built_at: str | None = None
    llm_mode: str
    llm_model: str | None = None
    llm_label: str
    llm_note: str = ""
    tables: list[TableInfo]
    issues: list[DataIssue]
    route_ref: str | None = None
    modes: ModesOut


class PlaceOut(BaseModel):
    emd_cd: str
    emd_nm: str
    city: str
    area_type: str
    region7: str
    lat: float
    lon: float


class StageInfo(BaseModel):
    stage: int
    title: str


class TypeInfo(BaseModel):
    code: str
    label: str
    meaning: str


class HubInfo(BaseModel):
    hub_id: str
    hub_nm: str
    hub_type: str
    lat: float
    lon: float


class ZoneInfo(BaseModel):
    zone: str
    zone_type: str


class OptionsOut(BaseModel):
    """확인 카드에서 고를 수 있는 값과 화면 범례."""

    stages: list[StageInfo]
    intents: dict[str, str]
    intent_stage: dict[str, int]
    types: list[TypeInfo]
    themes: list[str]
    hubs: list[HubInfo]
    zones: list[ZoneInfo]
    age_bands: list[int]
    youth_age_bands: list[int]
    period_months: int
    elasticity_grid: list[float]
    elasticity_default: float
    supply_change_default: float


class SuggestedGroup(BaseModel):
    stage: int
    title: str
    questions: list[str]


class BootstrapOut(BaseModel):
    status: StatusOut
    places: list[PlaceOut]
    suggested: list[SuggestedGroup]
    options: OptionsOut
    naver_map_key_id: str | None = Field(default=None, description="화면에서 네이버 지도를 띄울 Client ID. 없으면 기본 지도로 그려요")


# =========================================================================== 지도 (네이버 클라우드 Maps, 선택)
class MapPlaceOut(BaseModel):
    emd_cd: str
    emd_nm: str


class AddressOut(BaseModel):
    address: str = Field(description="도로명 주소 (없으면 지번 주소)")
    jibun: str
    lat: float
    lon: float
    emd_cd: str | None = Field(default=None, description="그 주소가 속한 읍면동 (43곳 밖이면 없음)")
    emd_nm: str | None = None


class RouteOut(BaseModel):
    distance_m: int = Field(description="자동차 도로 기준 거리 (m)")
    duration_s: int = Field(description="자동차 기준 걸리는 시간 (초, 부른 때의 교통 기준)")
    path: list[tuple[float, float]] = Field(description="(위도, 경도) 순서의 도로 경로")


# =========================================================================== 서버 상태
def _fail(status: int, code: str, message: str) -> HTTPException:
    """오류 응답은 {"detail": {"code": …, "message": …}} 모양이에요."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


class ApiState:
    """서버 하나가 쥐고 있는 것: 서비스(데이터 창고 + 에이전트)와 실행 잠금."""

    def __init__(self, settings: Settings, service: AgentService | None = None,
                 data_mode: str | None = None, llm_mode: str | None = None):
        self.settings = settings
        self._service = service
        self._data_mode, self._llm_mode = data_mode, llm_mode
        self.run_lock = threading.Lock()  # 분석은 한 번에 하나씩
        self.runs: dict[str, threading.Event] = {}  # 스트리밍 실행마다 '멈추기' 신호
        self.runs_lock = threading.Lock()
        self._make_lock = threading.Lock()

    def service(self) -> AgentService:
        """서비스는 처음 쓸 때 만들어요. 데이터 창고가 없으면 만드는 법을 알려 줘요."""
        if self._service is None:
            with self._make_lock:
                if self._service is None:
                    try:
                        self._service = AgentService.create(self._data_mode, self._llm_mode, settings=self.settings)  # type: ignore[arg-type]
                    except WarehouseMissing as e:
                        raise _fail(503, "warehouse_missing", str(e)) from e
        return self._service

    def switch(self, data_mode: str | None, llm_mode: str | None) -> AgentService:
        cur = self.service()
        now_data = cur.agent.ctx.wh.data_mode
        if data_mode and data_mode != now_data:
            try:  # 데이터가 바뀌면 대화 맥락도 새로 시작해요 (다른 데이터의 답을 섞지 않으려고요)
                new = AgentService.create(data_mode, llm_mode or cur.agent.llm_mode, settings=self.settings)  # type: ignore[arg-type]
            except WarehouseMissing as e:
                raise _fail(409, "warehouse_missing", str(e)) from e
        elif llm_mode:
            new = cur.with_llm(llm_mode)
        else:
            return cur
        self._service = new
        return new

    def modes(self) -> dict[str, Any]:
        s = self.settings
        svc = self._service
        cur_llm = svc.agent.llm_mode if svc else None
        built = warehouse_exists(s, ["synthetic", "hub", "center"])
        return {
            "data": [{"mode": m, "label": DATA_BADGE[m], "available": built[m],
                      "current": bool(svc and svc.agent.ctx.wh.data_mode == m)} for m in ("synthetic", "hub", "center")],
            "llm": [
                {"mode": "template", "label": TEMPLATE_LABEL, "available": True, "current": cur_llm == "template"},
                {"mode": "anthropic", "label": fmt.model_name(s.anthropic_model),
                 "available": bool(os.environ.get("ANTHROPIC_API_KEY")), "current": cur_llm == "anthropic"},
            ],
            "locked": s.lock_modes,
        }


def _options(svc: AgentService) -> dict[str, Any]:
    """확인 카드에서 고를 수 있는 값과 화면 범례."""
    refs, cfg = svc.agent.refs, svc.config
    return {
        "stages": [{"stage": k, "title": v} for k, v in STAGE_TITLE.items()],
        "intents": INTENT_LABEL,
        "intent_stage": dict(_INTENT_STAGE),
        "types": [{"code": k, "label": v, "meaning": TYPE_MEANING[k]} for k, v in TYPE_LABEL.items()],
        "themes": list(refs.themes),
        "hubs": [{"hub_id": h.hub_id, "hub_nm": h.hub_nm, "hub_type": h.hub_type, "lat": h.lat, "lon": h.lon}
                 for h in refs.hubs.values()],
        "zones": [{"zone": z.zone, "zone_type": z.zone_type} for z in refs.zones.values()],
        "age_bands": [10, 20, 30, 40, 50, 60, 70],
        "youth_age_bands": cfg.analysis.youth_age_bands,
        "period_months": cfg.analysis.period_months,
        "elasticity_grid": cfg.stage3.elasticity_grid,
        "elasticity_default": cfg.stage3.elasticity_default,
        "supply_change_default": cfg.stage3.supply_change_default,
    }


def _report_url(path: str | Path | None) -> str | None:
    return f"/api/reports/{quote(Path(path).name)}" if path else None


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# =========================================================================== 앱
def create_app(service: AgentService | None = None, settings: Settings | None = None,
               data_mode: str | None = None, llm_mode: str | None = None, web_dist: Path | None = None,
               maps: NaverMaps | None = None) -> FastAPI:
    """FastAPI 앱을 만들어요. `uvicorn meomulmeong.api:create_app --factory` 로도 띄울 수 있어요.

    maps 를 주지 않으면 설정의 네이버 지도 키로 만들어요 (키가 없으면 지도 API 없이 떠요).
    """
    settings = settings or (service.settings if service else get_settings())
    state = ApiState(settings, service, data_mode, llm_mode)
    naver = maps or NaverMaps.from_settings(settings)
    docs = settings.api_docs  # 공개 주소에 둘 때는 끄고(MEOMUL_API_DOCS=false), 이 PC 에서 개발할 때만 켜요
    app = FastAPI(title="머물멍 API", version="0.1.0",
                  description="머물멍 (Jeju Town Vitality Agent) 백엔드. React 화면이 부르는 API예요.",
                  docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)
    app.state.meomul = state
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:  # 개발할 때 Vite 개발 서버(다른 포트)에서 부를 수 있게 해요. 배포본은 같은 주소라 필요 없어요.
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    def locked(work: Callable[[AgentService], Any]) -> Any:
        state.service()  # 데이터 창고가 없으면 기다리지 않고 바로 알려 줘요
        with state.run_lock:
            return work(state.service())  # 기다리는 사이 모드가 바뀌었을 수 있어 다시 가져와요

    def stream(work: Callable[[AgentService, Callable[[str, Any], None]], dict[str, Any]]) -> StreamingResponse:
        """분석을 따로 돌리면서 진행 알림과 답을 SSE 로 흘려보내요.

        실행마다 번호(run)를 첫 알림에 실어 보내요. POST /api/runs/{run}/cancel 이 오면 다음 단계에서 멈추고 잠금을 풀어요.
        """
        q: queue.Queue[tuple[str, Any] | None] = queue.Queue()
        run_id = secrets.token_urlsafe(9)
        cancelled = threading.Event()
        with state.runs_lock:
            state.runs[run_id] = cancelled

        def send(event: str, data: Any) -> None:
            q.put((event, data))

        def on_progress(ev: dict[str, Any]) -> None:
            if cancelled.is_set():
                raise progress.Cancelled()
            if ev["kind"] == "answer":  # 연계 실행은 단계가 끝날 때마다 답을 보내요
                send("answer", ev["answer"].model_dump(mode="json"))
            else:
                send("progress", ev)

        def worker() -> None:
            try:
                state.service()
                if not state.run_lock.acquire(blocking=False):  # 분석은 한 번에 하나씩이라, 앞 사람이 있으면 알려 주고 기다려요
                    send("progress", {"kind": "queue"})
                    while not state.run_lock.acquire(timeout=0.3):
                        if cancelled.is_set():  # 기다리다 멈추면 차례를 기다리지 않아요
                            raise progress.Cancelled()
                try:
                    with progress.listen(on_progress):
                        send("done", work(state.service(), send))
                finally:
                    state.run_lock.release()
            except progress.Cancelled:
                send("error", {"code": "cancelled", "message": "분석을 멈췄어요."})
            except HTTPException as e:
                send("error", e.detail if isinstance(e.detail, dict) else {"code": "error", "message": str(e.detail)})
            except Exception as e:  # noqa: BLE001
                send("error", {"code": "internal", "message": f"처리하다 오류가 났어요: {e}"})
            finally:
                with state.runs_lock:
                    state.runs.pop(run_id, None)
                q.put(None)

        threading.Thread(target=worker, daemon=True, name="meomul-stream").start()

        def events() -> Iterator[str]:
            yield _sse("progress", {"kind": "start", "run": run_id})
            while (item := q.get()) is not None:
                yield _sse(*item)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/runs/{run_id}/cancel", tags=["스트리밍"])
    def cancel_run(run_id: str = PathParam(max_length=40)) -> dict[str, bool]:
        """스트리밍 실행을 멈춰요 (화면의 '멈추기'). 지금 하는 단계가 끝나면 멈추고, 다음 사람의 분석이 바로 시작돼요."""
        with state.runs_lock:
            ev = state.runs.get(run_id)
        if ev is None:
            raise _fail(404, "no_run", "이미 끝났거나 없는 실행이에요.")
        ev.set()
        return {"ok": True}

    # ------------------------------------------------------------------ 상태 · 첫 화면
    @app.get("/api/health", response_model=HealthOut, tags=["상태"])
    def health() -> HealthOut:
        try:
            state.service()
        except HTTPException as e:
            return HealthOut(ready=False, message=e.detail["message"])  # type: ignore[index]
        return HealthOut(ready=True)

    @app.get("/api/status", response_model=StatusOut, tags=["상태"])
    def status() -> dict[str, Any]:
        """데이터 배지, LLM 모드, 테이블별 수록 기간, 적재할 때 생긴 문제."""
        return {**state.service().status(), "modes": state.modes()}

    @app.get("/api/bootstrap", response_model=BootstrapOut, tags=["상태"])
    def bootstrap() -> dict[str, Any]:
        """첫 화면에 필요한 것을 한 번에 줘요."""
        svc = state.service()
        return {"status": {**svc.status(), "modes": state.modes()}, "places": svc.places(),
                "suggested": [{"stage": k, "title": STAGE_TITLE[k], "questions": v} for k, v in svc.suggested_questions().items()],  # type: ignore[union-attr]
                "options": _options(svc), "naver_map_key_id": naver.client_id if naver else None}

    # ------------------------------------------------------------------ 지도 (네이버, 선택)
    def need_maps() -> NaverMaps:
        if naver is None:
            raise _fail(503, "maps_off", "네이버 지도 키가 없어 이 기능을 쓸 수 없어요.")
        return naver

    def emd_of(code: str | None) -> dict[str, str] | None:
        """행정동 코드(10자리) → 우리 읍면동. 앞 8자리가 읍면동 코드예요."""
        e = state.service().agent.refs.emds.get((code or "")[:8])
        return {"emd_cd": e.emd_cd, "emd_nm": e.emd_nm} if e else None

    @app.get("/api/map/locate", response_model=MapPlaceOut, tags=["지도"])
    def map_locate(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)) -> dict[str, str]:
        """지도의 한 점이 속한 읍면동 (Reverse Geocoding). 바다 위나 43곳 밖이면 404."""
        m = need_maps()
        if not in_jeju(lat, lon):
            raise _fail(400, "outside_jeju", "제주도 안의 점을 골라 주세요.")
        try:
            found = emd_of(m.admcode(lat, lon))
        except MapsUnavailable as e:
            raise _fail(503, "maps_unavailable", f"지도에서 동네를 찾지 못했어요. {e}") from e
        if not found:
            raise _fail(404, "no_place", "그 자리에는 읍면동이 없어요. 육지 위를 눌러 주세요.")
        return found

    @app.get("/api/map/search", response_model=list[AddressOut], tags=["지도"])
    def map_search(q: str = Query(min_length=2, max_length=80)) -> list[dict[str, Any]]:
        """도로명·지번 주소로 찾기 (Geocoding). 제주의 주소만, 읍면동을 붙여 돌려줘요."""
        m = need_maps()

        def jeju(query: str) -> list[dict[str, Any]]:
            return [a for a in m.geocode(query) if in_jeju(a["lat"], a["lon"])]

        try:
            found = jeju(q)
            # '중앙로 105'처럼 다른 지역에도 있는 주소는 제주가 밀려나요. 시를 붙여 한 번 더 찾아요
            # ('제주특별자치도 성산읍 …'처럼 시 없이 도만 붙이면 네이버가 찾지 못해요)
            if not found and "제주시" not in q and "서귀포" not in q:
                for city in ("제주특별자치도 제주시", "제주특별자치도 서귀포시"):
                    found += [a for a in jeju(f"{city} {q}") if (a["lat"], a["lon"]) not in {(b["lat"], b["lon"]) for b in found}]
            out = []
            for a in found:
                place = emd_of(m.admcode(a["lat"], a["lon"]))
                out.append({"address": a["road"] or a["jibun"], "jibun": a["jibun"], "lat": a["lat"], "lon": a["lon"],
                            **(place or {})})
        except MapsUnavailable as e:
            raise _fail(503, "maps_unavailable", f"주소를 찾지 못했어요. {e}") from e
        return out

    @app.get("/api/map/route", response_model=RouteOut, tags=["지도"])
    def map_route(keys: str = Query(description="거점 ID와 읍면동 코드를 지나는 순서대로 쉼표로 (2~7개)")) -> dict[str, Any]:
        """코스의 자동차 도로 경로와 거리·시간 (Directions 5). 버스 노선의 실제 경로는 아니에요."""
        m = need_maps()
        refs = state.service().agent.refs
        names = [k for k in keys.split(",") if k]
        if not 2 <= len(names) <= 7:
            raise _fail(400, "bad_route", "지나는 곳은 2~7곳이어야 해요.")
        points = []
        for k in names:
            spot = refs.hubs.get(k) or refs.emds.get(k)
            if spot is None:
                raise _fail(400, "bad_route", f"모르는 거점·읍면동이에요: {k}")
            points.append((spot.lat, spot.lon))
        try:
            route = m.driving(points)
        except MapsUnavailable as e:
            raise _fail(503, "maps_unavailable", f"도로 경로를 찾지 못했어요. {e}") from e
        if not route:
            raise _fail(404, "no_route", "자동차 도로로 잇지 못했어요.")
        return route

    @app.get("/api/places", response_model=list[PlaceOut], tags=["상태"])
    def places() -> list[dict[str, Any]]:
        """지도에서 고를 읍면동 43곳 (좌표 포함)."""
        return state.service().places()

    @app.get("/api/options", response_model=OptionsOut, tags=["상태"])
    def options() -> dict[str, Any]:
        return _options(state.service())

    @app.post("/api/modes", response_model=StatusOut, tags=["상태"])
    def set_modes(body: ModesIn) -> dict[str, Any]:
        """데이터 모드나 LLM 모드를 바꿔요. 데이터 모드를 바꾸면 대화 맥락은 새로 시작해요.

        모드는 서버 전체에 걸려요. 여러 사람이 같은 주소를 쓰는 배포본은 MEOMUL_LOCK_MODES 로 잠가요.
        """
        if settings.lock_modes:
            raise _fail(403, "modes_locked", "이 주소에서는 데이터와 AI 설명 방식이 정해져 있어 바꿀 수 없어요.")
        with state.run_lock:
            svc = state.switch(body.data_mode, body.llm_mode)
        return {**svc.status(), "modes": state.modes()}

    # ------------------------------------------------------------------ 세션
    @app.post("/api/sessions", response_model=SessionOut, tags=["세션"])
    def new_session() -> SessionOut:
        """대화 하나를 시작해요. session_id 를 이후 요청에 넣으면 후속 질문과 단계 연계가 이어져요."""
        return SessionOut(session_id=state.service().agent.session().id)

    @app.post("/api/sessions/{session_id}/cloud-consent", response_model=ConsentOut, tags=["세션"])
    def cloud_consent(body: ConsentIn, session_id: str = PathParam(pattern=SESSION_ID)) -> ConsentOut:
        """클라우드 LLM 전송 동의. 화면에서 전송 미리보기(Answer.llm_payload)를 보여 준 뒤에만 켜요."""
        state.service().set_cloud_consent(session_id, body.consent)
        return ConsentOut(session_id=session_id, consent=body.consent)

    # ------------------------------------------------------------------ 질문
    @app.post("/api/understand", response_model=CardOut, tags=["질문"])
    def understand(body: QuestionIn) -> CardOut:
        """질문을 해석해 확인 카드를 돌려줘요. 실행은 하지 않아요."""
        def work(svc: AgentService) -> CardOut:
            s = svc.agent.session(body.session_id)
            return CardOut(session_id=s.id, card=svc.agent.understand(body.question, s))
        return locked(work)

    @app.post("/api/confirm", response_model=CardOut, tags=["질문"])
    def confirm(body: QueryIn) -> CardOut:
        """화면에서 고친 해석으로 확인 카드를 다시 만들어요. 장소는 place_name 만 바꿔 보내면 돼요."""
        svc = state.service()
        return CardOut(session_id=svc.agent.session(body.session_id).id, card=svc.card(body.query))

    @app.post("/api/run", response_model=AnswerOut, tags=["질문"])
    def run(body: QueryIn) -> AnswerOut:
        """확인 카드의 해석(고친 것 포함)을 실행해요."""
        def work(svc: AgentService) -> AnswerOut:
            s = svc.agent.session(body.session_id)
            return AnswerOut(session_id=s.id, answer=svc.agent.run(svc.normalize_query(body.query), s))
        return locked(work)

    def do_ask(svc: AgentService, body: QuestionIn) -> AskOut:
        s = svc.agent.session(body.session_id)
        res = svc.agent.ask(body.question, s)
        if isinstance(res, ChainResult):
            return AskOut(session_id=s.id, kind="chain", chain=res, report_url=_report_url(res.report_path))
        return AskOut(session_id=s.id, kind="answer", answer=res)

    def do_chain(svc: AgentService, body: ChainIn) -> ChainOut:
        s = svc.agent.session(body.session_id)
        card = svc.agent.understand(f"{body.place} 처음부터 끝까지", s)
        if card.query.place_kind != "emd":
            raise _fail(404, "unknown_place", f"'{body.place}'에 맞는 읍면동을 찾지 못했어요. (예: 성산읍, 구좌읍, 노형동)")
        res = svc.agent.run_chain(card.query, s, with_report=body.with_report)
        return ChainOut(session_id=s.id, chain=res, report_url=_report_url(res.report_path))

    @app.post("/api/ask", response_model=AskOut, tags=["질문"])
    def ask(body: QuestionIn) -> AskOut:
        """질문 한 줄을 확인 카드 없이 바로 실행해요. '처음부터 끝까지'는 연계 실행(chain)으로 돌려줘요."""
        return locked(lambda svc: do_ask(svc, body))

    @app.post("/api/chain", response_model=ChainOut, tags=["질문"])
    def chain(body: ChainIn) -> ChainOut:
        """읍면동 하나를 Stage 1 → 2 → 3 으로 끝까지 실행해요."""
        return locked(lambda svc: do_chain(svc, body))

    # ------------------------------------------------------------------ 스트리밍 (SSE)
    _SSE_DOC = {200: {"content": {"text/event-stream": {}},
                      "description": "event: progress | answer | done | error (README 8절)"}}

    @app.post("/api/run/stream", tags=["스트리밍"], responses=_SSE_DOC, response_class=StreamingResponse)
    def run_stream(body: QueryIn) -> StreamingResponse:
        def work(svc: AgentService, send: Callable[[str, Any], None]) -> dict[str, Any]:
            s = svc.agent.session(body.session_id)
            a = svc.agent.run(svc.normalize_query(body.query), s)
            send("answer", a.model_dump(mode="json"))
            return {"session_id": s.id, "kind": "answer", "elapsed": a.elapsed}
        return stream(work)

    @app.post("/api/ask/stream", tags=["스트리밍"], responses=_SSE_DOC, response_class=StreamingResponse)
    def ask_stream(body: QuestionIn) -> StreamingResponse:
        def work(svc: AgentService, send: Callable[[str, Any], None]) -> dict[str, Any]:
            out = do_ask(svc, body)
            if out.answer is not None:  # 연계 실행의 답은 단계가 끝날 때마다 이미 보냈어요
                send("answer", out.answer.model_dump(mode="json"))
                return {"session_id": out.session_id, "kind": "answer", "elapsed": out.answer.elapsed}
            assert out.chain is not None
            return {"session_id": out.session_id, "kind": "chain", "place_name": out.chain.place_name,
                    "report_url": out.report_url, "elapsed": out.chain.elapsed}
        return stream(work)

    @app.post("/api/chain/stream", tags=["스트리밍"], responses=_SSE_DOC, response_class=StreamingResponse)
    def chain_stream(body: ChainIn) -> StreamingResponse:
        def work(svc: AgentService, send: Callable[[str, Any], None]) -> dict[str, Any]:
            out = do_chain(svc, body)
            return {"session_id": out.session_id, "kind": "chain", "place_name": out.chain.place_name,
                    "report_url": out.report_url, "elapsed": out.chain.elapsed}
        return stream(work)

    # ------------------------------------------------------------------ 제안서
    @app.post("/api/reports", response_model=ReportOut, tags=["제안서"])
    def make_report(body: ReportIn) -> ReportOut:
        """세션에 쌓인 Stage 1~3 답으로 최종 제안서(HTML)를 만들어요. 빠진 단계는 먼저 실행해요."""
        def work(svc: AgentService) -> ReportOut:
            if body.place and not svc.agent.refs.resolve_place(body.place):
                raise _fail(404, "unknown_place", f"'{body.place}'에 맞는 장소를 찾지 못했어요.")
            try:
                path = svc.build_report(body.session_id, body.place)
            except ValueError as e:
                raise _fail(400, "nothing_to_report", f"{e} 읍면동을 하나 골라 먼저 분석해 주세요.") from e
            return ReportOut(filename=path.name, url=_report_url(path) or "")
        return locked(work)

    @app.get("/api/reports/{filename}", tags=["제안서"], response_class=FileResponse)
    def get_report(filename: str, download: bool = False) -> FileResponse:
        """만들어 둔 제안서를 돌려줘요. download=true 면 파일로 내려받아요."""
        folder = (settings.outputs_dir / "reports").resolve()
        path = (folder / filename).resolve()
        if path.parent != folder or path.suffix != ".html" or not path.is_file():
            raise _fail(404, "report_not_found", "제안서를 찾지 못했어요.")
        return FileResponse(path, media_type="text/html; charset=utf-8", filename=filename if download else None)

    # ------------------------------------------------------------------ React 빌드 결과물 (있을 때만)
    dist = Path(web_dist or settings.web_dist or settings.home.parent / "frontend" / "dist").resolve()
    if (dist / "index.html").is_file():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            """빌드한 React 화면을 같은 주소에서 내줘요. 없는 경로는 index.html 로 보내 화면 쪽 라우터가 처리해요."""
            if path.startswith("api/"):
                raise _fail(404, "not_found", "없는 API 경로예요.")
            f = (dist / path).resolve()
            if path and f.is_file() and dist in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def root() -> dict[str, Any]:
            return {"name": "머물멍 API", "docs": "/docs", "bootstrap": "/api/bootstrap",
                    "frontend": f"빌드한 React 화면이 없어요. {dist} 에 빌드 결과물을 두면 이 주소에서 같이 열려요."}

    return app
