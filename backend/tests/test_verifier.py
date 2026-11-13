import pytest

from meomulmeong.agent import explainer
from meomulmeong.agent.stages import run_stage1, run_stage2, run_stage3
from meomulmeong.agent.verifier import Verifier, _matches, _numbers, superlatives
from meomulmeong.schemas import EvidenceTable
from meomulmeong.tools.output import export_check


@pytest.fixture()
def b1(agent):
    return run_stage1(agent.ctx.new_request(), agent.understand("성산읍 청년 인구 진단").query)


@pytest.fixture()
def b2(agent):
    return run_stage2(agent.ctx.new_request(), agent.understand("성산읍에 누가 올까?").query, None)


@pytest.fixture()
def b3(agent):
    return run_stage3(agent.ctx.new_request(), agent.understand("성산읍 어떻게 데려올까? 감편 10%").query, None)


# ---------------------------------------------------------------- 숫자 뽑기·맞추기
def test_number_extraction():
    got = [(v, unit) for v, _d, _s, _raw, unit in _numbers("1,589명으로 5.5% 줄었고 12만 명, R01, 2025-11~2026-10, 111번")]
    assert got == [(1589.0, "명"), (5.5, "%"), (120000.0, "명"), (2025.0, ""), (11.0, ""), (2026.0, ""), (10.0, "")]


@pytest.mark.parametrize("value,decimals,allowed,ok", [
    (5.5, 1, [5.47], True),       # 소수 첫째 자리 반올림
    (5.0, 0, [5.47], True),       # 정수 반올림
    (5.6, 1, [5.47], False),
    (1600.0, 0, [1589.0], True),  # 유효숫자 2자리 반올림 ('약 1,600명')
    (2000.0, 0, [1589.0], False),
    (38.0, 1, [-38.02], True),    # 부호는 문장('줄었어요')이 담으므로 크기만 비교
    (99.9, 1, [100.0], False),    # 작은 수는 상대 오차로 봐주지 않아요
    (119000.0, 0, [119377.0], True),
])
def test_number_matching(value, decimals, allowed, ok):
    assert _matches(value, decimals, 1.0, allowed, 0.005) is ok


# ---------------------------------------------------------------- 숫자 대조
def test_numbers_check(agent, b1):
    v = agent.verifier
    good = f"성산읍의 20·30대 거주인구는 하루 평균 {b1.text('youth_resd_p1')}으로 {b1.text('youth_resd_chg').lstrip('-+')} 줄었어요."
    assert v.check_numbers(good, b1).passed
    bad = v.check_numbers("성산읍의 20·30대 거주인구는 하루 평균 1,234명으로 12.3% 줄었어요.", b1)
    assert not bad.passed and "1,234" in bad.detail and "12.3%" in bad.detail


def test_pairing_check(agent, b2):
    v = agent.verifier
    share = b2.text("cn_share:식음료")
    assert v.check_pairing(f"중국인 소비 가운데 식음료 비중은 {share}예요.", b2).passed
    wrong = v.check_pairing(f"중국인 개별관광객이 {share}의 소비 비중을 차지해요.", b2)
    assert not wrong.passed and "식음료 비중" in wrong.detail
    nat = b2.text("nat_growth_top").lstrip("+")
    assert v.check_pairing(f"대만 방문자는 {nat} 늘었어요.", b2).passed
    assert not v.check_pairing(f"중국인 방문자는 {nat} 늘었어요.", b2).passed


# ---------------------------------------------------------------- 인과·예측 가드
@pytest.mark.parametrize("text,ok", [
    ("관광객이 줄었기 때문이에요.", False),
    ("청년 인구가 줄어든 이유는 방문객이 늘었어요.", False),
    ("관광객 증가가 청년 유출을 초래했어요.", False),
    ("원인은 이 자료만으로 단정할 수 없어요.", True),
    ("관광객 증감이 청년 이동의 원인인지는 이 자료로 알 수 없어요.", True),
    ("버스가 올 수 없기 때문에 청년이 떠났어요.", False),  # 부정 표현이 인과 낱말 앞에 있으면 단정이에요
    ("청년 거주는 줄고 방문은 늘어 「C 방문 의존형」으로 분류돼요.", True),
])
def test_causal_guard(text, ok):
    assert Verifier.check_causal(text).passed is ok


@pytest.mark.parametrize("text,ok", [
    ("성산읍에 중국인 개별관광객이 올 거예요.", False),
    ("내년에는 방문자가 늘어날 것입니다.", False),
    ("가정대로라면 입도객은 줄어들 것으로 계산돼요.", True),
    ("방문자는 7.9% 늘었어요.", True),
])
def test_prediction_guard(text, ok):
    assert Verifier.check_prediction(text).passed is ok


# ---------------------------------------------------------------- 참조 대조
def test_reference_check(agent, b3):
    v = agent.verifier
    assert v.check_references("공항에서 111번으로 환승 없이 갈 수 있어요.", b3).passed
    r = v.check_references("공항에서 999번을 타면 돼요.", b3)
    assert not r.passed and "999" in r.detail
    r = v.check_references("애월읍을 거쳐 가는 방법도 있어요.", b3)
    assert not r.passed and "애월읍" in r.detail  # 실재하지만 이 답의 근거에는 없는 읍면동
    r = v.check_references("한라읍에서 갈아타요.", b3)
    assert not r.passed and "한라읍" in r.detail  # 참조표에 없는 지명


# ---------------------------------------------------------------- 구조 검사
def test_structure_checks(agent, b2, b3):
    v = agent.verifier
    names = {c.name: c for c in v.check_structure("가정에 따른 계산이에요.", b3)}
    assert names["assumption"].passed and names["export"].passed and names["periods"].passed
    assert not {c.name: c for c in v.check_structure("입도객이 줄어요.", b3)}["assumption"].passed  # '가정' 문구 누락
    assert {c.name: c for c in v.check_structure("", b2)}["suggestions"].passed


def test_export_gate():
    rules = {"min_cell": 5, "max_rows": 3, "count_columns": ["user_cnt"], "forbidden_columns": ["biz_num", "ent_nm"],
             "grades": {"center": "aggregate_only", "hub": "open"}}
    ev = EvidenceTable(id="t", title="t", columns=["읍면동", "user_cnt", "증가율"], rows=[["가", 3, 0.5], ["나", 12, 0.1],
                                                                                       ["다", 7, 0.2], ["라", 9, 0.3]])
    check, safe = export_check([ev], rules, "center")
    assert check.passed and safe[0].rows == [["가", None, 0.5], ["나", 12, 0.1], ["다", 7, 0.2]]  # 작은 셀 가림, 행 수 제한
    check, safe = export_check([ev], rules, "hub")
    assert safe[0].rows[0][1] == 3  # 공개 데이터는 가리지 않아요
    secret = EvidenceTable(id="s", title="s", columns=["ent_nm", "biz_num"], rows=[["가게", "123"]])
    check, safe = export_check([secret], rules, "center")
    assert not check.passed and safe == []  # 식별 컬럼은 내보내지 않아요


# ---------------------------------------------------------------- 초안 충실도·추측 표현
def test_fidelity_check(agent, b2):
    from meomulmeong.agent import explainer

    headline, draft = explainer.template_text(b2)
    v = agent.verifier
    ratio = b2.text("weekend_ratio_cn")
    ok = v.check_fidelity(f"중국인 소비는 주말 소비비가 {ratio}로 평일보다 낮아요.", f"{headline}. {draft}", b2)
    assert ok.passed
    bad = v.check_fidelity(f"주말 소비비는 내국인보다 {ratio}예요.", f"{headline}. {draft}", b2)
    assert not bad.passed and "내국인" in bad.detail  # 초안에서 이 숫자는 중국인 지표였어요
    assert v.check_fidelity(draft, f"{headline}. {draft}", b2).passed  # 초안 자체는 언제나 통과


@pytest.mark.parametrize("text", [
    "성산읍은 중국인 개별관광객이 가장 많이 올 가능성이 있어요.",
    "중국어 메뉴판을 준비하면 외국인 손님을 더 끌어올 수 있어요.",
    "아마 방문자가 줄어든 것 같아요.",
])
def test_speculation_is_blocked(text):
    assert not Verifier.check_prediction(text).passed


def test_plain_ability_statement_is_allowed():
    assert Verifier.check_prediction("제주국제공항에서 111번으로 환승 없이 갈 수 있어요.").passed


def test_korean_split_numbers_are_merged():
    got = {raw: v for v, _d, _s, raw, _u in _numbers("입도객이 10만 493명 줄고, 기준선은 100만 4926명, 금액은 1억 2,000만 원이에요. 12만 명, 3.5%")}
    assert got["10만 493"] == 100493 and got["100만 4926"] == 1004926 and got["1억 2,000만"] == 120000000
    assert got["12만"] == 120000 and got["3.5%"] == 3.5


def test_split_number_matches_fact(agent, b3):
    total = int(round(abs(b3.value("scenario_delta"))))
    text = f"가정대로라면 입도객이 {total // 10000}만 {total % 10000}명 줄어드는 것으로 계산돼요."
    assert agent.verifier.check_numbers(text, b3).passed


def test_superlatives_must_come_from_the_draft(agent, b3):
    v = agent.verifier
    headline, draft = explainer.template_text(b3)
    full = f"{headline}. {draft}"
    assert "가장 큰" in superlatives(full)  # 초안: '민감도가 가장 큰 노선은 …'
    assert v.check_fidelity(draft, full, b3).passed
    assert v.check_fidelity("관광 수요에 가장 높게 반응한 노선이 있어요.", full, b3).passed  # 같은 뜻으로 바꿔 쓴 말
    bad = v.check_fidelity("제주국제공항에서 오는 코스가 직행으로 가장 빠르고 편해요.", full, b3)
    assert not bad.passed and "최상급" in bad.detail
    assert not v.check_fidelity("이 코스가 최적이에요.", full, b3).passed
    assert superlatives("가장자리에 있어요") == set()
    assert superlatives("증가 폭이 가장 컸어요") == superlatives("최고 증가 폭이에요") == {"가장 큰"}  # 같은 뜻으로 바꿔 쓴 말


@pytest.mark.parametrize("text,value,unit", [
    ("입도객은 12만명이에요", 120000, "명"), ("입도객은 24만명", 240000, "명"), ("약 1천만 명", 10000000, "명"),
    ("1,193만명 수준", 11930000, "명"), ("3천명", 3000, "명"), ("금액은 5억원", 500000000, "원"),
    ("37만여 명", 370000, "명"), ("2만큼", 2, ""), ("12개월 만에", 12, "개월"),
    ("100만이 넘는 입도객", 1000000, ""), ("24만을 넘었어요", 240000, ""), ("12만 여행객", 120000, ""),
    ("3천리", 3, ""), ("-10%와 탄력성", 10, "%"), ("20·30대 비중은 17.5%예요", 20, ""),
    ("11만 해도", 110000, ""),
])
def test_unit_multipliers_attached_to_counters(text, value, unit):
    """'24만명'을 24로 읽으면 늘 허용하는 수(24)로 통과해 버려요. 붙여 쓴 배수도 제값으로 읽어요."""
    v, _d, _s, _raw, u = _numbers(text)[0]
    assert v == value and u == unit


def test_wrong_big_number_is_caught(agent, b3):
    total = abs(b3.value("scenario_delta"))
    wrong = int(total // 10000) + 13
    assert agent.verifier.check_numbers(f"가정대로라면 입도객이 {int(round(total / 10000))}만명 줄어드는 것으로 계산돼요.", b3).passed
    assert not agent.verifier.check_numbers(f"가정대로라면 입도객이 {wrong}만명 줄어드는 것으로 계산돼요.", b3).passed


def test_month_in_a_date_is_not_a_multiplier():
    assert [v for v, *_ in _numbers("2025-11만 해도 입도객이 많았어요")] == [2025, 11]


def test_forecast_wording_needs_the_assumption(agent):
    v = agent.verifier
    assert not v.check_prediction("12월에 예상되는 수치예요.").passed
    assert not v.check_prediction("입도객이 늘 것으로 전망돼요.").passed
    assert v.check_prediction("이 시나리오는 예측이 아니라 가정에 따른 계산이에요.").passed
    assert v.check_prediction("탄력성 1.0을 가정했을 때 예상되는 값이에요.").passed  # 가정을 밝힌 문장은 괜찮아요
    assert v.check_prediction("수요 탄력성이 1.0일 때 예상되는 수치예요.").passed  # 탄력성을 밝힌 것도 가정을 밝힌 거예요
    assert not v.check_prediction("내년에는 입도객이 늘 것으로 예상되는 상황이에요.").passed


def test_area_values_are_not_attributed_to_the_town(agent, b2):
    """Stage 2 의 카드 값은 '서귀포시 읍면 지역' 값이에요. 성산읍의 값처럼 쓰면 통과하지 못해요."""
    v = agent.verifier
    headline, draft = explainer.template_text(b2)
    full = f"{headline}. {draft}"
    growth = b2.text("cn_growth:전체").lstrip("+")
    assert growth in draft
    bad = v.check_fidelity(f"성산읍의 중국인 카드 소비는 전체로 {growth} 늘었어요.", full, b2)
    assert not bad.passed and "성산읍" in bad.detail
    assert v.check_fidelity(f"성산읍이 속한 {b2.text('area')}의 중국인 카드 소비는 전체로 {growth} 늘었어요.", full, b2).passed
    assert v.check_fidelity(f"중국인 카드 소비는 전체로 {growth} 늘었어요.", full, b2).passed
    assert v.check_fidelity(draft, full, b2).passed


def test_pairing_follows_the_subject_of_the_previous_sentence(agent):
    """지표 낱말이 없는 문장은 앞 문장의 주어를 이어받아요. 다른 지표를 말한 문장은 이어받지 못해요."""
    b = run_stage1(agent.ctx.new_request(), agent.understand("이도2동 20·30대 인구 흐름 진단해줘").query)
    p1, p0 = b.text("youth_resd_p1"), b.text("youth_resd_p0")
    v = agent.verifier
    ok = f"이도2동의 20·30대 거주인구는 최근 기간 하루 평균 {p1}이었어요. 직전 기간은 {p0}이었고, 거의 같은 수준이었어요."
    assert v.check_pairing(ok, b).passed
    assert not v.check_pairing(f"20·30대 근무인구는 조금 늘었어요. 직전 기간은 {p0}이었어요.", b).passed  # 앞 문장이 다른 지표
    assert not v.check_pairing(f"20·30대 거주인구는 줄었어요. 방문자는 {p0}이었어요.", b).passed  # 이 문장이 다른 지표를 말함
    assert not v.check_pairing(f"직전 기간은 {p0}이었어요.", b).passed  # 이어받을 앞 문장이 없음


def test_most_first_is_the_same_as_first(agent, b2):
    """한 줄 결론의 '먼저 볼 만해요'를 '가장 먼저 볼 만해요'로 쓴 것은 새 주장이 아니에요."""
    headline, draft = explainer.template_text(b2)
    assert "먼저 볼 만해요" in headline
    v = agent.verifier
    assert v.check_fidelity("이 지역에서는 중국인 개별관광객을 가장 먼저 볼 만해요.", f"{headline}. {draft}", b2).passed
    assert not v.check_fidelity("이 지역은 가장 인기 있는 곳이에요.", f"{headline}. {draft}", b2).passed


def test_reversed_ratio_is_rejected(agent, b2):
    """주말 소비비는 '주말 ÷ 평일'이에요. '주말에 비해 평일 소비가 0.89배'는 방향이 뒤바뀐 문장이에요."""
    v = agent.verifier
    headline, draft = explainer.template_text(b2)
    full = f"{headline}. {draft}"
    ratio = b2.text("weekend_ratio_cn")
    bad = v.check_fidelity(f"중국인은 주말에 비해 평일 소비가 {ratio}예요.", full, b2)
    assert not bad.passed and "방향" in bad.detail
    assert v.check_fidelity(f"중국인 소비는 주말 하루 소비가 평일 하루의 {ratio}예요.", full, b2).passed
    assert v.check_fidelity(f"중국인 소비는 평일에 비해 주말 소비가 {ratio}예요.", full, b2).passed
    assert v.check_fidelity(draft, full, b2).passed


def test_plain_words_for_the_same_metric_are_accepted(agent, b1, b3):
    """'사는 20·30대'는 거주인구, '국내선 좌석'은 국내선 공급이에요. 지표의 정의를 풀어 쓴 문장도 같은 대상이에요.

    클라우드 LLM(Claude)이 맞게 쓴 해설을 이 표현 때문에 다시 쓰게 하던 일을 막아요.
    """
    v = agent.verifier
    p1, chg = b1.text("youth_resd_p1"), b1.text("youth_resd_chg").lstrip("-+")
    assert v.check_pairing(f"성산읍에 사는 20·30대는 하루 평균 {p1}으로, 직전 기간보다 {chg} 줄었어요.", b1).passed
    assert not v.check_pairing(f"성산읍을 찾은 방문자는 하루 평균 {p1}이에요.", b1).passed  # 다른 지표에 붙이면 여전히 걸러요

    headline, draft = explainer.template_text(b1)
    share, settle = b1.text("youth_share"), b1.text("settle_ratio")
    assert v.check_fidelity(f"성산읍 거주인구 가운데 20·30대 비중은 {share}예요.", f"{headline}. {draft}", b1).passed
    assert v.check_fidelity(f"거주·근무·방문 인구를 합친 것 가운데 거주인구의 몫인 정주비는 {settle}예요.",
                            f"{headline}. {draft}", b1).passed

    supply = b3.text("supply_change").lstrip("-+")
    assert v.check_pairing(f"국내선 좌석이 {supply} 줄어든다고 가정하면 입도객이 줄어드는 것으로 계산돼요.", b3).passed
