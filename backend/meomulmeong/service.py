"""에이전트를 쓰는 진입점. 웹 API(`meomulmeong.api`)와 명령줄이 이 클래스를 불러요.

    svc = AgentService.create()
    card = svc.understand("성산읍 청년 인구 왜 줄었어?", session_id)   # 확인 카드
    answer = svc.run(card.query, session_id)                            # 답
    chain = svc.run_chain("성산읍", session_id)                         # 처음부터 끝까지
    path = svc.build_report(session_id, "성산읍")                       # 최종 제안서
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent.orchestrator import _INTENT_STAGE, Agent
from .agent.parser import confirm_card
from .data.catalog import Catalog
from .data.refs import Refs
from .data.warehouse import Warehouse
from .llm.base import LLMError, LLMProvider
from .llm.factory import make_llm
from .report.builder import build_report
from .schemas import STAGE_TITLE, Answer, ChainResult, ConfirmCard, ParsedQuery
from .settings import AppConfig, DataMode, Settings, get_settings, load_config
from .tools.base import TOOLS, ToolContext

SUGGESTED = {
    1: ["성산읍 청년 인구 왜 줄었어?", "30대가 살기 좋은 읍면은?", "한 달 살이 지원은 어디에?"],
    2: ["성산읍에 누가 올까?", "서귀포 구도심 음식점인데 외국인 손님 늘릴 수 있나?", "구좌읍 숙박 중국인 소비 변화"],
    3: ["구좌읍까지 오는 코스는?", "국내선 10% 감편 시 12월 개별여행 입도객", "성산읍 감편 때 버스 수요는?"],
}


def connect_llm(settings: Settings, llm_mode: str | None = None) -> tuple[LLMProvider | None, str]:
    """LLM 공급자를 만들고 쓸 수 있는지 확인해요. 쓸 수 없으면 (None, 이유) 를 돌려줘 템플릿 모드로 내려가요."""
    try:
        llm = make_llm(settings, llm_mode)
        if llm is None:
            return None, ""
        ok, note = llm.check()
        return (llm, note) if ok else (None, note + " 템플릿 모드로 실행해요.")
    except LLMError as e:
        return None, f"{e} 템플릿 모드로 실행해요."


class AgentService:
    def __init__(self, settings: Settings, config: AppConfig, agent: Agent, llm_note: str = ""):
        self.settings = settings
        self.config = config
        self.agent = agent
        self.llm_note = llm_note

    # ------------------------------------------------------------------ 만들기
    @classmethod
    def create(cls, data_mode: DataMode | None = None, llm_mode: str | None = None,
               settings: Settings | None = None) -> AgentService:
        """설정을 읽고 데이터 창고와 LLM을 연결해요. LLM을 쓸 수 없으면 템플릿 모드로 내려가요."""
        settings = settings or get_settings()
        config = load_config(settings.config_dir)
        refs = Refs(settings.ref_dir)
        catalog = Catalog.load(settings.catalog_dir)
        wh = Warehouse(settings.warehouse_path(data_mode))
        ctx = ToolContext(wh, refs, catalog, config, settings)
        llm, note = connect_llm(settings, llm_mode)
        return cls(settings, config, Agent(ctx, llm), note)

    def with_llm(self, llm_mode: str) -> AgentService:
        """같은 데이터로 LLM 모드만 바꾼 서비스를 돌려줘요. 대화 맥락(세션)은 이어 가요."""
        llm, note = connect_llm(self.settings, llm_mode)
        agent = Agent(self.agent.ctx, llm)
        agent._sessions = self.agent._sessions
        return AgentService(self.settings, self.config, agent, note)

    # ------------------------------------------------------------------ 질문
    def understand(self, question: str, session_id: str | None = None) -> ConfirmCard:
        return self.agent.understand(question, self.agent.session(session_id))

    def normalize_query(self, query: ParsedQuery) -> ParsedQuery:
        """화면에서 고쳐 보낸 해석을 실행할 수 있게 바로잡아요.

        화면은 확인 카드의 query 에서 바꾸고 싶은 값만 고쳐 보내면 돼요. 장소를 바꿀 때는 place_name 만 새 이름으로
        바꾸면 서버가 코드(place_key)를 참조표에서 다시 찾아요. 참조표에 없는 장소·테마·거점과 범위를 벗어난 값은 버려요.
        """
        refs = self.agent.refs
        q = query.model_copy(deep=True)
        if q.intent in _INTENT_STAGE:
            q.stage = _INTENT_STAGE[q.intent]  # type: ignore[assignment]
        elif q.intent == "chain":
            q.stage = 1
        elif q.intent == "free":
            q.stage = None
        # 장소: 코드와 이름이 서로 맞는지 보고, 안 맞으면 이름으로 다시 찾아요
        names = {"emd": lambda k: refs.emds[k].emd_nm if k in refs.emds else None,
                 "zone": lambda k: k if k in refs.zones else None,
                 "city": lambda k: k if k in ("제주시", "서귀포시") else None}
        known = names[q.place_kind](q.place_key) if q.place_kind and q.place_key else None
        if known is None or (q.place_name and q.place_name != known):
            m = refs.resolve_place(q.place_name) if q.place_name else None
            if m:
                q.place_kind, q.place_key, q.place_name = m.kind, m.key, m.name  # type: ignore[assignment]
            elif known is not None:
                q.place_name = known
            else:
                q.place_kind = q.place_key = q.place_name = None
        if q.theme and q.theme not in refs.themes:
            q.theme = refs.find_theme(q.theme)
        if q.hub_id and q.hub_id not in refs.hubs:
            q.hub_id = None
        q.ages = sorted({a for a in q.ages if a in (0, 10, 20, 30, 40, 50, 60, 70)}) or list(self.config.analysis.youth_age_bands)
        if q.last_n_months is not None and not 1 <= q.last_n_months <= 36:
            q.last_n_months = None
        if q.year is not None and not 2010 <= q.year <= 2035:
            q.year = None
        if q.target_month is not None and not 1 <= q.target_month <= 12:
            q.target_month = None
        if q.supply_change is not None and not -1 <= q.supply_change <= 1:
            q.supply_change = None
        if q.elasticity is not None and not 0 <= q.elasticity <= 5:
            q.elasticity = None
        q.stage_question = None
        q.question = q.question[:500]
        return q

    def card(self, query: ParsedQuery) -> ConfirmCard:
        """고친 해석으로 확인 카드를 다시 만들어요 (실행하지 않아요)."""
        return confirm_card(self.normalize_query(query), self.agent.refs, self.config)

    def run(self, query: ParsedQuery, session_id: str | None = None) -> Answer:
        return self.agent.run(query, self.agent.session(session_id))

    def ask(self, question: str, session_id: str | None = None) -> Answer | ChainResult:
        return self.agent.ask(question, self.agent.session(session_id))

    def run_chain(self, place: str, session_id: str | None = None, with_report: bool = False) -> ChainResult:
        session = self.agent.session(session_id)
        card = self.agent.understand(f"{place} 처음부터 끝까지", session)
        return self.agent.run_chain(card.query, session, with_report=with_report)

    def build_report(self, session_id: str, place: str | None = None, out_dir: Path | None = None) -> Path:
        """세션에 쌓인 Stage 1~3 답으로 제안서를 만들어요. 빠진 단계는 먼저 실행해요."""
        session = self.agent.session(session_id)
        key = None
        if place:
            m = self.agent.refs.resolve_place(place)
            key = m.key if m else None
        elif session.last_query:
            key = session.last_query.place_key
        answers = [a for a in (session.latest(key, s) for s in (1, 2, 3)) if a]
        if len(answers) < 3 and key and key in self.agent.refs.emds:
            chain = self.run_chain(self.agent.refs.emd_name(key), session_id)
            answers = chain.answers
        return build_report(answers, out_dir or self.settings.outputs_dir / "reports", self.agent.ctx)

    def set_cloud_consent(self, session_id: str, consent: bool) -> None:
        """클라우드 LLM 전송 동의 (전송 미리보기를 확인한 뒤에만 켜요)."""
        self.agent.session(session_id).cloud_consent = consent

    # ------------------------------------------------------------------ 화면용 정보
    def status(self) -> dict[str, Any]:
        wh = self.agent.ctx.wh
        llm = self.agent.llm
        return {
            "data_mode": wh.data_mode, "data_badge": wh.data_badge, "built_at": wh.build_info().get("built_at"),
            "llm_mode": self.agent.llm_mode, "llm_model": llm.model if llm else None,
            "llm_label": (f"로컬 · {llm.model}" if llm and not llm.is_cloud else f"클라우드 · {llm.model}" if llm else "템플릿 (LLM 없음)"),
            "llm_note": self.llm_note,
            "tables": [{"table": m.table, "title": m.title, "rows": m.n_rows, "source": m.source,
                        "period": f"{m.min_date}~{m.max_date}" if m.min_date else "자료 없음"} for m in wh.meta().values()],
            "issues": wh.issues(),
            "route_ref": wh.build_info().get("route_ref_source"),
        }

    def places(self) -> list[dict[str, Any]]:
        """지도에서 고를 읍면동 목록."""
        return [{"emd_cd": e.emd_cd, "emd_nm": e.emd_nm, "city": e.city, "area_type": e.area_type,
                 "region7": e.region7, "lat": e.lat, "lon": e.lon} for e in self.agent.refs.emds.values()]

    @staticmethod
    def suggested_questions(stage: int | None = None) -> dict[int, list[str]] | list[str]:
        return SUGGESTED if stage is None else SUGGESTED.get(stage, [])

    @staticmethod
    def stages() -> dict[int, str]:
        return dict(STAGE_TITLE)

    @staticmethod
    def tools() -> list[dict[str, str]]:
        return [{"name": t.name, "group": t.group, "description": t.description} for t in TOOLS.values()]
