"""검증기(Verifier): 에이전트가 말할 수 있는 범위를 코드로 제한해요.

| 장치           | 막는 문제                         |
|----------------|-----------------------------------|
| 숫자 대조      | 해설 속 숫자와 근거표 불일치      |
| 인과 표현 가드 | '때문에·원인은·초래' 같은 단정    |
| 참조 대조      | 존재하지 않는 노선·읍면동         |
| 제안 근거      | 규칙 ID·근거 지표가 없는 제안     |
| 숫자-지표 짝   | 맞는 숫자를 다른 지표의 값처럼 씀 |
| 초안 충실도    | 숫자를 초안과 다른 대상에 붙임    |
| 예측·추측 가드 | '올 거예요', '가능성이 있어요'    |
| 가정치 표시    | 시나리오를 예측으로 오인          |
| 기간 확인      | 기간이 다른 데이터 혼합           |
| 반출 게이트    | 식별 컬럼·소집단 노출             |
"""

from __future__ import annotations

import re
from typing import Any

from .. import fmt
from ..data.refs import Refs
from ..schemas import Check, Fact, Verification
from ..settings import AppConfig
from ..tools.output import export_check
from .stages import Bundle

# 숫자 + 단위 배수. 숫자 바로 뒤의 만·억은 조사가 붙어도 배수로 읽어요 ('12만명', '100만이 넘는', '5억원').
# 배수로 읽지 않으면 '24만명'이 늘 허용하는 수 24로 통과해 버려요. '2만큼'의 '만'과 다른 낱말의 '천'은 배수가 아니에요.
_NUM = re.compile(r"(?<![A-Za-z0-9.,])([-+−]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
                  r"(\s*(?:%|퍼센트|[십백천]?[만억](?!큼)|천(?:(?![가-힣])|(?=\s*(?:명|원|개|곳|회|대|건|여)))))?")
_APPROX = re.compile(r"^\s*(?:여(?=\s*(?:명|원|개|곳|회|대|건)))?\s*")  # '37만여 명'의 '여'는 건너뛰어요
_ROUTE = re.compile(r"(?<![\d.,])(\d{2,4}(?:-\d{1,2})?)\s*번(?![째지호])")
_MULT = {"천": 1e3, "만": 1e4, "십만": 1e5, "백만": 1e6, "천만": 1e7, "억": 1e8, "십억": 1e9, "백억": 1e10, "천억": 1e11}

CAUSAL_TERMS = ["때문", "탓에", "탓으로", "탓이", "원인", "초래", "야기", "로 인해", "로 인한", "덕분", "영향으로",
                "결과로", "이유는", "이유로", "유발", "떠나게 했", "하게 만들", "밀어냈", "몰아냈"]
HEDGE_TERMS = ["단정", "수 없", "어렵", "아니", "확인이 필요", "확인해야", "따로 확인", "뜻하지 않", "못해", "못했",
               "불확실", "모르", "가리지 못", "확인되지 않"]
_STRUCTURAL = {0.0, 1.0, 2.0, 3.0, 12.0, 24.0, 43.0, 100.0}
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
# 단정적 예측 표현 (시나리오 문장은 '가정'·'계산'이라는 말이 있으면 허용)
_PREDICT = re.compile(
    r"(올|갈|늘어날|줄어들|증가할|감소할|늘|줄|될|살아날|커질|많아질|떠날)\s*(거예요|거에요|것이에요|것입니다|겁니다)"
    r"|예상(돼|되|됩|됨)|예측(돼|되|됩|됨)|전망(이|입|돼|되|됩)|확실해요|틀림없"
    r"|가능성이|것 같아요|것 같습니다|듯해요|듯합니다|아마도?\s"
    r"|면\s[^.]{0,40}(늘릴|늘어날|끌어올|끌어들일|살릴|살아날|높일|키울)\s*수 있")
_PREDICT_OK = ("가정", "계산", "시나리오", "탄력성", "ε")  # 가정을 밝힌 문장 ('탄력성이 1.0일 때 예상되는 수치')


# 숫자가 가리키는 대상을 나타내는 낱말 (초안 충실도 검사용). 읍면동·국적·거점 이름은 참조표에서 더해요.
_ENTITY_WORDS = ["내국인", "중국인", "외국인", "주말", "개별", "단체", "거주", "근무", "방문", "정주", "비중",
                 "식음료", "숙박", "쇼핑", "소매", "교통", "문화", "레저", "입도객", "기준선", "노선", "코스"]


# 초안에 없는 순위·평가를 덧붙였는지 볼 때 쓰는 최상급 표현 ('가장 빠른 코스'처럼 근거 없는 말을 막아요)
_SUPER = re.compile(r"(가장|제일)\s+([가-힣])|(최고|최대|최저|최소|최적|유일|압도적|독보적)")
_BIG, _SMALL = "큰컸크높많", "작낮적덜"


# 지표의 정의를 풀어 쓸 때 함께 나와도 되는 낱말 (초안 충실도 검사에서 다른 대상으로 보지 않아요)
# 예) '거주인구 가운데 20·30대 비중은 17.5%예요', '정주비는 거주·근무·방문 인구 가운데 거주인구의 비중이에요'
_DEFINITION_WORDS = {"youth_share": {"거주"}, "settle_ratio": {"거주", "근무", "방문"}}


_SUPER_SAME = {"최고": "가장 큰", "최대": "가장 큰", "최저": "가장 작은", "최소": "가장 작은"}


def superlatives(text: str) -> set[str]:
    """최상급 표현을 뜻이 같은 것끼리 묶어 뽑아요. '가장 큰'·'가장 높은'·'가장 많이'·'최고'·'최대'는 같은 표현으로 봐요."""
    out: set[str] = set()
    for m in _SUPER.finditer(text):
        if m.group(3):
            out.add(_SUPER_SAME.get(m.group(3), m.group(3)))
        else:
            ch = m.group(2)
            out.add("가장 " + ("큰" if ch in _BIG else "작은" if ch in _SMALL else ch + "…"))
    return out


# 배율의 방향. 주말 소비비는 '주말 하루 소비 ÷ 평일 하루 소비', 개별여행 인당 배율은 '개별 ÷ 단체'예요.
# 분자를 '~에 비해'로 앞세우면 방향이 뒤바뀐 문장이에요 ('주말에 비해 평일 소비가 0.89배').
_REVERSED = [
    ("weekend_ratio", re.compile(r"주말[^.,]{0,6}(?:에\s*비해|보다|대비)[^.]{0,20}평일"), "주말과 평일"),
    ("indiv_ratio", re.compile(r"개별[^.,]{0,8}(?:에\s*비해|보다|대비)[^.]{0,20}단체"), "개별과 단체"),
]


def _alts(word: str) -> str:
    """'쇼핑·소매' → '쇼핑|소매' (둘 중 하나만 있어도 인정)."""
    return "|".join(w for w in re.split(r"[·/]", word) if w)


def fact_anchors(f: Fact) -> list[str]:
    """그 값을 쓰는 문장에 함께 있어야 하는 낱말. 항목마다 '|'로 구분한 것 중 하나가 있으면 돼요."""
    k = f.key
    if k.startswith("youth_resd"):
        return ["거주|사는|살고"]
    if k.startswith("youth_work"):
        return ["근무|일하"]
    if k in ("visit_p1", "visit_chg"):
        return ["방문"]
    if k == "youth_share":
        return ["비중|비율"]
    if k == "settle_ratio":
        return ["정주"]
    if k.startswith("foreign_resd"):
        return ["외국인"]
    if k == "weekend_ratio":
        return ["주말"]
    if k == "corr_visit_resd":
        return ["상관"]
    if k.startswith("rank"):
        return [f.text.split()[0]]
    if k.startswith("peer") and k.endswith("_resd_chg"):
        return [f.label.split()[0]]
    if ":" in k:
        metric, theme = k.split(":", 1)
        th = "전체|모두|합계|총" if theme == "전체" else _alts(theme)
        if metric == "cn_growth":
            return [th]
        if metric == "cn_share":
            return [th, "비중|비율"]
        if metric == "indiv_ratio_cn":
            return [th, "개별"]
        if metric == "indiv_ratio_kr":
            return [th, "개별", "내국인"]
    if k == "weekend_ratio_cn":
        return ["중국인", "주말"]
    if k == "weekend_ratio_kr":
        return ["내국인", "주말"]
    if k == "nat_growth_top":
        return [f.label.split()[0]]
    if k == "nat_share_top":
        return [f.label.split()[0], "비중|비율"]
    if k in ("baseline_indiv", "scenario_indiv"):
        return ["개별"]
    if k == "supply_change":
        return ["공급|감편|증편|항공|좌석|국내선"]
    if k == "elasticity":
        return ["ε|탄력"]
    if m := re.match(r"route\d+_(beta|r2|implied)$", k):
        no = re.match(r"([\d-]+)번", f.label)
        base = [no.group(1)] if no else []
        return base + {"beta": ["β|민감"], "r2": [], "implied": ["이용|승객|수요"]}[m.group(1)]
    return []


_UNITS = ("%", "배", "명", "곳", "개월", "개", "원", "회", "위", "월", "년", "대", "일", "행")


def _numbers(text: str) -> list[tuple[float, int, float, str, str]]:
    """문장에서 숫자를 뽑아요: (값, 소수 자릿수, 단위 배수, 원문, 뒤따르는 단위).

    '10만 493명', '1억 2,000만 원'처럼 나눠 쓴 우리말 큰 수는 하나로 합쳐요.
    """
    found = []
    for m in _NUM.finditer(text):
        tail = text[m.end(): m.end() + 2]
        if tail.lstrip().startswith("번") and _ROUTE.match(text, m.start(2)):
            continue  # 노선 번호는 참조 대조에서 검사
        whole = m.group(2).replace(",", "")
        dec = m.group(3) or ""
        mult = (m.group(4) or "").strip()
        dated = m.start() >= 2 and text[m.start() - 1] == "-" and text[m.start() - 2].isdigit()
        scale = 1.0 if dated else _MULT.get(mult, 1.0)  # '2025-11만 해도'의 11은 달이에요
        rest = _APPROX.sub("", text[m.end(): m.end() + 6])
        unit = "%" if mult in ("%", "퍼센트") else next((u for u in _UNITS if rest.startswith(u)), "")
        found.append([float(whole + dec) * scale, len(dec) - 1 if dec else 0, scale, m.group(0).strip(), unit, m.start(), m.end()])
    out: list[tuple[float, int, float, str, str]] = []
    i = 0
    while i < len(found):
        v, d, sc, raw, unit, _start, end = found[i]
        # 만·억 단위 뒤에 더 작은 수가 바로 이어지면 한 수로 합쳐요 (10만 493 → 100,493)
        while (sc >= 1e4 and i + 1 < len(found) and not text[end:found[i + 1][5]].strip()
               and found[i + 1][2] < sc and found[i + 1][0] < sc and found[i + 1][4] != "%" and not found[i + 1][1]):
            nxt = found[i + 1]
            v, raw, unit, end = v + nxt[0], f"{raw} {nxt[3]}", nxt[4], nxt[6]
            sc = nxt[2]
            d = 0
            i += 1
        out.append((v, d, 1.0 if sc < 1e3 else sc, raw, unit))
        i += 1
    return out


def _matches(value: float, decimals: int, scale: float, allowed: list[float], rel_tol: float) -> bool:
    v = abs(value)
    tol = 0.5 * (10 ** -decimals) * scale + 1e-9
    for a in allowed:
        a = abs(a)
        if abs(v - a) <= tol:
            return True
        if a >= 1000 and abs(v - a) / a <= rel_tol:  # 큰 수의 반올림만 상대 오차로 허용
            return True
        if a >= 100:  # '약 1,600명'처럼 유효숫자 2자리 이상으로 반올림한 값
            n = 1
            while a >= 10 ** (n + 1):
                if round(a, -n) == v:
                    return True
                n += 1
    return False


class Verifier:
    def __init__(self, refs: Refs, config: AppConfig, rule_ids: set[str], export_rules: dict[str, Any], data_mode: str):
        self.refs = refs
        self.config = config
        self.rule_ids = rule_ids
        self.export_rules = export_rules
        self.data_mode = data_mode

    # ------------------------------------------------------------------ 허용 숫자
    def allowed_numbers(self, b: Bundle) -> list[float]:
        allowed: set[float] = set(_STRUCTURAL)
        a, c3 = self.config.analysis, self.config.stage3

        def add_text(text: str | None) -> None:
            for v, *_ in _numbers(text or ""):
                allowed.add(v)

        for f in b.facts():
            if fmt.is_num(f.value):
                allowed.add(float(f.value))  # type: ignore[arg-type]
                if f.unit == "pct":
                    allowed.add(float(f.value) * 100)  # type: ignore[arg-type]
            add_text(f.text)
            add_text(f.label)
            add_text(f.period)
        for ev in b.evidence():
            add_text(ev.title)
            add_text(ev.note)
            add_text(ev.period)
            for row in ev.rows:
                for col, v in zip(ev.columns, row, strict=False):
                    if fmt.is_num(v):
                        allowed.add(float(v))
                        if ev.formats.get(col) in ("pct", "share"):
                            allowed.add(float(v) * 100)
                    elif isinstance(v, str):
                        add_text(v)
        for s in b.suggestions():
            add_text(s.text)
            for t in s.evidence_text:
                add_text(t)
        q = b.query
        add_text(q.question)
        allowed.update(float(x) for x in q.ages)
        for v in (q.last_n_months, q.year, q.target_month, q.elasticity):
            if v is not None:
                allowed.add(float(v))
        if q.supply_change is not None:
            allowed.add(q.supply_change * 100)
        allowed.update([a.tau * 100, a.min_base_pop, float(a.period_months), float(a.min_month_days),
                        float(a.peers_k), c3.beta_min_r2, float(c3.beta_min_months), *c3.elasticity_grid,
                        c3.supply_change_default * 100, c3.elasticity_default])
        return sorted(allowed)

    # ------------------------------------------------------------------ 문장 검사
    def check_numbers(self, text: str, b: Bundle) -> Check:
        allowed = self.allowed_numbers(b)
        bad = [raw for v, d, s, raw, _u in _numbers(text)
               if not _matches(v, d, s, allowed, self.config.verify.number_rel_tol)]
        return Check(name="numbers", passed=not bad,
                     detail="근거에 없는 숫자: " + ", ".join(dict.fromkeys(bad)) if bad else "해설 속 숫자가 모두 근거와 일치해요")

    @staticmethod
    def check_causal(text: str) -> Check:
        """인과 표현 가드. '원인인지는 알 수 없어요'처럼 인과 낱말 뒤에 부정·유보 표현이 오면 단정이 아니에요."""
        bad = []
        for sent in _SENT.split(text):
            for term in CAUSAL_TERMS:
                i = sent.find(term)
                if i < 0:
                    continue
                rest = sent[i + len(term):]
                if not any(h in rest for h in HEDGE_TERMS):
                    bad.append(f"'{term}' → {sent.strip()[:60]}")
                    break
        return Check(name="causal", passed=not bad,
                     detail="인과를 단정한 표현: " + " / ".join(bad) if bad else "인과를 단정한 표현이 없어요")

    def check_references(self, text: str, b: Bundle) -> Check:
        bad = []
        variants = {v for r in self.refs.routes.values() for v in r.variants}
        for rn in _ROUTE.findall(text):
            if rn not in self.refs.routes and rn not in variants:
                bad.append(f"참조표에 없는 노선 {rn}번")
        parts = [f.text + " " + f.label for f in b.facts()] + [s.text for s in b.suggestions()]
        parts += [b.query.place_name or "", b.query.question]
        if b.stage is None:  # 자유 질문은 조회 결과 표가 근거예요
            parts += [str(v) for ev in b.evidence() for row in ev.rows for v in row if isinstance(v, str)]
        corpus = " ".join(parts)
        for m in self.refs.find_places(text):
            if m.kind == "emd" and m.name not in corpus and m.matched not in "".join(corpus.split()):
                bad.append(f"근거에 없는 읍면동 {m.name}")
        known = {e.emd_nm for e in self.refs.emds.values()}
        for name in re.findall(r"[가-힣]{2,3}읍", text):
            if name not in known and not any(name.endswith(k) for k in known):
                bad.append(f"참조표에 없는 지명 {name}")
        return Check(name="references", passed=not bad,
                     detail="; ".join(dict.fromkeys(bad)) if bad else "노선·읍면동이 모두 참조표와 근거에 있어요")

    def _free_numbers(self, b: Bundle) -> set[float]:
        """지표의 '값'이 아닌 곳(지표 이름·기간·질문·설정)에 나오는 숫자. 짝 검사 대상에서 빼요."""
        free: set[float] = set(_STRUCTURAL)
        for f in b.facts():
            for text in (f.label, f.period):
                free.update(v for v, *_ in _numbers(text or ""))
        free.update(v for v, *_ in _numbers(b.query.question))
        a, c3 = self.config.analysis, self.config.stage3
        free.update([a.tau * 100, a.min_base_pop, float(a.period_months), *c3.elasticity_grid, c3.elasticity_default])
        return free

    def check_pairing(self, text: str, b: Bundle) -> Check:
        """숫자-지표 짝: 숫자가 근거에 있더라도, 그 숫자의 지표를 가리키는 낱말이 같은 문장에 있어야 해요.

        단위가 맞는 값만 봐요 (변화율·비중은 %, 인구는 명, 배율은 배 또는 소수).
        지표를 가리키는 낱말이 하나도 없는 문장은 앞 문장의 주어를 이어받은 것으로 보고 앞 문장까지 함께 봐요.
        예) '… 거주인구는 하루 평균 8,473명이었어요. 직전 기간은 8,482명이었고 거의 같았어요.'
        """
        anchored = []
        for f in b.facts():
            anchors = fact_anchors(f)
            if anchors and fmt.is_num(f.value) and f.unit in ("pct", "people", "ratio"):
                v = abs(float(f.value)) * (100 if f.unit == "pct" else 1)  # type: ignore[arg-type]
                anchored.append((f, anchors, v))
        free = self._free_numbers(b)
        metric_words = {alt for _f, a, _v in anchored for group in a for alt in group.split("|")}
        bad = []
        prev = ""
        for sent in _SENT.split(text):
            scope = sent if any(w in sent for w in metric_words) else f"{prev} {sent}"
            prev = sent
            for v, d, sc, raw, unit in _numbers(sent):
                tol = 0.5 * (10 ** -d) * sc + 1e-9
                if unit != "%" and any(abs(abs(v) - abs(x)) < 1e-9 for x in free):
                    continue
                cands = [(f, a) for f, a, fv in anchored
                         if abs(abs(v) - fv) <= tol
                         and ((f.unit == "pct" and unit == "%") or (f.unit == "people" and unit == "명")
                              or (f.unit == "ratio" and (unit == "배" or d >= 1)))]
                if not cands:
                    continue
                if not any(all(any(alt in scope for alt in group.split("|")) for group in a) for _f, a in cands):
                    bad.append(f"{raw}는 '{cands[0][0].label}'의 값이에요")
        return Check(name="pairing", passed=not bad,
                     detail="; ".join(dict.fromkeys(bad)) if bad else "숫자가 제 지표와 함께 쓰였어요")

    def check_fidelity(self, text: str, draft: str, b: Bundle) -> Check:
        """초안 충실도: 숫자를 쓴 문장에는 초안에서 그 숫자와 함께 쓰인 대상(내국인·중국인·테마·지명 등)만 나와야 해요.

        예) 초안 '중국인 … 주말 소비비는 0.89배예요' → '내국인보다 0.89배예요'는 대상이 달라 통과하지 못해요.
        '가장 빠른 코스'처럼 초안·지표 이름·규칙 제안에 없는 최상급 표현도 통과하지 못해요.
        Stage 2 에서 지역 단위 값을 읍면동 값처럼 쓴 문장('성산읍의 중국인 소비는 28.4% 늘었어요')도 통과하지 못해요.
        배율의 방향을 뒤바꾼 문장('주말에 비해 평일 소비가 0.89배')도 통과하지 못해요.
        """
        vocab = list(_ENTITY_WORDS) + [e.emd_nm for e in self.refs.emds.values()] + list(self.refs.nationalities)
        vocab += [h.hub_nm for h in self.refs.hubs.values()]
        asked = f"{b.query.question} {b.query.stage_question or ''}"
        always = {w for w in vocab if w in (b.query.place_name or "") or w in asked}
        # Stage 2 의 값은 읍면동 값이 아니라 시군구×도심/읍면 '지역' 값이에요. 지역을 밝히지 않은 문장에서
        # 읍면동 이름과 숫자를 함께 쓰면 그 동네의 값으로 읽혀요.
        emd_names = {e.emd_nm for e in self.refs.emds.values()} if b.stage == 2 else set()

        def ents(sent: str) -> set[str]:
            return {w for w in vocab if w in sent}

        def keys(sent: str) -> set[tuple[float, str]]:
            return {(round(abs(v), 6), u) for v, _d, _s, _raw, u in _numbers(sent) if u in ("%", "배", "명") or _d >= 1}

        draft_sents = [(keys(d), ents(d)) for d in _SENT.split(draft) if d.strip()]
        anchored = [(f, fact_anchors(f)) for f in b.facts() if fmt.is_num(f.value) and f.unit in ("pct", "people", "ratio")]
        bad = []
        for sent in _SENT.split(text):
            ks = keys(sent)
            src = [e for k, e in draft_sents if k & ks]
            if not src:
                continue
            # 이 문장의 숫자가 가리키는 지표의 낱말은 초안 문장에 없어도 괜찮아요 (예: 초안에 없던 '식음료 비중 16.2%')
            own: set[str] = set()
            for v, d, sc, _raw, unit in _numbers(sent):
                tol = 0.5 * (10 ** -d) * sc + 1e-9
                for f, anchors in anchored:
                    fv = abs(float(f.value)) * (100 if f.unit == "pct" else 1)  # type: ignore[arg-type]
                    unit_ok = (f.unit == "pct" and unit == "%") or (f.unit == "people" and unit == "명") or (
                        f.unit == "ratio" and (unit == "배" or d >= 1))
                    if unit_ok and abs(abs(v) - fv) <= tol and all(any(a in sent for a in g.split("|")) for g in anchors):
                        own |= {w for g in anchors for w in g.split("|")} | _DEFINITION_WORDS.get(f.key, set())
            extra = ents(sent) - set().union(*src) - (always if "지역" in sent else always - emd_names) - own
            if extra:
                bad.append(f"'{', '.join(sorted(extra))}' ↔ {sent.strip()[:50]}")
        problems = ["초안과 다른 대상에 숫자를 붙였어요: " + " / ".join(bad)] if bad else []
        ratios = [f for f in b.facts() if f.unit == "ratio" and fmt.is_num(f.value)]
        for sent in _SENT.split(text):
            nums = [(abs(v), d) for v, d, _s, _raw, u in _numbers(sent) if u == "배" or d >= 1]
            for prefix, rx, names in _REVERSED:
                hit = any(f.key.startswith(prefix) and any(abs(v - abs(float(f.value))) <= 0.5 * 10 ** -d + 1e-9 for v, d in nums)  # type: ignore[arg-type]
                          for f in ratios)
                if hit and rx.search(sent):
                    problems.append(f"배율의 방향이 뒤바뀌었어요 ({names}): {sent.strip()[:50]}")
        source = " ".join([draft, *(f.label for f in b.facts()), *(s.text for s in b.suggestions())])
        added = superlatives(text) - superlatives(source)
        if "먼저" in source or "우선" in source:  # '먼저 볼 만해요'를 '가장 먼저 볼 만해요'로 쓴 것은 같은 말이에요
            added -= {"가장 먼…", "가장 우…"}
        if added:
            problems.append("초안에 없는 최상급 표현: " + ", ".join(sorted(added)))
        return Check(name="fidelity", passed=not problems,
                     detail="; ".join(problems) if problems else "숫자가 초안과 같은 대상에 쓰였어요")

    @staticmethod
    def check_prediction(text: str) -> Check:
        bad = [sent.strip()[:50] for sent in _SENT.split(text)
               if _PREDICT.search(sent) and not any(w in sent for w in _PREDICT_OK)]
        return Check(name="prediction", passed=not bad,
                     detail="예측·추측 표현: " + " / ".join(bad) if bad else "예측·추측 표현이 없어요")

    def check_text(self, text: str, b: Bundle, draft: str = "") -> list[Check]:
        checks = [self.check_numbers(text, b), self.check_pairing(text, b), self.check_causal(text),
                  self.check_prediction(text), self.check_references(text, b)]
        if draft:
            checks.append(self.check_fidelity(text, draft, b))
        return checks

    # ------------------------------------------------------------------ 구조 검사
    def check_structure(self, text: str, b: Bundle) -> list[Check]:
        checks: list[Check] = []
        sugg = b.suggestions()
        if sugg:
            bad = [s.rule_id for s in sugg if s.rule_id not in self.rule_ids or not s.evidence_text]
            checks.append(Check(name="suggestions", passed=not bad,
                                detail=f"규칙·근거가 없는 제안: {bad}" if bad else f"제안 {len(sugg)}개 모두 규칙 ID와 근거 지표가 있어요"))
        fc = b.result("s3_forecast")
        if fc and fc.ok:
            has_badge = any(x.tone == "assumption" for x in b.badges())
            grid_ok = all(any(f"ε {e:.1f}" == c for c in fc.evidence[0].columns) for e in self.config.stage3.elasticity_grid)
            says = "가정" in text
            ok = has_badge and grid_ok and says
            checks.append(Check(name="assumption", passed=ok,
                                detail="가정 배지·민감도 표·'가정' 문구가 모두 있어요" if ok
                                else f"가정 표시 누락 (배지 {has_badge}, 민감도 표 {grid_ok}, 문구 {says})"))
        conflicts = [lim for lim in b.limits() if "겹치지 않" in lim or "함께 볼 수 없" in lim]
        checks.append(Check(name="periods", passed=True,
                            detail="; ".join(conflicts) if conflicts else "함께 쓴 지표의 기간이 겹쳐요"))
        check, _ = export_check(b.evidence(), self.export_rules, self.data_mode)
        checks.append(check)
        return checks

    def verify(self, text: str, b: Bundle, retries: int = 0, fallback: bool = False, draft: str = "") -> Verification:
        """최종 답의 검증 결과. draft 를 주면(LLM 해설) 초안 충실도도 함께 기록해요."""
        checks = self.check_text(text, b, draft) + self.check_structure(text, b)
        return Verification(passed=all(c.passed for c in checks), checks=checks, retries=retries, fallback=fallback)
