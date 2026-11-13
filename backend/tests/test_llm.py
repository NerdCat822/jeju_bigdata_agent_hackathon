"""LLM 경로: 가짜 공급자로 검증 → 재시도 → 템플릿 대체, LLM 해석, 자유 질문을 시험해요."""

import os

import pytest

from meomulmeong.agent.orchestrator import Agent
from meomulmeong.llm.base import (
    ExplainOut,
    FreeExplainOut,
    LLMError,
    LLMFormatError,
    LLMProvider,
    ParseOut,
    SqlOut,
)
from meomulmeong.schemas import Answer


class FakeLLM(LLMProvider):
    """미리 정한 답을 차례로 돌려주는 공급자."""

    name = "fake"
    model = "fake-1"

    def __init__(self, script: dict[str, list], cloud: bool = False):
        super().__init__()
        self.script = {k: list(v) for k, v in script.items()}
        self.is_cloud = cloud
        self.calls: list[tuple[str, str]] = []

    def generate(self, system, user, out, *, purpose="", model=None, effort="low"):
        self.calls.append((purpose, user))
        item = self.script[purpose].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def check(self):
        return True, "fake"


def make(agent, script, cloud=False) -> Agent:
    return Agent(agent.ctx, FakeLLM(script, cloud))


GOOD = "성산읍의 20·30대 거주인구는 줄었고 방문자는 늘었어요."


def test_llm_explanation_used_when_it_passes(agent):
    ag = make(agent, {"explain": [ExplainOut(explanation=GOOD)]})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "llm" and a.explanation == GOOD and a.verification.retries == 0
    assert a.headline == "청년 거주는 줄고 방문은 늘어 「C 방문 의존형」으로 분류돼요"  # 한 줄 결론은 규칙이 만든 문장
    assert {"numbers", "pairing", "fidelity", "causal", "prediction", "references"} <= {c.name for c in a.verification.checks}
    payload = ag.llm.calls[0][1]
    assert "근거:" in payload and "20·30대 거주 변화율" in payload and a.llm_payload == payload


def test_retry_then_pass(agent):
    ag = make(agent, {"explain": [ExplainOut(explanation="관광객이 늘었기 때문에 청년이 줄었어요."),
                                 ExplainOut(explanation=GOOD)]})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "llm" and a.verification.retries == 1 and not a.verification.fallback
    assert "검증을 통과하지 못했어요" in ag.llm.calls[1][1] and "때문" in ag.llm.calls[1][1]  # 고칠 점을 알려 줘요
    assert [s.ok for s in a.steps if s.tool == "llm:explain"] == [False, True]


def test_fallback_to_template_after_two_retries(agent):
    bad = [ExplainOut(explanation="거주인구가 77.7% 줄었어요."),            # 근거에 없는 숫자
           ExplainOut(explanation="성산읍에 관광객이 더 올 거예요."),        # 단정적 예측
           ExplainOut(explanation="애월읍과 한라읍도 비슷해요.")]            # 근거에 없는 지명
    ag = make(agent, {"explain": bad})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "template" and a.verification.fallback and a.verification.retries == 2
    assert a.verification.passed and "1,5" in a.explanation  # 수치만 담은 템플릿 해설
    assert any("템플릿 해설로 대신" in n for n in a.notices)
    assert len(ag.llm.calls) == 3


def test_llm_error_falls_back(agent):
    ag = make(agent, {"explain": [LLMError("연결 실패")]})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.ok and a.explained_by == "template" and any("연결 실패" in n for n in a.notices)


def test_stage3_requires_assumption_word(agent, monkeypatch):
    ag = make(agent, {"explain": [ExplainOut(explanation="성산읍을 지나는 노선은 4개예요."),
                                 ExplainOut(explanation="가정에 따른 계산이에요. 성산읍을 지나는 노선은 4개예요.")]})
    monkeypatch.setattr(ag.config.llm, "template_only_intents", ["recommend", "courses"])  # plan 도 LLM에 맡기는 설정
    a = ag.ask("성산읍 어떻게 데려올까? 감편 10%", ag.session())
    assert a.explained_by == "llm" and a.verification.retries == 0  # 한 줄 결론에 이미 '가정'이 있어요
    assert a.verification.passed


def test_cloud_needs_consent(agent):
    ag = make(agent, {"explain": [ExplainOut(explanation=GOOD)]}, cloud=True)
    s = ag.session()
    a = ag.ask("성산읍 청년 인구 진단", s)
    assert a.explained_by == "template" and ag.llm.calls == []  # 동의 전에는 아무것도 보내지 않아요
    assert a.llm_payload and any("동의" in n for n in a.notices)  # 전송 미리보기는 제공
    s.cloud_consent = True
    b = ag.ask("성산읍 청년 인구 진단", s)
    assert b.explained_by == "llm" and len(ag.llm.calls) == 1
    assert "원자료" not in b.llm_payload and "base_date" not in b.llm_payload


def test_llm_parse_for_unclear_question(agent):
    parsed = ParseOut(stage=1, intent="diagnose", place="성산읍", ages=[20, 30], last_n_months=None, year=None, theme=None,
                      supply_change_pct=None, elasticity=None, target_month=None, wants_cause=False)
    ag = make(agent, {"parse": [parsed], "explain": [ExplainOut(explanation=GOOD)]})
    card = ag.understand("젊은 층이 요즘 많이 빠져나간다는 그 바닷가 마을 어때?", ag.session())  # 규칙으로는 장소·단계를 못 잡는 질문
    assert card.query.parsed_by == "llm" and card.query.place_name == "성산읍" and card.query.intent == "diagnose"


def test_llm_parse_cannot_invent_places(agent):
    parsed = ParseOut(stage=1, intent="diagnose", place="한라읍", ages=[20, 30], last_n_months=None, year=None, theme=None,
                      supply_change_pct=None, elasticity=None, target_month=None, wants_cause=False)
    ag = make(agent, {"parse": [parsed]})
    card = ag.understand("젊은 사람들 요즘 어때?", ag.session())
    assert card.query.place_key is None  # 참조표에 없는 장소는 버려요


def test_confident_questions_skip_llm_parse(agent):
    ag = make(agent, {"explain": [ExplainOut(explanation=GOOD)]})
    ag.ask("성산읍 청년 인구 진단", ag.session())
    assert [p for p, _ in ag.llm.calls] == ["explain"]


FREE_Q = "지난달 버스 이용자가 가장 많은 노선 5개는?"
FREE = ParseOut(stage=None, intent="free", place=None, ages=[20, 30], last_n_months=None, year=None, theme=None,
                supply_change_pct=None, elasticity=None, target_month=None, wants_cause=False)
SQL = ("SELECT route_no, SUM(riders) AS riders FROM m_bus_route_month WHERE month = DATE '2026-10-01' "
       "GROUP BY route_no ORDER BY riders DESC LIMIT 5")


def test_free_question_with_sql_retry(agent):
    ag = make(agent, {
        "parse": [FREE],
        "sql": [SqlOut(title="노선별 이용자", sql="SELECT * FROM no_such_table"), SqlOut(title="2026-10 이용자 상위 5개 노선", sql=SQL)],
        "explain": [FreeExplainOut(headline="이용자가 가장 많은 노선은 201번이에요", explanation="201번과 202번이 가장 많아요.")],
    })
    a = ag.ask(FREE_Q, ag.session())
    assert isinstance(a, Answer) and a.ok and a.intent == "free" and a.explained_by == "llm"
    assert a.evidence[0].sql.startswith("SELECT route_no") and len(a.evidence[0].rows) == 5
    assert a.evidence[0].rows[0][0] == "201"
    assert "카탈로그에 없는 테이블" in ag.llm.calls[2][1]  # 실패한 SQL의 오류를 돌려줘요
    assert any("LLM이 썼어요" in lim for lim in a.limits)
    explain_input = ag.llm.calls[-1][1]
    riders = a.evidence[0].rows[0][1]
    assert riders >= 10_000 and f"{riders:,}" in explain_input  # 큰 정수는 쉼표를 붙여 넘겨요


def test_free_question_rejects_unsafe_sql(agent):
    ag = make(agent, {"parse": [FREE], "sql": [SqlOut(title="x", sql="DROP TABLE ref_emd")] * 3})
    a = ag.ask(FREE_Q, ag.session())
    assert not a.ok and "SQL" in a.message
    assert agent.ctx.wh.query("SELECT COUNT(*) FROM ref_emd").scalar() == 43


def test_free_explanation_numbers_are_checked(agent):
    ag = make(agent, {"parse": [FREE], "sql": [SqlOut(title="상위 5개 노선", sql=SQL)],
                      "explain": [FreeExplainOut(headline="1위는 201번이에요", explanation="이용자는 999,999,999명이에요.")] * 3})
    a = ag.ask(FREE_Q, ag.session())
    assert a.ok and a.explained_by == "template" and a.verification.fallback and "5행" in a.explanation


@pytest.mark.cloud
def test_real_claude_roundtrip(svc):
    """실제 Claude API를 한 번 불러요 (요금이 나가요). API 키가 있을 때만: pytest -m cloud"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY 가 없어요")
    from meomulmeong.llm.anthropic_provider import AnthropicProvider

    llm = AnthropicProvider(svc.settings.anthropic_model)
    ag = Agent(svc.agent.ctx, llm)
    session = ag.session()
    session.cloud_consent = True  # 화면에서는 전송 미리보기를 보고 동의해야 보내요
    a = ag.ask("성산읍 청년 인구 진단", session)
    assert a.ok and a.verification.passed and llm.usage.calls >= 1


def test_cause_questions_always_use_rule_sentences(agent):
    ag = make(agent, {"explain": [ExplainOut(explanation="관광객이 많아져도 청년이 떠나는 건 아니에요.")]})
    a = ag.ask("성산읍 청년 인구 왜 줄었어?", ag.session())
    assert a.explained_by == "template" and ag.llm.calls == []  # 원인 질문은 LLM에 문장을 맡기지 않아요
    assert "원인은 이 자료만으로 단정할 수 없어요" in a.explanation and any("원인을 묻는 질문" in n for n in a.notices)


def test_llm_explanations_can_be_switched_off(agent):
    ag = make(agent, {"explain": [ExplainOut(explanation=GOOD)]})
    ag.config = ag.config.model_copy(deep=True)
    ag.config.llm.explain = False
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "template" and ag.llm.calls == [] and a.llm_mode == "fake"


def test_semantic_mix_up_is_rejected(agent):
    wrong = ExplainOut(explanation="중국인 식음료 소비가 28.4% 늘었고, 주말 소비비는 내국인보다 0.89배예요.")
    right = ExplainOut(explanation="서귀포시 읍면 지역의 중국인 식음료 소비는 28.4% 늘었어요.")
    ag = make(agent, {"explain": [wrong, right]})
    a = ag.ask("성산읍에 누가 올까?", ag.session())
    assert a.explained_by == "llm" and a.verification.retries == 1 and a.explanation == right.explanation
    assert "초안에서 함께 쓰인 대상" in ag.llm.calls[1][1]


def test_unrunnable_recipe_becomes_free_question(agent):
    as_routes = ParseOut(stage=3, intent="routes", place=None, ages=[20, 30], last_n_months=None, year=None, theme=None,
                         supply_change_pct=None, elasticity=None, target_month=None, wants_cause=False)
    ag = make(agent, {"parse": [as_routes], "sql": [SqlOut(title="상위 5개 노선", sql=SQL)],
                      "explain": [FreeExplainOut(headline="이용자가 가장 많은 노선은 201번이에요", explanation="201번이 가장 많아요.")]})
    a = ag.ask(FREE_Q, ag.session())  # LLM이 '노선 분석'으로 읽어도 읍면동이 없어 실행할 수 없으니 자유 질문으로 시도
    assert a.ok and a.intent == "free" and a.evidence[0].rows[0][0] == "201"


def test_echoed_payload_is_rejected(agent):
    echo = ExplainOut(explanation="성산읍 청년 인구 진단\n단계: Stage 1 청년이 머무는 동네\n근거:\n- 장소: 성산읍")
    ag = make(agent, {"explain": [echo, ExplainOut(explanation=GOOD)]})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "llm" and a.verification.retries == 1 and "근거:" not in a.explanation
    assert "입력을 그대로 옮기지 말고" in ag.llm.calls[1][1]
    assert "⟵" in next(s.note for s in a.steps if s.tool == "llm:explain" and not s.ok)  # 떨어진 문장을 기록에 남겨요


def test_list_answers_stay_rule_based(agent):
    """추천 순위와 코스처럼 목록을 보여 주는 답은 LLM에 맡기지 않아요."""
    ag = make(agent, {})
    for q in ("30대가 살기 좋은 읍면 추천해줘", "구좌읍까지 오는 코스는?"):
        a = ag.ask(q, ag.session())
        assert a.ok and a.explained_by == "template" and a.verification.passed
    assert ag.llm.calls == []


def test_free_question_zero_rows_retries(agent):
    empty = SqlOut(title="x", sql="SELECT route_no FROM m_bus_route_month WHERE month = DATE '1999-01-01'")
    ag = make(agent, {"parse": [FREE], "sql": [empty, SqlOut(title="상위 5개 노선", sql=SQL)],
                      "explain": [FreeExplainOut(headline="이용자가 가장 많은 노선은 201번이에요", explanation="201번이 가장 많아요.")]})
    a = ag.ask(FREE_Q, ag.session())
    assert a.ok and len(a.evidence[0].rows) == 5 and "0행" in ag.llm.calls[2][1]
    assert any(b.label.startswith("자유 질문") for b in a.badges)
    sql_prompt = ag.llm.calls[1][1]
    assert "m_bus_route_month" in sql_prompt and "가장 최근 달은 2026-10" in sql_prompt  # 월 집계 테이블과 최근 달 안내


def test_cause_question_without_place_skips_llm_parse(agent):
    ag = make(agent, {})
    a = ag.ask("관광객 때문에 청년이 떠났지?", ag.session())
    assert a.ok and ag.llm.calls == [] and "단정" in a.headline


def test_truncated_output_is_retried(agent):
    ag = make(agent, {"explain": [LLMFormatError("잘린 JSON"), ExplainOut(explanation=GOOD)]})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "llm" and a.verification.retries == 1
    assert "짧게 써 주세요" in ag.llm.calls[1][1]


def test_chain_gives_each_stage_its_own_question(agent, monkeypatch):
    """'처음부터 끝까지'는 단계의 질문이 아니라서, 단계마다 물을 것을 따로 넘겨요."""
    ok = [ExplainOut(explanation="값은 근거표와 같아요. 가정에 따른 계산이에요.")] * 3
    ag = make(agent, {"explain": list(ok)})
    monkeypatch.setattr(ag.config.llm, "template_only_intents", ["recommend", "courses"])  # Stage 3 도 LLM에 맡겨 봐요
    result = ag.ask("성산읍 처음부터 끝까지", ag.session())
    asked = [user.splitlines()[0] for purpose, user in ag.llm.calls if purpose == "explain"]
    assert len(asked) == 3 and all("처음부터 끝까지" not in line for line in asked)
    assert asked[0].startswith("질문: 성산읍의 청년 인구는") and "관광객" in asked[1] and "국내선 공급" in asked[2]
    assert all(a.query.question == "성산읍 처음부터 끝까지" for a in result.answers)  # 기록에 남는 질문은 그대로예요


def test_payload_ends_with_evidence_not_instructions(agent):
    """끝에 지시문이 있으면 작은 모델이 지시문을 되받아 적어서, 근거 목록으로 끝내요."""
    ag = make(agent, {"explain": [ExplainOut(explanation="가정에 따른 계산이에요.")]})
    a = ag.ask("국내선 10% 감편 시 12월 개별여행 입도객", ag.session())
    last = a.llm_payload.splitlines()[-1]
    assert last.startswith("- ") and "주의" not in a.llm_payload and "(가정값)" in a.llm_payload


def test_plan_answers_stay_rule_based_by_default(agent):
    """Stage 3 전체 계획(시나리오·노선·코스)은 코스 목록이 들어가서, 기본 설정에서는 규칙 문장을 그대로 써요."""
    ok = [ExplainOut(explanation="값은 근거표와 같아요.")] * 2
    ag = make(agent, {"explain": list(ok)})
    result = ag.ask("성산읍 처음부터 끝까지", ag.session())
    assert [a.explained_by for a in result.answers] == ["llm", "llm", "template"]
    assert len(ag.llm.calls) == 2 and all(a.verification.passed for a in result.answers)
    alone = ag.ask("성산읍 어떻게 데려올까? 감편 10%", ag.session())
    assert alone.intent == "plan" and alone.explained_by == "template" and len(ag.llm.calls) == 2


def test_explanation_that_only_repeats_the_headline_falls_back_at_once(agent):
    """한 줄 결론만 되풀이한 해설은 다시 쓰게 하지 않고 바로 템플릿 해설로 바꿔요."""
    from meomulmeong.agent.orchestrator import repeats_headline

    base = agent.ask("국내선 10% 감편 시 12월 개별여행 입도객", agent.session())  # 템플릿 모드의 답
    headline = base.headline
    assert repeats_headline(headline + ".", headline) and repeats_headline(headline.replace("줄면", "줄어들면"), headline)
    assert not repeats_headline(base.explanation, headline)
    ag = make(agent, {"explain": [ExplainOut(explanation=headline + "."), ExplainOut(explanation="전년 동월 실적을 기준선으로 한 가정 계산이에요.")]})
    a = ag.ask("국내선 10% 감편 시 12월 개별여행 입도객", ag.session())
    assert a.explained_by == "template" and a.explanation == base.explanation and a.verification.fallback
    assert len(ag.llm.calls) == 1 and a.verification.passed


def test_retry_feedback_comes_first(agent):
    """고칠 점은 맨 앞에 붙이고, 입력은 여전히 근거 목록으로 끝나요 (맨 뒤 지시문은 작은 모델이 되받아 적어요)."""
    ag = make(agent, {"explain": [ExplainOut(explanation="관광객이 늘었기 때문에 청년이 줄었어요."), ExplainOut(explanation=GOOD)]})
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    retry = ag.llm.calls[1][1]
    assert a.explained_by == "llm" and a.verification.retries == 1
    assert retry.startswith("다시 쓰기 요청:") and retry.splitlines()[-1].startswith("- ") and retry.endswith(a.llm_payload)


def test_explain_time_budget_stops_retries(agent, monkeypatch):
    """느린 PC에서 다시 쓰기가 길어지지 않게, 시간 한도를 넘기면 템플릿 해설로 대체해요."""
    bad = ExplainOut(explanation="관광객이 늘었기 때문에 청년이 줄었어요.")
    ag = make(agent, {"explain": [bad, ExplainOut(explanation=GOOD)]})
    monkeypatch.setattr(ag.config.llm, "explain_budget_seconds", 1e-9)
    a = ag.ask("성산읍 청년 인구 진단", ag.session())
    assert a.explained_by == "template" and a.verification.fallback and a.verification.retries == 0
    assert len(ag.llm.calls) == 1 and any("시간 한도" in s.note for s in a.steps)
    monkeypatch.setattr(ag.config.llm, "explain_budget_seconds", 0)  # 0 이면 한도 없이 다시 써요
    ag2 = make(agent, {"explain": [bad, ExplainOut(explanation=GOOD)]})
    assert ag2.ask("성산읍 청년 인구 진단", ag2.session()).explained_by == "llm"


def test_stage2_payload_leaves_out_the_stage_link_sentence(agent):
    """'Stage 1에서 …으로 분류됐어요'는 화면용 문장이에요. LLM 초안에서는 빼고, 유형은 근거 목록으로만 알려 줘요."""
    ag = make(agent, {"explain": [ExplainOut(explanation="중국인 카드 소비가 늘었어요.")]})
    a = ag.ask("성산읍에 누가 올까?", ag.session())
    draft_line = next(x for x in a.llm_payload.splitlines() if x.startswith("해설 초안:"))
    assert "Stage 1에서" not in draft_line and "중국인 카드 소비" in draft_line
    template = agent.ask("성산읍에 누가 올까?", agent.session())
    assert "Stage 1에서" in template.explanation  # 템플릿 해설에는 그대로 있어요
