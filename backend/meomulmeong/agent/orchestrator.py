"""오케스트레이터: 의도 파싱 → 단계·계획 → 도구 실행 → 검증 → 해설 → 결과.

검증에 실패한 LLM 해설은 최대 2회 다시 쓰게 하고, 그래도 실패하면 수치만 담은 템플릿 해설로 대체해요.
연계 실행(처음부터 끝까지)은 이 루프를 Stage 1 → 2 → 3 순서로 세 번 돌려요.
"""

from __future__ import annotations

import difflib
import json
import re
import time
import uuid
from datetime import datetime
from importlib import resources
from typing import Any

from .. import fmt, progress
from ..llm.base import ExplainOut, FreeExplainOut, LLMError, LLMFormatError, LLMProvider, ParseOut, SqlOut
from ..schemas import (
    STAGE_TITLE,
    Answer,
    Badge,
    ChainResult,
    Check,
    ConfirmCard,
    Fact,
    NextQuestion,
    ParsedQuery,
    StepLog,
    Verification,
)
from ..tools import common as _common  # noqa: F401  (도구 등록)
from ..tools import output as _output  # noqa: F401
from ..tools import stage1 as t1
from ..tools import stage2 as _t2  # noqa: F401
from ..tools import stage3 as _t3  # noqa: F401
from ..tools.base import ToolContext
from ..tools.output import load_export_rules
from . import explainer
from .memory import Session
from .parser import RuleParser, confirm_card
from .stages import Bundle, call, run_stage1, run_stage2, run_stage3
from .verifier import Verifier

MAX_EXPLANATION = 480  # LLM 해설 글자 수 상한 (3문장 안팎)
_ECHO = ("근거:", "해설 초안", "한 줄 결론", "단계: Stage", "결과:", "컬럼:")  # 입력을 되풀이한 흔적

_PUNCT = re.compile(r"[\s.,!?·'\"「」()]+")


def repeats_headline(explanation: str, headline: str) -> bool:
    """해설이 한 줄 결론을 되풀이하기만 했는지 봐요. 같은 문장을 두 번 보여 주게 되거든요."""
    e, h = _PUNCT.sub("", explanation), _PUNCT.sub("", headline)
    if not e or not h:
        return False
    one_sentence = len([x for x in re.split(r"(?<=[.!?])\s+", explanation.strip()) if x]) == 1
    return e == h or (one_sentence and difflib.SequenceMatcher(None, e, h).ratio() >= 0.85)


# 검증 실패 때 LLM에 돌려주는 고칠 점
_FIX = {
    "numbers": "근거의 값에 있는 숫자만 그대로 쓰고, 직접 계산한 숫자는 빼요",
    "causal": "원인을 설명하지 말아요. '때문', '이유는', '원인은', '탓', '영향으로' 같은 말을 모두 빼고 값이 어떻게 변했는지만 써요. "
              "원인을 묻는 질문이면 '원인은 이 자료만으로 단정할 수 없어요.'라고만 답해요",
    "pairing": "숫자를 그 지표의 이름과 같은 문장에 쓰거나, 그 숫자를 빼요",
    "prediction": "'올 거예요', '가능성이 있어요', '~하면 늘릴 수 있어요' 같은 예측·추측을 빼고 지금까지의 값만 말해요",
    "fidelity": "초안에 없는 내용을 더하지 말아요. 숫자는 초안에서 함께 쓰인 대상(내국인·중국인·테마·지명)과만 같이 쓰고, "
                "'가장'·'최고' 같은 말은 초안에 있는 것만 써요. 배율은 초안의 순서 그대로 '주말 하루 소비는 평일 하루의 몇 배'처럼 써요",
    "references": "근거에 없는 읍면동·노선·지명을 빼요",
    "assumption": "'가정'이라는 낱말을 넣어 가정에 따른 계산임을 밝혀요",
    "format": "입력을 그대로 옮기지 말고, 3문장 이내의 한 문단으로 써요",
}

_INTENT_STAGE = {"diagnose": 1, "trend": 1, "recommend": 1, "peers": 1, "shift": 2, "plan": 3, "forecast": 3,
                 "routes": 3, "courses": 3}


def _prompt(name: str) -> str:
    return resources.files("meomulmeong.agent").joinpath("prompts", name).read_text(encoding="utf-8")


class Agent:
    def __init__(self, ctx: ToolContext, llm: LLMProvider | None = None):
        self.ctx = ctx
        self.refs, self.config, self.settings = ctx.refs, ctx.config, ctx.settings
        self.llm = llm
        self.parser = RuleParser(self.refs, self.config)
        self.export_rules = load_export_rules(str(self.settings.config_dir))
        self.verifier = Verifier(self.refs, self.config, {r["id"] for r in ctx.playbook}, self.export_rules,
                                 ctx.wh.data_mode)
        self._sessions: dict[str, Session] = {}

    # ------------------------------------------------------------------ 세션·상태
    def session(self, session_id: str | None = None) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        s = Session() if not session_id else Session(id=session_id)
        self._sessions[s.id] = s
        return s

    @property
    def llm_mode(self) -> str:
        return self.llm.name if self.llm else "template"

    def _llm_ok(self, session: Session) -> bool:
        """LLM을 쓸 수 있는지. 클라우드는 사용자가 전송에 동의한 뒤에만 써요."""
        return self.llm is not None and (not self.llm.is_cloud or session.cloud_consent)

    # ------------------------------------------------------------------ 1) 해석
    def understand(self, question: str, session: Session | None = None) -> ConfirmCard:
        session = session or self.session()
        q, trace = self.parser.parse(question, session.last_query)
        card = confirm_card(q, self.refs, self.config)
        # 규칙 파서가 확신하지 못했거나 실행할 수 없는 해석이면 LLM에 한 번 더 물어요.
        if (not trace.confident or not card.runnable) and self._llm_ok(session):
            q2 = self._llm_parse(question, q, session)
            card = confirm_card(q2, self.refs, self.config)
            if not card.runnable:  # 준비된 분석으로 실행할 수 없으면 자유 질문(LLM SQL)으로 시도해요
                q2.stage, q2.intent = None, "free"
                card = confirm_card(q2, self.refs, self.config)
        return card

    def _llm_parse(self, question: str, rule_q: ParsedQuery, session: Session) -> ParsedQuery:
        last = session.last_query
        user = json.dumps({"질문": question, "직전 질문": last.question if last else None,
                           "직전 장소": last.place_name if last else None}, ensure_ascii=False)
        progress.emit("llm", purpose="parse", label=progress.LLM_LABEL["parse"], attempt=1)
        try:
            out = self.llm.generate(_prompt("parse_system.md"), user, ParseOut, purpose="parse")  # type: ignore[union-attr]
        except LLMError as e:
            rule_q.notes.append(f"LLM 해석을 쓰지 못해 규칙으로 해석했어요. ({e})")
            return rule_q
        q = rule_q.model_copy(deep=True)
        intent = out.intent
        stage = _INTENT_STAGE.get(intent, out.stage)
        if intent == "chain":
            stage = 1
        if intent == "free" or stage is None:
            q.stage, q.intent = None, "free"
            q.parsed_by = "llm"
            return q
        q.stage, q.intent = stage, intent  # type: ignore[assignment]
        # 장소는 참조표로 다시 확인해요 (LLM이 지어낸 이름은 버려요).
        if out.place:
            m = self.refs.resolve_place(out.place)
            if m:
                q.place_kind, q.place_key, q.place_name = m.kind, m.key, m.name  # type: ignore[assignment]
        ages = sorted({a for a in out.ages if a in (0, 10, 20, 30, 40, 50, 60, 70)})
        if ages:
            q.ages = ages
        if out.last_n_months and 1 <= out.last_n_months <= 36:
            q.last_n_months = out.last_n_months
        if out.year and 2010 <= out.year <= 2035:
            q.year = out.year
        if out.theme:
            q.theme = out.theme if out.theme in self.refs.themes else self.refs.find_theme(out.theme)
        if out.supply_change_pct is not None and -100 <= out.supply_change_pct <= 100:
            q.supply_change = out.supply_change_pct / 100
        if out.elasticity is not None and 0 <= out.elasticity <= 5:
            q.elasticity = out.elasticity
        if out.target_month and 1 <= out.target_month <= 12 and stage == 3:
            q.target_month = out.target_month
        q.wants_cause = q.wants_cause or out.wants_cause
        if q.intent in ("recommend", "forecast") and not self.refs.find_places(question):
            q.place_kind = q.place_key = q.place_name = None
        q.parsed_by = "llm"
        return q

    # ------------------------------------------------------------------ 2) 실행
    def ask(self, question: str, session: Session | None = None) -> Answer | ChainResult:
        """질문 한 줄을 끝까지 처리해요 (확인 카드 없이 바로 실행)."""
        session = session or self.session()
        card = self.understand(question, session)
        if card.query.intent == "chain":
            return self.run_chain(card.query, session, with_report="제안서" in question)
        return self.run(card.query, session)

    def run(self, query: ParsedQuery, session: Session | None = None) -> Answer:
        session = session or self.session()
        t0 = time.perf_counter()
        ctx = self.ctx.new_request()
        q = query.model_copy(deep=True)
        notices: list[str] = list(q.notes)
        card = confirm_card(q, self.refs, self.config)
        if q.auto_place and not q.place_key:
            picked = self._auto_place(ctx, q)
            if picked:
                notices.append(picked)
            card = confirm_card(q, self.refs, self.config)
        if q.stage is None or q.intent == "free":
            return self._run_free(ctx, q, session, t0)
        if q.intent == "chain":
            q.intent = "diagnose"
        if not card.runnable:
            return self._fail(q, " ".join(w for w in card.warnings if "골라" in w) or "질문을 실행할 수 없어요.", session, t0)
        if q.stage == 1:
            bundle = run_stage1(ctx, q)
        elif q.stage == 2:
            bundle = run_stage2(ctx, q, session)
        else:
            bundle = run_stage3(ctx, q, session)
        if any("자동 실행" in s.note for s in bundle.steps):
            notices.append("앞 단계 결과가 없어 먼저 실행해 맥락을 채웠어요.")
        return self._finish(bundle, session, t0, notices)

    def _auto_place(self, ctx: ToolContext, q: ParsedQuery) -> str | None:
        """'청년이 빠지는 읍면 한 곳'처럼 장소를 에이전트가 고르는 경우."""
        try:
            rows, _period, _sql = t1.metrics_all(ctx, list(self.config.analysis.youth_age_bands),
                                                 t1._req(q.last_n_months, q.year))
        except Exception:  # noqa: BLE001
            return None
        pool = [r for r in rows if r["type"] is not None and not r["small"]]
        if q.emd_type == "읍면":
            pool = [r for r in pool if r["area_type"] == "읍면"]
        elif q.emd_type == "동":
            pool = [r for r in pool if r["area_type"] == "도심"]
        if not pool:
            return None
        pick = (min if q.auto_place == "declining" else max)(pool, key=lambda r: (r["youth_resd_chg"], r["emd_cd"]))
        q.place_kind, q.place_key, q.place_name = "emd", pick["emd_cd"], pick["emd_nm"]
        word = "줄어든" if q.auto_place == "declining" else "늘어난"
        return (f"청년 거주가 가장 많이 {word} 곳으로 {pick['emd_nm']}({fmt.pct(pick['youth_resd_chg'])})을 골랐어요. "
                f"작은 표본은 후보에서 뺐어요.")

    # ------------------------------------------------------------------ 3) 검증·해설
    def _finish(self, b: Bundle, session: Session, t0: float, notices: list[str]) -> Answer:
        q = b.query
        if not b.ok:
            return self._fail(q, b.message or "분석을 하지 못했어요.", session, t0, steps=b.steps)
        headline, explanation = explainer.template_text(b)
        explained_by = "template"
        retries, fallback = 0, False
        payload_txt: str | None = None
        if self.llm is not None:
            # LLM에는 집계 지표와 규칙이 만든 제안만 보내요 (원자료는 보내지 않아요).
            payload_txt = (explainer.free_payload(b, self.config.llm.evidence_max_rows) if b.stage is None
                           else explainer.llm_payload(b, max_facts=self.config.llm.evidence_max_rows))
            if not self.config.llm.explain and b.stage is not None:
                pass  # 설정에서 LLM 해설을 껐어요 (해석·자유 질문에만 LLM 사용)
            elif q.wants_cause and b.stage is not None:
                notices.append("원인을 묻는 질문에는 정해진 문장으로만 답해요 (원인을 단정하지 않기 위해서예요).")
            elif b.intent in self.config.llm.template_only_intents:
                pass  # 순위·코스처럼 목록을 그대로 보여 주는 답은 규칙 문장을 써요 (settings.yaml 의 llm.template_only_intents)
            elif self._llm_ok(session):
                res = self._llm_explain(b, payload_txt)
                retries, fallback = res["retries"], res["fallback"]
                b.steps += res["steps"]
                if res["text"]:
                    headline, explanation = res["text"]
                    explained_by = "llm"
                elif res["error"]:
                    notices.append(f"LLM 해설을 쓰지 못해 템플릿 해설로 대신했어요. ({res['error']})")
                else:
                    notices.append("LLM 해설이 검증을 통과하지 못해 수치만 담은 템플릿 해설로 대신했어요.")
            else:
                notices.append("클라우드 전송에 동의하지 않아 템플릿 해설을 썼어요. '전송 미리보기'를 확인한 뒤 동의하면 LLM 해설을 받을 수 있어요.")
        draft = ""
        if explained_by == "llm" and b.stage is not None:  # LLM 해설은 초안 충실도까지 기록에 남겨요
            draft = ". ".join(explainer.template_text(b))
        # 한 줄 결론과 해설이 한 문장으로 붙어 검사되지 않게 마침표로 나눠요.
        head = headline if headline.endswith((".", "!", "?")) else headline + "."
        verification = self.verifier.verify(f"{head} {explanation}", b, retries, fallback, draft)
        badges = [Badge(label=self.ctx.wh.data_badge, tone="data"), *b.badges()]
        answer = Answer(
            id=uuid.uuid4().hex[:10], stage=b.stage, intent=b.intent, query=q, headline=headline, explanation=explanation,
            badges=badges, facts=b.facts(), evidence=b.evidence(), charts=b.charts(), maps=b.maps(),
            suggestions=b.suggestions(), limits=b.limits(), next_questions=explainer.next_questions(b),
            data_period=b.period(), data_badge=self.ctx.wh.data_badge, llm_mode=self.llm_mode,
            llm_model=self.llm.model if self.llm else None, explained_by=explained_by,  # type: ignore[arg-type]
            verification=verification, stage_output=b.stage_output, steps=b.steps, llm_payload=payload_txt,
            notices=notices, elapsed=round(time.perf_counter() - t0, 3))
        # 유형은 청년(20·30대) 기준이라, 다른 연령으로 본 Stage 1 답은 다음 단계 입력으로 쓰지 않아요.
        default_ages = sorted(q.ages) == sorted(self.config.analysis.youth_age_bands)
        session.remember(answer, store_stage=(b.stage != 1 or default_ages))
        self._log(answer, session)
        return answer

    def _llm_explain(self, b: Bundle, payload_txt: str) -> dict[str, Any]:
        """LLM 해설을 받아 검증하고, 실패하면 고칠 점을 알려 주며 다시 쓰게 해요 (최대 2회).

        준비된 분석에서는 한 줄 결론을 규칙이 만든 문장 그대로 쓰고, LLM은 쉬운 해설만 써요.
        고칠 점은 입력의 맨 앞에 붙여요. 맨 뒤에 붙이면 작은 모델이 지시문을 답으로 되받아 적었어요.
        """
        free = b.stage is None
        system = _prompt("free_explain_system.md" if free else "explain_system.md")
        schema = FreeExplainOut if free else ExplainOut
        template_headline, draft = explainer.template_text(b)
        draft_all = "" if free else f"{template_headline}. {draft}"
        model = (self.settings.ollama_explain_model or None) if self.llm_mode == "ollama" else None
        steps: list[StepLog] = []
        feedback = ""
        max_retries = self.config.verify.max_retries
        budget = self.config.llm.explain_budget_seconds
        started = time.perf_counter()
        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            if attempt and budget > 0 and t0 - started >= budget:  # 느린 PC에서 답 하나에 몇 분씩 걸리지 않게 해요
                steps.append(StepLog(tool="llm:explain", ok=False, seconds=0.0,
                                     note=f"해설 시간 한도 {budget:.0f}초를 넘겨 더 다시 쓰지 않았어요"))
                return {"text": None, "retries": attempt - 1, "fallback": True, "steps": steps, "error": None}
            progress.emit("llm", purpose="explain", label=progress.LLM_LABEL["explain"], attempt=attempt + 1)
            try:
                out = self.llm.generate(system, feedback + payload_txt, schema, purpose="explain", model=model,  # type: ignore[union-attr]
                                        temperature=0.0 if attempt == 0 else 0.4)
            except LLMFormatError as e:  # 잘렸거나 형식이 틀린 답: 짧게 다시 쓰게 해요
                steps.append(StepLog(tool="llm:explain", ok=False, seconds=round(time.perf_counter() - t0, 2), note=str(e)))
                feedback = "다시 쓰기 요청: 이전 답은 너무 길거나 형식이 맞지 않았어요. 3문장 이내의 한 문단으로 짧게 써 주세요.\n\n"
                continue
            except LLMError as e:
                steps.append(StepLog(tool="llm:explain", ok=False, seconds=round(time.perf_counter() - t0, 2), note=str(e)))
                return {"text": None, "retries": attempt, "fallback": True, "steps": steps, "error": str(e)}
            explanation = out.explanation.strip()
            headline = out.headline.strip() if free else template_headline  # type: ignore[union-attr]
            if not free and repeats_headline(explanation, template_headline):
                # 한 줄 결론만 되풀이한 답은 덧붙일 말이 없다는 뜻이라, 다시 쓰게 하지 않고 바로 템플릿 해설을 써요.
                # (다시 쓰게 하면 작은 모델은 지시문을 되받아 적거나 끝없이 길게 써서 1분 가까이 걸렸어요.)
                steps.append(StepLog(tool="llm:explain", ok=False, seconds=round(time.perf_counter() - t0, 2),
                                     note="한 줄 결론을 되풀이해서 템플릿 해설을 써요 ⟵ " + explanation[:120]))
                return {"text": None, "retries": attempt, "fallback": True, "steps": steps, "error": None}
            written = f"{headline} {explanation}" if free else explanation
            failed = [c for c in self.verifier.check_text(written, b, draft_all) if not c.passed]
            if b.result("s3_forecast") and "가정" not in f"{headline} {explanation}":
                failed.append(Check(name="assumption", passed=False, detail="가정에 따른 계산이라는 점이 빠졌어요"))
            if not explanation or (free and not headline):
                failed.append(Check(name="format", passed=False, detail="내용이 비어 있어요"))
            elif len(explanation) > MAX_EXPLANATION or "\n" in explanation or any(m in explanation for m in _ECHO):
                failed.append(Check(name="format", passed=False, detail="입력을 옮겨 적지 말고 3문장 이내의 한 문단으로 써야 해요"))
            steps.append(StepLog(tool="llm:explain", ok=not failed, seconds=round(time.perf_counter() - t0, 2),
                                 note="검증 통과" if not failed else ("; ".join(c.detail for c in failed)[:300]
                                                                  + " ⟵ " + written[:200])))
            progress.emit("llm_result", purpose="explain", attempt=attempt + 1, ok=not failed,
                          note="검증 통과" if not failed else "검증을 통과하지 못해 다시 써요")
            if not failed:
                return {"text": (headline, explanation), "retries": attempt, "fallback": False, "steps": steps, "error": None}
            feedback = "다시 쓰기 요청: 이전 답은 검증을 통과하지 못했어요. 이번에는 아래를 지켜서 써 주세요.\n" + "\n".join(
                f"- {_FIX.get(c.name, '')} ({c.detail})" for c in failed) + "\n\n"
        return {"text": None, "retries": max_retries, "fallback": True, "steps": steps, "error": None}

    # ------------------------------------------------------------------ 자유 질문 (LLM SQL)
    def _run_free(self, ctx: ToolContext, q: ParsedQuery, session: Session, t0: float) -> Answer:
        if not self._llm_ok(session):
            return self._fail(q, "준비된 분석에 맞지 않는 질문이에요. 자유 질문은 LLM 모드에서만 답할 수 있어요. "
                                 "읍면동을 하나 골라 '성산읍 청년 인구 진단'처럼 물어 보세요.", session, t0)
        b = Bundle(stage=None, intent="free", query=q)
        found = call(b, ctx, "search_catalog", query=q.question, k=3)
        if not found.ok:
            return self._fail(q, "질문과 관련 있는 데이터를 카탈로그에서 찾지 못했어요.", session, t0, steps=b.steps)
        schema = "\n\n".join(t["schema"] + f"\n수록 기간: {t['period']}" + (f"\n{t['mart']}" if t.get("mart") else "")
                             for t in found.data["tables"])
        latest = max((ctx.wh.period(t["table"])[1] for t in found.data["tables"] if ctx.wh.period(t["table"])), default=None)
        hint = f"\n\n자료의 가장 최근 달은 {fmt.month_label(latest)}이에요. '지난달'·'최근'은 이 달을 기준으로 해요." if latest else ""
        user = f"질문: {q.question}\n\n쓸 수 있는 테이블\n{schema}{hint}"
        feedback, result = "", None
        for attempt in range(self.config.verify.max_retries + 1):
            ts = time.perf_counter()
            progress.emit("llm", purpose="sql", label=progress.LLM_LABEL["sql"], attempt=attempt + 1)
            try:
                out = self.llm.generate(_prompt("sql_system.md"), user + feedback, SqlOut, purpose="sql", effort="medium")  # type: ignore[union-attr]
            except LLMError as e:
                b.steps.append(StepLog(tool="llm:sql", ok=False, seconds=round(time.perf_counter() - ts, 2), note=str(e)))
                return self._fail(q, f"SQL을 만들지 못했어요. ({e})", session, t0, steps=b.steps)
            b.steps.append(StepLog(tool="llm:sql", ok=True, seconds=round(time.perf_counter() - ts, 2)))
            result = call(b, ctx, "run_sql", sql=out.sql, title=out.title)
            if result.ok and result.data.get("n_rows"):
                break
            why = result.message if not result.ok else "결과가 0행이에요. 날짜 조건과 조인 조건을 확인해요"
            feedback = f"\n\n이전 SQL은 쓸 수 없었어요: {why}\n이전 SQL: {out.sql}\n문제를 고쳐 다시 써 주세요."
        if not result or not result.ok or not result.data.get("n_rows"):
            return self._fail(q, "질문에 맞는 SQL을 만들지 못했어요. 질문을 조금 더 구체적으로 써 주세요.", session, t0, steps=b.steps)
        ev = result.evidence[0]
        ev.tables = found.tables
        result.limits = ctx.limits(found.tables) + [
            "자유 질문의 SQL은 LLM이 썼어요. 값의 뜻(기간·단위·조건)은 접어 둔 SQL에서 꼭 확인해 주세요."]
        result.badges.append(Badge(label="자유 질문 · SQL 검토 필요", tone="warn"))
        result.facts.append(Fact(key="n_rows", label="결과 행 수", value=len(ev.rows), unit="count", text=f"{len(ev.rows)}행"))
        b.results = [result]
        return self._finish(b, session, t0, [])

    # ------------------------------------------------------------------ 연계 실행
    def run_chain(self, query: ParsedQuery, session: Session | None = None, with_report: bool = False) -> ChainResult:
        """읍면동 하나를 Stage 1 → 2 → 3 순서로 끝까지 실행해요."""
        session = session or self.session()
        t0 = time.perf_counter()
        base = query.model_copy(deep=True)
        notice = None
        if base.auto_place and not base.place_key:
            notice = self._auto_place(self.ctx.new_request(), base)
        answers: list[Answer] = []
        if base.place_kind != "emd":
            a = self._fail(base, "처음부터 끝까지 보려면 읍면동을 하나 골라 주세요. (예: 성산읍)", session, t0)
            return ChainResult(place_name=base.place_name or "", answers=[a], elapsed=a.elapsed)
        for stage, intent in ((1, "diagnose"), (2, "shift"), (3, "plan")):
            q = base.model_copy(deep=True, update={"stage": stage, "intent": intent, "auto_place": None,
                                                   "theme": None if stage != 2 else base.theme,
                                                   "stage_question": explainer.stage_question(stage, base.place_name or "")})
            progress.emit("stage", stage=stage, title=STAGE_TITLE[stage], place=base.place_name)
            a = self.run(q, session)
            if notice and stage == 1:
                a.notices.insert(0, notice)
            answers.append(a)
            progress.emit("answer", answer=a)  # 화면이 단계마다 바로 그릴 수 있게 해요
        result = ChainResult(place_name=base.place_name or "", answers=answers, elapsed=round(time.perf_counter() - t0, 3))
        if with_report:
            from ..report.builder import build_report

            path = build_report(answers, self.settings.outputs_dir / "reports", self.ctx)
            result.report_path = str(path)
        return result

    # ------------------------------------------------------------------ 실패·기록
    def _fail(self, q: ParsedQuery, message: str, session: Session, t0: float, steps: list[StepLog] | None = None) -> Answer:
        examples = [
            NextQuestion(label="성산읍 청년 인구 진단", question="성산읍 청년 인구 진단", kind="follow_up", stage=1),
            NextQuestion(label="30대가 살기 좋은 읍면은?", question="30대가 살기 좋은 읍면 추천해줘", kind="follow_up", stage=1),
            NextQuestion(label="국내선 10% 감편 시 입도객", question="국내선 10% 감편 시 입도객은?", kind="follow_up", stage=3),
        ]
        a = Answer(id=uuid.uuid4().hex[:10], ok=False, message=message, stage=q.stage, intent=q.intent, query=q,
                   headline=message, badges=[Badge(label=self.ctx.wh.data_badge, tone="data")],
                   next_questions=examples, data_badge=self.ctx.wh.data_badge, llm_mode=self.llm_mode,
                   llm_model=self.llm.model if self.llm else None, verification=Verification(passed=True),
                   steps=steps or [], elapsed=round(time.perf_counter() - t0, 3))
        self._log(a, session)
        return a

    def _log(self, a: Answer, session: Session) -> None:
        """실행 기록: 질문, 해석, 도구, SQL, 검증 결과를 남겨 재현과 점검에 써요."""
        try:
            d = self.settings.outputs_dir / "runs"
            d.mkdir(parents=True, exist_ok=True)
            rec = {
                "at": datetime.now().isoformat(timespec="seconds"), "session": session.id, "answer": a.id, "ok": a.ok,
                "question": a.query.question, "query": a.query.model_dump(exclude={"question", "notes"}, exclude_none=True),
                "stage": a.stage, "intent": a.intent, "headline": a.headline, "explanation": a.explanation,
                "explained_by": a.explained_by,
                "llm_mode": a.llm_mode, "llm_model": a.llm_model, "data_badge": a.data_badge,
                "steps": [s.model_dump() for s in a.steps],
                "sql": [{"id": e.id, "sql": e.sql} for e in a.evidence if e.sql],
                "verification": a.verification.model_dump(), "elapsed": a.elapsed,
            }
            with (d / f"{datetime.now():%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass  # 기록 실패가 답을 막지는 않아요
