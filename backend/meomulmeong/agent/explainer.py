"""해설기(Explainer): 근거(facts)만 보고 한 줄 결론과 쉬운 해설을 써요.

- 템플릿 해설: LLM 없이 수치만으로 만드는 문장. 항상 만들 수 있고, 검증에 실패한 LLM 해설의 대체문이기도 해요.
- LLM 해설: 같은 근거를 LLM에 주고 문장을 쓰게 한 뒤 검증기를 통과한 것만 써요 (orchestrator 가 호출).
"""

from __future__ import annotations

import re

from .. import fmt
from ..schemas import STAGE_TITLE, TYPE_LABEL, NextQuestion, ParsedQuery
from .stages import Bundle

FLAT = 0.005  # 이보다 작은 변화는 '거의 같았어요'


def _chg(v: float | None, end: bool = True) -> str:
    """변화율 → '5.5% 줄었어요' / '5.5% 줄었고'."""
    if not fmt.is_num(v):
        return "비교할 수 없었어요" if end else "비교할 수 없었고"
    if abs(v) < FLAT:
        return "거의 같았어요" if end else "거의 같았고"
    word = ("늘었어요" if end else "늘었고") if v > 0 else ("줄었어요" if end else "줄었고")
    return f"{fmt.pct_abs(v)} {word}"


def _youth(q: ParsedQuery) -> str:
    return "청년" if sorted(q.ages) == [20, 30] else fmt.ages_label(q.ages)


def _type_text(t: str) -> str:
    return f"{t} {TYPE_LABEL[t]}" if t != "유지" else TYPE_LABEL[t]


def _p1(b: Bundle) -> str:
    return b.text("period", "").split(" vs ")[0]


CAUSE_NOTE = ("원인은 이 자료만으로 단정할 수 없어요. 함께 움직인 지표를 보여 드린 것이고, "
              "일자리·주거비·교통 같은 외부 요인은 따로 확인해야 해요.")


# =========================================================================== Stage 1
def _s1_headline(lab: str, t: str | None, near: str | None, visit: float | None) -> str:
    visit_word = "방문은 늘어" if (visit or 0) >= FLAT else "방문은 줄지 않아"
    if t == "A":
        return f"{lab} 거주와 근무가 함께 늘어 「A 정착 성장형」으로 분류돼요"
    if t == "B":
        return f"{lab} 근무는 늘었지만 거주는 그만큼 늘지 않아 「B 출퇴근형」으로 분류돼요"
    if t == "C":
        return f"{lab} 거주는 줄고 {visit_word} 「C 방문 의존형」으로 분류돼요"
    if t == "D":
        return f"{lab} 거주와 방문이 함께 줄어 「D 활력 저하형」으로 분류돼요"
    if t == "유지":
        tail = f" (가장 가까운 유형은 {_type_text(near)})" if near else ""
        return f"{lab} 거주와 방문의 변화가 작아 「유지형」으로 분류돼요{tail}"
    return f"{lab} 인구 흐름을 정리했어요"


def _s1_emd(b: Bundle) -> tuple[str, str]:
    q = b.query
    place, lab, lab_full = (q.place_name or b.text("place")), _youth(q), fmt.ages_label(q.ages)
    resd, work, visit = b.value("youth_resd_chg"), b.value("youth_work_chg"), b.value("visit_chg")
    t, near = b.value("type"), b.value("near_type")
    peers = b.text("peers", "")
    if q.intent == "peers" and peers:
        headline = f"{fmt.josa(place, '과와')} 지표가 가장 비슷한 곳은 {fmt.josa(peers, '이에요예요')}"
    elif q.intent == "trend" and fmt.is_num(resd):
        headline = f"{place} {lab_full} 거주인구는 {_chg(resd)}"
    else:
        headline = _s1_headline(lab, t, near, visit)
    s: list[str] = []
    if b.fact("youth_resd_p1"):
        s.append(f"{place}의 {lab_full} 거주인구는 최근 기간({_p1(b)}) 하루 평균 {b.text('youth_resd_p1')}으로, "
                 f"직전 기간보다 {_chg(resd)}.")
        s.append(f"같은 기간 {lab_full} 근무인구는 {_chg(work, end=False)}, 방문자는 {_chg(visit)}.")
        s.append(f"{lab_full} 비중은 {b.text('youth_share')}, 정주비는 {b.text('settle_ratio')}예요.")
    elif fmt.is_num(resd):
        s.append(f"{place}의 {lab_full} 거주인구는 {_chg(resd, end=False)}, 근무인구는 {_chg(work, end=False)}, "
                 f"방문자는 {_chg(visit)}.")
    if b.fact("foreign_resd_chg") and fmt.is_num(b.value("foreign_resd_chg")):
        s.append(f"외국인 장기체류 거주인구는 {_chg(b.value('foreign_resd_chg'))}.")
    if q.intent == "trend" and t:
        s.append(f"유형은 「{_type_text(t)}」이에요.")
    if peers and q.intent != "trend":
        s.append(f"지표가 비슷한 곳은 {fmt.josa(peers, '이에요예요')}.")
    if b.fact("small_sample"):
        s.append("기준 인구가 100명 미만인 작은 표본이라 변화율은 참고로만 봐 주세요.")
    if q.wants_cause:
        s.append(CAUSE_NOTE)
    return headline, " ".join(s)


def _s1_zone(b: Bundle) -> tuple[str, str]:
    q = b.query
    lab, lab_full = _youth(q), fmt.ages_label(q.ages)
    t = b.value("type")
    headline = _s1_headline(lab, t, None, b.value("visit_chg"))
    s = [f"{b.text('place')}({b.text('members')})의 {lab_full} 거주인구는 {_chg(b.value('youth_resd_chg'), end=False)}, "
         f"근무인구는 {_chg(b.value('youth_work_chg'), end=False)}, 방문자는 {_chg(b.value('visit_chg'))}."]
    if q.wants_cause:
        s.append(CAUSE_NOTE)
    return headline, " ".join(s)


def _s1_recommend(b: Bundle) -> tuple[str, str]:
    q = b.query
    lab_full = fmt.ages_label(q.ages)
    top = b.stage_output.get("top") or []
    scope = b.stage_output.get("scope") or "읍면동"
    counts = b.stage_output.get("counts") or {}
    ranks = [b.text(f"rank{i}") for i in range(1, 4) if b.fact(f"rank{i}")]
    type_line = ", ".join(f"{_type_text(t)} {counts.get(t, 0)}곳" for t in ("A", "B", "C", "D", "유지"))
    s: list[str] = []
    corr = b.fact("corr_visit_resd")
    if q.wants_cause and corr:
        r = float(corr.value)  # type: ignore[arg-type]
        if abs(r) < 0.2:
            how = "두 지표는 거의 따로 움직였어요"
        elif r < 0:
            how = "방문이 늘어난 곳일수록 청년 거주가 줄어든 경향이 있었어요"
        else:
            how = "방문이 늘어난 곳일수록 청년 거주도 늘어난 경향이 있었어요"
        headline = "두 지표가 함께 움직였는지는 볼 수 있지만, 원인이라고 단정할 수는 없어요"
        s.append(f"{corr.label}는 {corr.text}예요. {how}.")
        s.append("상관은 함께 움직인 정도일 뿐이라, 관광객 증감이 청년 이동의 원인인지는 이 자료로 알 수 없어요.")
        s.append("일자리·주거비·교통 같은 외부 요인을 함께 확인해야 해요.")
        s.append(f"유형별로는 {type_line}이에요.")
        return headline, " ".join(s)
    if not top:
        return "순위를 만들 자료가 부족해요", "조건에 맞는 읍면동이 없었어요."
    first = top[0]
    word = "가장 많이 늘어난" if first["youth_resd_chg"] > 0 else "가장 덜 줄어든"
    headline = f"{lab_full} 거주가 {word} 곳은 {first['emd_nm']}({fmt.pct(first['youth_resd_chg'])})이에요"
    s.append(f"{scope}을 {lab_full} 거주인구 변화율 순으로 보면 {', '.join(ranks)} 순이에요.")
    s.append(f"43개 읍면동의 유형은 {type_line}이에요.")
    if b.fact("excluded_small"):
        s.append(f"기준 인구가 100명 미만인 {fmt.josa(b.text('excluded_small'), '은는')} 순위에서 뺐어요.")
    if q.wants_cause:
        s.append(CAUSE_NOTE)
    return headline, " ".join(s)


# =========================================================================== Stage 2
def _s2(b: Bundle) -> tuple[str, str]:
    q = b.query
    out = b.stage_output
    area, place = b.text("area"), b.text("place")
    target, t = out.get("target"), out.get("type")
    sugg = b.suggestions()
    if target:
        headline = f"{area}에서는 「{target}」{'을' if fmt.has_batchim(target) else '를'} 먼저 볼 만해요"
    elif sugg:
        headline = f"「{_type_text(t)}」 동네라 관광객 모객보다 머무는 환경을 키우는 제안이 맞아요" if t else "조건을 충족한 제안이 있어요"
    else:
        headline = "조건을 충족한 제안 규칙이 없어요. 지표를 먼저 확인해 주세요"
    s: list[str] = []
    if t:
        s.append(f"{fmt.josa(place, '은는')} Stage 1에서 「{_type_text(t)}」으로 분류됐어요.")
    if t == "유지" and b.fact("near_type"):
        s.append(f"변화가 작아 가장 가까운 유형인 {b.text('near_type')}의 규칙을 참고로 적용했어요.")
    top, total = out.get("top_theme"), b.value("cn_growth:전체")
    if top and fmt.is_num(out.get("top_theme_growth")) and out["top_theme_growth"] > 0:
        s.append(f"{area}의 중국인 카드 소비는 {top}에서 {fmt.pct_abs(out['top_theme_growth'])} 늘었고, 전체로는 {_chg(total)}.")
    elif fmt.is_num(total):
        s.append(f"{area}의 중국인 카드 소비는 전체로 {_chg(total)}.")
    th = q.theme
    if th and b.fact(f"cn_growth:{th}") and th != top:
        extra = f", 개별여행 인당 배율은 {b.text(f'indiv_ratio_cn:{th}')}예요" if b.fact(f"indiv_ratio_cn:{th}") else ""
        s.append(f"질문하신 {th}의 중국인 소비는 {_chg(b.value(f'cn_growth:{th}'), end=not extra)}{extra}.")
    # '주말 소비비'는 낯선 말이라 풀어서 써요: 주말 하루 소비가 평일 하루의 몇 배인지
    if b.fact("peak_dow_cn") and b.fact("weekend_ratio_cn"):
        s.append(f"중국인 소비는 {b.text('peak_dow_cn')}에 가장 많고, 주말 하루 소비는 평일 하루의 {b.text('weekend_ratio_cn')}예요.")
    if b.fact("peak_dow_kr") and b.fact("weekend_ratio_kr"):
        s.append(f"내국인 소비는 {b.text('peak_dow_kr')}에 가장 많고, 주말 하루 소비는 평일 하루의 {b.text('weekend_ratio_kr')}예요.")
    if b.fact("nat_top") and fmt.is_num(b.value("nat_growth_top")) and b.value("nat_growth_top") > 0:
        s.append(f"외국인 방문자 가운데 {b.text('nat_top')} 방문자가 {fmt.pct_abs(b.value('nat_growth_top'))} 늘어 증가 폭이 가장 컸어요.")
    if b.fact("n_rules"):
        s.append(f"제안 규칙 {b.text('n_rules')} 가운데 {b.text('n_fired')}가 조건을 충족했어요.")
    if q.wants_cause:
        s.append(CAUSE_NOTE)
    return headline, " ".join(s)


# =========================================================================== Stage 3
def _s3(b: Bundle) -> tuple[str, str]:
    q = b.query
    place = q.place_name or ""
    fc, rt, cs = b.result("s3_forecast"), b.result("s3_route_beta"), b.result("s3_courses")
    s: list[str] = []
    headline = ""
    if fc and fc.ok:
        delta = float(b.value("supply_change"))
        dv = float(b.value("scenario_delta"))
        verb = "줄면" if delta < 0 else "늘면"
        result = "줄어드는" if dv < 0 else "늘어나는"
        headline = (f"국내선 공급이 {fmt.pct_abs(delta, 0)} {verb} {b.text('target_month')} 입도객은 "
                    f"{fmt.people(abs(dv))} {result} 것으로 계산돼요 (ε {b.text('elasticity')} 가정)")
        s.append(f"전년 동월({b.text('baseline_month')}) 실적 {b.text('baseline_total')}을 기준선으로, 국내선 공급 "
                 f"{b.text('supply_change')}와 탄력성 ε {fmt.josa(b.text('elasticity'), '을를')} 가정하면 {b.text('target_month')} 입도객은 "
                 f"{b.text('scenario_total')}으로 계산돼요.")
        others = [f for f in b.facts() if f.key.startswith("scenario_total_e") and f.key != f"scenario_total_e{float(b.value('elasticity')):.1f}"]
        if others:
            s.append("탄력성을 바꾸면 " + ", ".join(f"ε {f.key.split('_e')[1]}일 때 {f.text}" for f in others) + "이에요.")
        if "개별" in q.question and b.fact("baseline_indiv"):
            s.append(f"개별여행 입도객은 {b.text('baseline_indiv')}에서 {b.text('scenario_indiv')}으로 계산돼요.")
    if rt and rt.ok and rt.fact("n_routes"):
        n, k = int(b.value("n_routes") or 0), int(b.value("n_sensitive") or 0)
        if n == 0:
            s.append(f"참조표에는 {fmt.josa(place, '을를')} 지나는 노선이 없어요.")
        elif k == 0:
            s.append(f"{fmt.josa(place, '을를')} 지나는 노선 {n}개 가운데 관광 수요와 뚜렷하게 함께 움직인 노선은 없었어요.")
        else:
            s.append(f"{fmt.josa(place, '을를')} 지나는 노선 {n}개 가운데 관광 수요와 함께 움직인 노선은 {k}개이고, "
                     f"민감도가 가장 큰 노선은 {b.text('route1')}(β {b.text('route1_beta')}, R² {b.text('route1_r2')})이에요.")
            if not headline:
                headline = f"{fmt.josa(place, '을를')} 지나는 노선 가운데 관광 수요에 가장 민감한 노선은 {b.text('route1')}이에요"
        if not headline:
            headline = f"{fmt.josa(place, '을를')} 지나는 노선에서 관광 수요와 함께 움직인 노선은 찾지 못했어요"
    if cs:
        courses = cs.data.get("courses", [])
        gaps = cs.data.get("gaps", [])
        if courses:
            s.append(f"거점에서 {place}까지 오는 코스는 {len(courses)}개예요: " + "; ".join(c["text"] for c in courses) + ".")
            if not headline:
                c0 = courses[0]
                how = "환승 없이" if c0["transfers"] == 0 else f"환승 {c0['transfers']}회로"
                headline = f"{place}까지는 {c0['hub_nm']}에서 {c0['routes'][0]}번으로 {how} 갈 수 있어요"
        else:
            s.append(f"거점에서 {place}까지 직행이나 환승 1회로 닿는 노선이 참조표에 없어 접근성 공백으로 표시했어요.")
            if not headline:
                headline = f"{place}까지 직행이나 환승 1회로 닿는 노선이 없어요 (접근성 공백)"
        if courses and gaps:
            s.append(f"{fmt.join_names(gaps)}에서는 직행이나 환승 1회로 닿는 노선이 없어 접근성 공백으로 표시했어요.")
    if fc and fc.ok:
        s.append("이 시나리오는 예측이 아니라 가정에 따른 계산이에요.")
    if q.wants_cause:
        s.append(CAUSE_NOTE)
    return headline or "Stage 3 분석 결과예요", " ".join(s)


def template_text(b: Bundle) -> tuple[str, str]:
    """LLM 없이 수치만으로 만드는 한 줄 결론과 해설."""
    if not b.ok:
        return (b.message or "분석을 하지 못했어요"), ""
    if b.stage == 1:
        if b.intent == "recommend":
            return _s1_recommend(b)
        if b.query.place_kind == "zone":
            return _s1_zone(b)
        return _s1_emd(b)
    if b.stage == 2:
        return _s2(b)
    if b.stage == 3:
        return _s3(b)
    ev = b.evidence()
    if ev:  # 자유 질문: 조회 결과 표
        return ev[0].title, f"조건에 맞는 결과가 {len(ev[0].rows)}행 나왔어요. 아래 표와 접어 둔 SQL을 확인해 주세요."
    return "결과를 정리했어요", ""


# =========================================================================== 다음 질문
def next_questions(b: Bundle) -> list[NextQuestion]:
    """답마다 이어서 물을 질문 3개. 그중 하나는 다음 단계로 가요."""
    q = b.query
    place = q.place_name
    if b.stage == 1:
        if b.intent == "recommend":
            top = (b.stage_output.get("top") or [{}])[0].get("emd_nm")
            out = []
            if top:
                out.append(NextQuestion(label=f"{top} 진단 보기", question=f"{top} 청년 인구 진단", kind="follow_up", stage=1))
                out.append(NextQuestion(label=f"{top} 처음부터 끝까지", question=f"{top} 처음부터 끝까지", kind="next_stage", stage=2))
            out.append(NextQuestion(label="읍면만 보기" if q.emd_type != "읍면" else "동 지역만 보기",
                                    question=("청년이 늘어난 읍면 순위" if q.emd_type != "읍면" else "청년이 늘어난 동 지역 순위"),
                                    kind="follow_up", stage=1))
            return out[:3]
        if not place:
            return []
        second = (NextQuestion(label="비슷한 읍면과 비교", question=f"{place} 비슷한 읍면과 비교", kind="follow_up", stage=1)
                  if b.intent != "peers" else
                  NextQuestion(label="진단 다시 보기", question=f"{place} 청년 인구 진단", kind="follow_up", stage=1))
        third = (NextQuestion(label="30대만 보기", question=f"{place} 30대만 보면?", kind="follow_up", stage=1)
                 if sorted(q.ages) == [20, 30] else
                 NextQuestion(label="20·30대로 보기", question=f"{place} 청년 인구 진단", kind="follow_up", stage=1))
        return [NextQuestion(label="이 동네에 누가 올까? → Stage 2", question=f"{place}에 누가 올까?", kind="next_stage", stage=2),
                second, third]
    if b.stage == 2:
        p = place or "제주"
        out = []
        if q.place_kind == "emd":
            out.append(NextQuestion(label="어떻게 데려올까? → Stage 3", question=f"{p} 어떻게 데려올까?", kind="next_stage", stage=3))
        else:
            out.append(NextQuestion(label="감편 시나리오 보기 → Stage 3", question="국내선 10% 감편 시 입도객은?", kind="next_stage", stage=3))
        theme = "숙박" if q.theme == "식음료" else "식음료"
        out.append(NextQuestion(label=f"{theme}만 보기", question=f"{p} {theme} 중국인 소비 변화", kind="follow_up", stage=2))
        if q.place_kind in ("emd", "zone"):
            out.append(NextQuestion(label="청년 인구 진단 보기", question=f"{p} 청년 인구 진단", kind="follow_up", stage=1))
        return out
    if b.stage == 3:
        p = (place + " ") if place and q.place_kind == "emd" else ""
        out = []
        if q.place_kind == "emd":
            out.append(NextQuestion(label="최종 제안서 받기", question=f"{place} 최종 제안서", kind="report", stage=None))
        sc = b.value("supply_change")
        other = "20%" if not fmt.is_num(sc) or abs(sc) < 0.15 else "10%"
        out.append(NextQuestion(label=f"감편 {other}면?", question=f"{p}감편 {other}면?", kind="follow_up", stage=3))
        out.append(NextQuestion(label="탄력성 1.5로 보기", question=f"{p}감편 10% 탄력성 1.5면?", kind="follow_up", stage=3))
        return out
    return []


# =========================================================================== LLM 해설용 근거 묶음
_DROP_S1_EMD = ("rank", "count_", "excluded_small", "ages", "peer1", "peer2", "peer3")


def select_facts(b: Bundle, limit: int = 30) -> list:
    """해설에 필요한 지표만 골라요 (프롬프트가 짧을수록 로컬 LLM이 빠르고 덜 헷갈려요)."""
    facts = b.facts()
    if b.stage == 1 and b.intent != "recommend":
        facts = [f for f in facts if not f.key.startswith(_DROP_S1_EMD)]
    elif b.stage == 2:
        want: list[str] = []
        for s in b.suggestions():
            want += s.evidence_keys
        out = b.stage_output
        for th in dict.fromkeys([out.get("top_theme"), b.query.theme]):
            if th:
                want += [f"cn_growth:{th}", f"cn_share:{th}", f"indiv_ratio_cn:{th}"]
        keep_prefix = ("place", "area", "type", "target", "cn_growth:전체", "weekend_ratio", "peak_dow", "nat_",
                       "n_rules", "n_fired", "focus_theme")
        facts = [f for f in facts if f.key in want or f.key.startswith(keep_prefix)]
    elif b.stage == 3:
        facts = [f for f in facts if not f.key.startswith(("route3", "route2_r2", "route2_implied"))]
    return facts[:limit]


def free_payload(b: Bundle, max_rows: int = 40) -> str:
    """자유 질문의 조회 결과를 LLM에 넘길 글로 바꿔요 (집계 결과 표만, 최대 max_rows 행)."""
    ev = b.evidence()[0]
    lines = [f"질문: {b.query.question}", f"표 제목: {ev.title}", "컬럼: " + " | ".join(ev.columns), "결과:"]
    for r in ev.rows[:max_rows]:
        lines.append("- " + " | ".join(_free_cell(v) for v in r))
    return "\n".join(lines)


def _free_cell(v: object) -> str:
    """조회 결과 칸 하나. 큰 정수는 천 단위 쉼표를 붙여요 (모델이 '9730808명'처럼 그대로 옮겨 적지 않게).

    연도(2025)나 노선 번호처럼 네 자리 이하인 정수는 그대로 둬요.
    """
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.4g}"
    if isinstance(v, int) and not isinstance(v, bool) and abs(v) >= 10_000:
        return f"{v:,}"
    return str(v)


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def stage_question(stage: int, place: str) -> str:
    """연계 실행에서 단계마다 LLM 해설에 넘기는 질문.

    '처음부터 끝까지'는 단계의 질문이 아니라서, 작은 모델이 고를 문장을 못 찾고 지시문을 되받아 적어요.
    """
    return {
        1: f"{place}의 청년 인구는 어떻게 변했고, 어떤 유형의 동네인가요?",
        2: f"{place}에는 어떤 관광객을 먼저 볼 만한가요?",
        3: f"국내선 공급이 바뀌면 입도객은 어떻게 되고, {place}에는 어떻게 올 수 있나요?",
    }[stage]


def llm_payload(b: Bundle, max_facts: int = 30) -> str:
    """LLM에 넘길 근거. 집계된 지표와 규칙이 만든 제안만 담아요. 원자료와 근거표 원문은 넣지 않아요.

    글은 근거 목록으로 끝나요. 끝에 지시문을 덧붙이면 작은 모델이 지시문을 답으로 되받아 적는 일이 잦았어요.
    가정값 표시는 시스템 지시문 7번과 검증기가 맡아요.
    """
    headline, draft = template_text(b)
    if b.stage == 2:
        # 앞 단계를 잇는 문장('Stage 1에서 …으로 분류됐어요')은 빼요. 작은 모델이 이 문장과 한 줄 결론을 한 문장으로 섞었어요.
        draft = " ".join(x for x in _SENTENCE.split(draft) if "Stage 1에서" not in x)
    main_period = b.text("period", "")
    lines = [f"질문: {b.query.stage_question or b.query.question}",
             f"단계: Stage {b.stage} {STAGE_TITLE.get(b.stage or 0, '')}".strip(),
             f"한 줄 결론: {headline}",
             f"해설 초안: {draft}",
             "근거:"]
    for f in select_facts(b, max_facts):
        label = f.label.replace("(P1)", "(최근 기간)").replace("(P0)", "(직전 기간)")
        extra = []
        if f.period and f.period not in main_period:
            extra.append(f"기간 {f.period}")
        if f.flag == "assumption":
            extra.append("가정값")
        elif f.flag == "small_sample":
            extra.append("작은 표본")
        elif f.flag == "proxy_zone":
            extra.append("참고 지구 값")
        elif f.flag == "access_gap":
            extra.append("접근성 공백")
        lines.append(f"- {label}: {f.text}" + (f" ({'; '.join(extra)})" if extra else ""))
    if b.suggestions():
        lines.append("규칙이 만든 제안:")
        for s in b.suggestions():
            lines.append(f"- {s.rule_id} {s.text} (근거: {' · '.join(s.evidence_text)})")
    if b.query.wants_cause:
        lines.append("주의: 원인을 묻는 질문이에요. 원인을 설명하지 말고 '원인은 이 자료만으로 단정할 수 없어요.'라고 밝힌 뒤, "
                     "값이 어떻게 변했는지와 따로 확인할 외부 요인(일자리·주거비·교통)을 말해요.")
    return "\n".join(lines)
