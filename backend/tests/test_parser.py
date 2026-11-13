import pytest

from meomulmeong.agent.parser import RuleParser, confirm_card
from meomulmeong.settings import load_config


@pytest.fixture(scope="module")
def parser(refs, settings):
    return RuleParser(refs, load_config(settings.config_dir))


@pytest.mark.parametrize("question,stage,intent,place", [
    ("성산읍 청년 인구 왜 줄었어?", 1, "diagnose", "성산읍"),
    ("한림읍 30대 거주인구 추이", 1, "trend", "한림읍"),
    ("30대가 살기 좋은 읍면 추천해줘", 1, "recommend", None),
    ("한 달 살이 지원은 어느 읍면에 배정해야 하나?", 1, "recommend", None),
    ("성산읍 비슷한 읍면과 비교", 1, "peers", "성산읍"),
    ("서귀포 구도심 음식점인데 외국인 손님 늘릴 수 있나?", 2, "shift", "서귀포시 구도심"),
    ("서귀포 구도심 식음료 중국인 소비 변화", 2, "shift", "서귀포시 구도심"),
    ("구좌읍까지 오는 코스는?", 3, "courses", "구좌읍"),
    ("국내선 10% 감편 시 12월 개별여행 입도객", 3, "forecast", None),
    ("노형동 감편 때 버스 수요는?", 3, "plan", "노형동"),
    ("성산읍 버스 노선 민감도", 3, "routes", "성산읍"),
    ("성산읍 처음부터 끝까지", 1, "chain", "성산읍"),
    ("제주도 날씨 알려줘", None, "free", None),
])
def test_stage_intent_place(parser, question, stage, intent, place):
    q, _ = parser.parse(question)
    assert (q.stage, q.intent, q.place_name) == (stage, intent, place)


def test_slots(parser):
    q, _ = parser.parse("국내선 10% 감편 시 12월 개별여행 입도객")
    assert (q.supply_change, q.target_month) == (-0.10, 12)
    q, _ = parser.parse("국내선 공급 5% 증가하면 8월 입도객은? 탄력성 1.5")
    assert (q.supply_change, q.target_month, q.elasticity) == (0.05, 8, 1.5)
    q, _ = parser.parse("30대가 살기 좋은 읍면 추천해줘")
    assert q.ages == [30] and q.emd_type == "읍면"
    q, _ = parser.parse("성산읍 최근 6개월 청년 인구")
    assert q.last_n_months == 6 and q.ages == [20, 30] and q.target_month is None  # '6개월'을 '6월'로 읽지 않아요
    q, _ = parser.parse("서귀포 구도심 음식점인데 외국인 손님 늘릴 수 있나?")
    assert q.theme == "식음료" and q.place_kind == "zone"
    q, _ = parser.parse("공항에서 한경면 가는 버스")
    assert q.hub_id == "JEJU_AIRPORT" and q.place_name == "한경면"
    q, _ = parser.parse("한 달 살이 지원은 어느 읍면에 배정해야 하나?")
    assert q.target_month is None


def test_cause_and_auto_place(parser):
    q, _ = parser.parse("관광객 때문에 청년이 떠났지?")
    assert q.wants_cause and q.stage == 1 and q.place_key is None
    q, _ = parser.parse("청년이 빠지는 읍면 한 곳의 전체 제안서")
    assert (q.intent, q.auto_place, q.emd_type, q.place_key) == ("chain", "declining", "읍면", None)


def test_follow_ups_keep_context(parser):
    q1, _ = parser.parse("성산읍 청년 인구 왜 줄었어?")
    q2, _ = parser.parse("거기 30대만?", q1)
    assert (q2.place_name, q2.ages, q2.stage, q2.intent) == ("성산읍", [30], 1, "diagnose")
    q3, _ = parser.parse("비슷한 읍면과 비교", q2)
    assert (q3.place_name, q3.intent, q3.ages) == ("성산읍", "peers", [30])
    q4, _ = parser.parse("이 동네에 누가 올까?", q3)
    assert (q4.place_name, q4.stage, q4.ages) == ("성산읍", 2, [20, 30])  # 단계가 바뀌면 연령은 기본값으로
    q5, _ = parser.parse("어떻게 데려올까? 감편 10%", q4)
    assert (q5.place_name, q5.stage, q5.intent, q5.supply_change) == ("성산읍", 3, "plan", -0.10)
    q6, _ = parser.parse("감편 20%면?", q5)
    assert (q6.place_name, q6.intent, q6.supply_change) == ("성산읍", "plan", -0.20)
    q7, trace = parser.parse("제주도 날씨 알려줘", q6)
    assert q7.intent == "free" and not trace.confident  # 관련 없는 질문은 맥락을 잇지 않아요


def test_confidence_for_llm_handoff(parser):
    assert parser.parse("성산읍 청년 인구 진단")[1].confident
    q, trace = parser.parse("지난달 버스 이용자가 가장 많은 노선 5개는?")
    assert not trace.confident and q.intent == "routes" and q.place_key is None  # 자유 질의에 가까운 표현
    assert not parser.parse("오늘 점심 뭐 먹지")[1].confident


def test_confirm_card(parser, refs, settings):
    cfg = load_config(settings.config_dir)
    card = confirm_card(parser.parse("성산읍 청년 인구 왜 줄었어?")[0], refs, cfg)
    assert [(c.label, c.value) for c in card.chips[:3]] == [("장소", "성산읍"), ("연령", "20·30대"), ("기간", "최근 12개월 vs 직전")]
    assert card.runnable and any("단정" in w for w in card.warnings)
    card = confirm_card(parser.parse("어떻게 데려올까?")[0], refs, cfg)
    assert not card.runnable and any("읍면동" in w for w in card.warnings)
    card = confirm_card(parser.parse("성산읍 어떻게 데려올까? 감편 10%")[0], refs, cfg)
    assert ("가정", "국내선 공급 -10% · ε 1.0") in [(c.label, c.value) for c in card.chips]
    card = confirm_card(parser.parse("청년이 빠지는 읍면 한 곳의 전체 제안서")[0], refs, cfg)
    assert card.runnable and "자동 선택" in card.chips[0].value
