"""해석기(Parser): 질문을 단계·장소·기간·연령·업종·시나리오로 구조화해요.

규칙 파서는 LLM 없이 동작하고(템플릿 모드), LLM 모드에서는 규칙 파서가 확신하지 못한 질문만 LLM에 넘겨요.
어느 쪽이든 장소는 참조표로 다시 확인하고, 결과는 '이렇게 이해했어요' 확인 카드로 보여 줘요.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .. import fmt
from ..data.refs import Refs
from ..schemas import INTENT_LABEL, STAGE_TITLE, Chip, ConfirmCard, ParsedQuery
from ..settings import AppConfig

_S3 = ["감편", "증편", "항공", "국내선", "공급석", "입도객", "시나리오", "버스", "노선", "코스", "루트", "오는 길",
       "오는길", "데려올", "데려오", "오게", "접근성", "환승", "가는 법", "가는 방법", "어떻게 가", "어떻게 와"]
_S2 = ["관광객", "외국인", "중국인", "손님", "소비", "카드", "업종", "요일", "주말", "평일", "누가 올", "누가 채",
       "모객", "단체", "개별", "국적", "매출", "빈자리", "결제"]
_S1 = ["청년", "20대", "30대", "2030", "인구", "거주", "정착", "머무", "떠나", "떠났", "빠지", "빠져", "유형", "한 달 살이",
       "한달살이", "살기 좋", "귀촌", "이주", "근무", "일자리", "활력", "진단", "정주"]
_CHAIN = ["처음부터 끝까지", "끝까지", "전체 제안서", "최종 제안서", "전 단계", "세 단계"]
_RECOMMEND = ["추천", "순위", "배정", "살기 좋", "어느 읍면", "어느 동네", "어느 곳", "어디가", "어디에", "어디야", "상위", "랭킹"]
_PEERS = ["비슷한", "유사한", "닮은", "비슷한 곳"]
_TREND = ["추이", "흐름", "변화 추", "어떻게 변"]
# 원인을 묻거나('왜'), 원인을 전제로 확인을 구하는('~해서 ~한 거지?') 표현
_CAUSE = re.compile(r"때문|탓|원인|왜\s|왜\?|이유|초래|덕분|떠나게"
                    r"|(어서|아서|해서|여서|라서|니까)[^?.]*(거지|거죠|맞지|맞죠|잖아|아닌가|아냐|아니야)")
_FOLLOW = ["거기", "그 동네", "이 동네", "그곳", "그 곳", "여기", "같은 곳"]
_AGE_WORDS = {"10대": 10, "20대": 20, "30대": 30, "40대": 40, "50대": 50, "60대": 60, "70대": 70}


_PLAN = ["데려올", "데려오", "오게 하", "오게할", "어떻게 오", "어떻게 와"]
_COURSE = ["코스", "루트", "오는 길", "오는길", "가는 법", "가는 방법", "어떻게 가"]
_PERIOD_WORDS = ["작년", "전년", "지난해", "올해", "최근"]
_DECLINING = re.compile(r"(빠지는|빠져나가는|줄어드는|줄고 있는|떠나는|감소하는)[^.?!]{0,10}(읍면동|읍면|동네|곳)")
_GROWING = re.compile(r"(늘어나는|늘고 있는|모이는|증가하는|버티는)[^.?!]{0,10}(읍면동|읍면|동네|곳)")
_PLACE_FREE = {"recommend", "forecast"}  # 장소 없이도 답할 수 있는 분석
_CHANGE = re.compile(r"늘어난|늘어나는|늘었|줄어든|줄어드는|줄었|살기 좋|추천|배정|빠지는|떠나는")  # 추천 순위(변화율)에 맞는 표현
# 준비된 분석보다 자유 질의에 가까운 표현 (LLM 모드에서는 LLM이 한 번 더 판단해요)
_FREE_HINT = re.compile(r"가장\s*(많|높|낮|적|큰|작)|몇\s*(명|개|곳|건)|얼마|평균|합계|상위\s*\d|top\s*\d", re.I)


@dataclass
class ParseTrace:
    """규칙 파서가 얼마나 확신했는지 (LLM 호출 여부 판단용)."""

    stage_hits: dict[int, int]
    place_found: bool
    follow_up: bool
    explicit_intent: bool
    in_scope: bool
    free_hint: bool = False
    cause: bool = False

    @property
    def confident(self) -> bool:
        return (self.in_scope and not self.free_hint
                and (self.place_found or self.follow_up or self.explicit_intent or self.cause))


class RuleParser:
    def __init__(self, refs: Refs, config: AppConfig):
        self.refs = refs
        self.config = config

    def parse(self, question: str, last: ParsedQuery | None = None) -> tuple[ParsedQuery, ParseTrace]:
        q = question.strip()
        compact = "".join(q.split())
        notes: list[str] = []
        hits = {1: self._count(q, compact, _S1), 2: self._count(q, compact, _S2), 3: self._count(q, compact, _S3)}

        # ---- 질문에 직접 나온 값
        places = self.refs.find_places(q)
        place = next((m for k in ("emd", "zone", "city") for m in places if m.kind == k), None)
        hub = next((m for m in places if m.kind == "hub"), None)
        ages = self._ages(q, compact)
        last_n = int(m.group(1)) if (m := re.search(r"최근\s*(\d{1,2})\s*개월", q)) else None
        year = int(m.group(1)) if (m := re.search(r"(20\d{2})\s*년", q)) else None
        month = int(m.group(1)) if (m := re.search(r"(?<!\d)(1[0-2]|[1-9])\s*월(?!\s*살이)", q)) else None
        supply = self._supply(q)
        elasticity = float(m.group(1)) if (m := re.search(r"(?:탄력성|ε|엡실론)\s*(?:은|는|이|가|을|를)?\s*(\d+(?:\.\d+)?)", q)) else None
        if supply is not None or elasticity is not None:
            hits[3] += 2
        chain = any(w in q for w in _CHAIN)
        theme_word = self.refs.find_theme(q)
        auto = "declining" if _DECLINING.search(q) else ("growing" if _GROWING.search(q) else None)

        # ---- 후속 질문인지: 장소는 없지만 바꿀 값(단계·연령·기간·테마·가정)이나 지시어가 있을 때
        signals = (max(hits.values()) > 0 or ages is not None or last_n is not None or year is not None
                   or theme_word is not None or chain or any(w in q for w in _PERIOD_WORDS)
                   or any(w in q for w in _PEERS + _RECOMMEND + _TREND))
        follow = bool(last) and place is None and (any(w in q for w in _FOLLOW) or signals)
        in_scope = place is not None or signals or follow

        # ---- 단계
        stage: int | None
        if chain:
            stage = 1
        elif max(hits.values()) == 0:
            stage = last.stage if (last and follow) else (1 if place else None)
        else:
            top = max(hits.values())
            winners = [s for s, v in hits.items() if v == top]
            stage = winners[0] if len(winners) == 1 else (last.stage if last and last.stage in winners else winners[-1])
        if not in_scope:
            stage = None

        # ---- 장소
        place_kind = place_key = place_name = None
        if place:
            place_kind, place_key, place_name = place.kind, place.key, place.name
            if place.ambiguous:
                notes.append(f"'{place.matched}'은(는) 여러 곳에 있어 {self.refs.emd(place.key).full_nm}으로 이해했어요.")
        elif follow and last and last.place_key and not auto:
            place_kind, place_key, place_name = last.place_kind, last.place_key, last.place_name

        # ---- 의도
        intent, explicit = self._intent(q, stage, chain, place_kind, supply, hub is not None)
        if follow and last and not explicit and not chain and last.stage == stage and last.intent not in ("chain", "free"):
            intent = last.intent
        if (follow and last and stage == 3 and last.stage == 3 and intent == "forecast" and place_kind == "emd"
                and last.intent in ("plan", "routes") and not place):
            intent = last.intent  # '감편 20%면?'처럼 가정만 바꾼 후속 질문은 같은 분석을 다시 해요
        if intent in _PLACE_FREE and not place:
            place_kind = place_key = place_name = None
            auto = None
        if intent == "free":
            stage = None
        if stage is None:
            intent = "free"

        # ---- 이어받는 값
        if ages is None:
            ages = list(last.ages) if (last and follow and last.stage == stage) else list(self.config.analysis.youth_age_bands)
        theme = theme_word if stage == 2 else None
        if follow and last and stage == last.stage:
            last_n = last_n if last_n is not None else last.last_n_months
            year = year if year is not None else last.year
            theme = theme if theme is not None else (last.theme if stage == 2 else None)
            if stage == 3:
                supply = supply if supply is not None else last.supply_change
                elasticity = elasticity if elasticity is not None else last.elasticity
                month = month if month is not None else last.target_month
        emd_type = None
        if intent == "recommend" or auto:
            # '읍면동'(전체)과 '읍면'(읍·면만)을 구분해요.
            emd_type = "읍면" if re.search(r"읍면(?!동)", compact) else ("동" if ("동 지역" in q or "동지역" in compact) else None)

        parsed = ParsedQuery(
            question=q, stage=stage, intent=intent, place_kind=place_kind, place_key=place_key, place_name=place_name,
            auto_place=auto if not place_key else None, ages=ages, last_n_months=last_n, year=year, theme=theme,
            emd_type=emd_type, supply_change=supply, elasticity=elasticity, target_month=month if stage == 3 else None,
            hub_id=hub.key if hub else None, wants_cause=bool(_CAUSE.search(q + " ")), notes=notes, parsed_by="rule")
        return parsed, ParseTrace(hits, place is not None, follow, explicit or chain, in_scope,
                                  bool(_FREE_HINT.search(q)) and not (intent == "recommend" and _CHANGE.search(q)),
                                  parsed.wants_cause)

    # ------------------------------------------------------------------ 세부 규칙
    @staticmethod
    def _count(q: str, compact: str, words: list[str]) -> int:
        return sum(1 for w in words if w in q or w.replace(" ", "") in compact)

    @staticmethod
    def _ages(q: str, compact: str) -> list[int] | None:
        if re.search(r"20\s*[·,/~-]?\s*30\s*대|2030|청년", compact):
            only = re.search(r"(20|30)대만", compact)
            return [int(only.group(1))] if only else [20, 30]
        found = sorted({v for k, v in _AGE_WORDS.items() if k in compact})
        return found or None

    @staticmethod
    def _supply(q: str) -> float | None:
        if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:%|퍼센트|프로)\s*(감편|감소|줄|축소|증편|증가|늘|확대)", q):
            v = float(m.group(1)) / 100
            return -v if m.group(2) in ("감편", "감소", "줄", "축소") else v
        if m := re.search(r"(감편|감소|축소|증편|증가|확대)[^0-9%]{0,6}(\d+(?:\.\d+)?)\s*(?:%|퍼센트|프로)", q):
            v = float(m.group(2)) / 100
            return -v if m.group(1) in ("감편", "감소", "축소") else v
        return None  # 숫자가 없으면 설정의 기본 가정을 써요

    @staticmethod
    def _intent(q: str, stage: int | None, chain: bool, place_kind: str | None, supply: float | None,
                has_hub: bool) -> tuple[str, bool]:
        """(의도, 질문에 의도 단어가 직접 있었는지)."""
        if chain:
            return "chain", True
        if stage == 1:
            if any(w in q for w in _PEERS):
                return "peers", True
            if any(w in q for w in _RECOMMEND):
                return "recommend", True
            if any(w in q for w in _TREND):
                return "trend", True
            if place_kind is None or place_kind == "city":
                return "recommend", False
            return "diagnose", False
        if stage == 2:
            return "shift", False
        if stage == 3:
            wants_plan = any(w in q for w in _PLAN)
            wants_course = any(w in q for w in _COURSE) or has_hub
            wants_route = any(w in q for w in ("버스", "노선"))
            wants_fc = supply is not None or any(w in q for w in ("감편", "증편", "입도객", "시나리오", "공급"))
            explicit = wants_plan or wants_course or wants_route or wants_fc
            if place_kind != "emd":
                # 읍면동 없이 답할 수 있는 것은 수요 시나리오뿐이에요. 나머지는 확인 카드에서 읍면동을 묻거나
                # (LLM 모드에서는) 자유 질문으로 넘겨요.
                if wants_fc:
                    return "forecast", True
                if wants_plan:
                    return "plan", True
                if wants_course:
                    return "courses", True
                return ("routes", True) if wants_route else ("free", False)
            if wants_plan or sum([wants_course, wants_route, wants_fc]) != 1:
                return "plan", explicit
            return ("courses" if wants_course else ("routes" if wants_route else "forecast")), True
        return "free", False


# --------------------------------------------------------------------------- 확인 카드
def confirm_card(q: ParsedQuery, refs: Refs, config: AppConfig) -> ConfirmCard:
    """'이렇게 이해했어요' 카드. 실행 전에 장소·기간·연령·업종·가정치를 보여 줘요."""
    chips: list[Chip] = []
    warnings = list(q.notes)
    runnable = True
    needs_emd = q.intent in ("diagnose", "trend", "peers", "plan", "routes", "courses", "chain")
    if q.place_name:
        chips.append(Chip(label="장소", value=q.place_name))
    elif q.auto_place:
        word = "줄어든" if q.auto_place == "declining" else "늘어난"
        scope = "읍면" if q.emd_type == "읍면" else ("동" if q.emd_type == "동" else "읍면동")
        chips.append(Chip(label="장소", value=f"자동 선택 · 청년 거주가 가장 많이 {word} {scope}"))
    elif q.intent == "recommend":
        chips.append(Chip(label="장소", value="읍면" if q.emd_type == "읍면" else ("동 지역" if q.emd_type == "동" else "43개 읍면동")))
    elif q.stage in (2,) or q.intent == "forecast":
        chips.append(Chip(label="장소", value="제주 전체"))
    if needs_emd and q.place_kind != "emd" and not q.auto_place:
        if q.stage == 1 and q.place_kind == "zone" and q.intent != "chain":
            pass  # 지구는 속한 읍면동을 묶어 진단해요
        elif q.stage == 1 and q.wants_cause and q.place_kind is None:
            pass  # 장소 없는 원인 질문은 43개 읍면동 전체로 답해요
        else:
            warnings.append("읍면동을 하나 골라 주세요. (예: 성산읍, 구좌읍, 노형동)")
            runnable = False
    if q.stage is None or q.intent == "free":
        warnings.append("준비된 분석에 맞지 않는 자유 질문이에요. LLM 모드에서만 답할 수 있어요.")
    if q.stage == 1 or q.intent == "chain":
        chips.append(Chip(label="연령", value=fmt.ages_label(q.ages)))
    if q.stage in (1, 2) or q.intent == "chain":
        if q.year:
            period = f"{q.year}년 vs {q.year - 1}년"
        elif q.last_n_months:
            period = f"최근 {q.last_n_months}개월 vs 전년 같은 기간"
        else:
            period = f"최근 {config.analysis.period_months}개월 vs 직전"
        chips.append(Chip(label="기간", value=period))
    if q.stage == 2 and q.theme:
        chips.append(Chip(label="테마", value=q.theme))
    if q.stage == 3 or q.intent == "chain":
        c3 = config.stage3
        if q.intent in ("plan", "forecast", "routes", "chain"):
            sc = c3.supply_change_default if q.supply_change is None else q.supply_change
            el = c3.elasticity_default if q.elasticity is None else q.elasticity
            chips.append(Chip(label="가정", value=f"국내선 공급 {fmt.pct(sc, 0)} · 탄력성 {el:.1f}"))
            if q.target_month:
                chips.append(Chip(label="대상 월", value=f"{q.target_month}월"))
        if q.hub_id and q.hub_id in refs.hubs:
            chips.append(Chip(label="출발 거점", value=refs.hubs[q.hub_id].hub_nm))
    label = INTENT_LABEL.get(q.intent, q.intent)
    if q.intent == "recommend" and q.wants_cause:
        label = "전체 읍면동 비교"
    if q.intent == "chain":
        label = "1~3단계 전체"
    elif q.stage and q.intent != "free":
        label = f"{q.stage}단계 {STAGE_TITLE[q.stage]} · {label}"
    chips.append(Chip(label="분석", value=label))
    if q.wants_cause:
        warnings.append("원인은 이 자료만으로 단정할 수 없어요. 함께 움직인 지표와 확인할 외부 요인으로 답할게요.")
    return ConfirmCard(query=q, chips=chips, warnings=warnings, runnable=runnable)
