"""에이전트 전체 흐름 (템플릿 모드): 질문 → 확인 카드 → 실행 → 검증 → 답."""

from pathlib import Path

import pytest

from meomulmeong.schemas import Answer, ChainResult


def ask(agent, question, session=None) -> Answer:
    result = agent.ask(question, session or agent.session())
    assert isinstance(result, Answer)
    return result


def test_stage1_answer_shape(agent):
    a = ask(agent, "성산읍 청년 인구 왜 줄었어?")
    assert a.ok and a.stage == 1 and a.explained_by == "template" and a.verification.passed
    assert a.headline == "청년 거주는 줄고 방문은 늘어 「C 방문 의존형」으로 분류돼요"
    assert "원인은 이 자료만으로 단정할 수 없어요" in a.explanation  # 원인 질문에는 단정 없이 답해요
    assert [b.label for b in a.badges] == ["샘플 데이터", "유형 C"]
    assert a.charts and a.maps and a.limits and a.data_period
    assert all(e.sql for e in a.evidence if e.id != "s1_type_rule" or e.sql)
    assert [n.kind for n in a.next_questions] == ["next_stage", "follow_up", "follow_up"]  # 3개, 하나는 다음 단계
    assert a.stage_output["type"] == "C" and len(a.stage_output["peers"]) == 3
    peers = [p.name for p in a.maps[0].points if p.role == "peer"]
    assert sorted(peers) == sorted(a.stage_output["peers"])


@pytest.mark.parametrize("question", [
    "30대가 살기 좋은 읍면 추천해줘",
    "한 달 살이 지원은 어느 읍면에 배정해야 하나?",
    "서귀포 구도심 청년 인구 진단",
    "한림읍 30대 거주인구 추이",
    "성산읍 비슷한 읍면과 비교",
    "서귀포 구도심 음식점인데 외국인 손님 늘릴 수 있나?",
    "성산읍에 누가 올까?",
    "국내선 10% 감편 시 12월 개별여행 입도객",
    "구좌읍까지 오는 코스는?",
    "우도면까지 오는 코스는?",
    "노형동 감편 20% 탄력성 1.5면 버스 수요는?",
    "관광객 때문에 청년이 떠났지?",
])
def test_recipe_questions_pass_verification(agent, question):
    a = ask(agent, question)
    assert a.ok, a.message
    assert a.verification.passed, [(c.name, c.detail) for c in a.verification.checks if not c.passed]
    assert a.headline and a.explanation and a.evidence and a.data_badge == "샘플 데이터"


def test_stage2_uses_stage1_type(agent):
    a = ask(agent, "성산읍에 누가 올까?")
    assert a.stage == 2 and a.stage_output["type"] == "C" and a.stage_output["target"] == "중국인 개별관광객"
    assert [s.rule_id for s in a.suggestions][0] == "R01"
    assert any("먼저 실행" in n for n in a.notices)  # 앞 단계 자동 실행 안내
    assert any(s.note.startswith("앞 단계") for s in a.steps)
    assert all(e.id.startswith(("s2_", "dow")) for e in a.evidence)  # 화면에는 Stage 2 근거만


def test_stage3_plan(agent):
    a = ask(agent, "성산읍 어떻게 데려올까? 감편 10%")
    assert a.stage == 3 and a.intent == "plan"
    assert any(b.tone == "assumption" for b in a.badges) and "가정" in a.headline
    assert a.stage_output["sensitive_routes"][0] == "111" and len(a.stage_output["courses"]) == 3
    assert {e.id for e in a.evidence} == {"s3_scenario", "s3_routes", "s3_courses"}
    assert a.next_questions[0].kind == "report"


def test_causal_trap_without_place(agent):
    a = ask(agent, "관광객 때문에 청년이 떠났지?")
    assert "단정" in a.headline and a.fact("corr_visit_resd") is not None
    assert next(c for c in a.verification.checks if c.name == "causal").passed


def test_conversation_memory(agent):
    s = agent.session()
    a1 = ask(agent, "성산읍 청년 인구 왜 줄었어?", s)
    a2 = ask(agent, "거기 30대만?", s)
    assert a2.query.place_name == "성산읍" and a2.query.ages == [30] and "30대" in a2.explanation
    a3 = ask(agent, "이 동네에 누가 올까?", s)
    assert a3.stage == 2 and a3.query.place_name == "성산읍"
    assert not any("먼저 실행" in n for n in a3.notices)  # 청년 기준 Stage 1 결과를 기억해 다시 돌리지 않아요
    assert s.stage_output(a1.query.place_key, 1)["ages"] == [20, 30]  # '30대만' 답이 덮어쓰지 않아요
    a4 = ask(agent, "어떻게 데려올까? 감편 10%", s)
    assert a4.stage == 3 and a4.stage_output["target"] == "중국인 개별관광객"  # Stage 2의 타깃이 Stage 3로 넘어가요
    assert a1.stage_output["type"] == a3.stage_output["type"]


def test_chain_and_report(agent, settings):
    result = agent.ask("성산읍 처음부터 끝까지 최종 제안서", agent.session())
    assert isinstance(result, ChainResult)
    assert [a.stage for a in result.answers] == [1, 2, 3]
    assert {a.query.place_name for a in result.answers} == {"성산읍"}  # 세 단계가 같은 읍면동으로 연결
    assert all(a.ok and a.verification.passed for a in result.answers)
    path = Path(result.report_path)
    html = path.read_text(encoding="utf-8")
    assert path.parent == settings.outputs_dir / "reports" and path.suffix == ".html"
    for needle in ("성산읍 제안서", "샘플(합성) 데이터", "Stage 1", "Stage 3", "SQL 보기", "R01", "<svg", "한계", "가정"):
        assert needle in html, needle
    assert "<script" not in html  # 자바스크립트 없이 열려요


def test_auto_pick_declining_emd(agent):
    result = agent.ask("청년이 빠지는 읍면 한 곳의 전체 제안서", agent.session())
    assert isinstance(result, ChainResult) and len(result.answers) == 3
    place = result.place_name
    assert agent.refs.find_emd(place).area_type == "읍면" and result.answers[0].stage_output["type"] in ("C", "D")
    assert "골랐어요" in result.answers[0].notices[0] and "추자면" not in place  # 작은 표본은 후보에서 빼요


def test_failures_are_explained(agent):
    a = ask(agent, "제주도 날씨 알려줘")
    assert not a.ok and "LLM 모드" in a.message and len(a.next_questions) == 3
    a = ask(agent, "어떻게 데려올까?")
    assert not a.ok and "읍면동" in a.message


def test_run_is_deterministic(agent):
    a = ask(agent, "구좌읍 청년 인구 진단")
    b = ask(agent, "구좌읍 청년 인구 진단")
    assert (a.headline, a.explanation) == (b.headline, b.explanation)
    assert [f.value for f in a.facts] == [f.value for f in b.facts]


def test_service_helpers(svc):
    st = svc.status()
    assert st["data_badge"] == "샘플 데이터" and st["llm_mode"] == "template" and len(st["tables"]) == 8
    assert len(svc.places()) == 43 and set(svc.stages()) == {1, 2, 3}
    names = {t["name"] for t in svc.tools()}
    assert {"resolve_place", "search_catalog", "run_sql", "s1_trend", "s1_classify", "s1_peers", "s2_shift", "s2_playbook",
            "s3_forecast", "s3_route_beta", "s3_courses"} <= names
    card = svc.understand("성산읍 청년 인구 왜 줄었어?")
    answer = svc.run(card.query)
    assert answer.ok and svc.build_report(svc.agent.session().id, "성산읍").exists()


def test_run_log_written(agent, settings):
    ask(agent, "성산읍 청년 인구 진단")
    logs = list((settings.outputs_dir / "runs").glob("*.jsonl"))
    text = logs[0].read_text(encoding="utf-8")
    assert '"question": "성산읍 청년 인구 진단"' in text
    assert '"explanation": "' in text and '"explained_by": "template"' in text  # 사용자에게 보인 해설도 남겨요
