"""숫자·문장 표기 도우미 (화면과 제안서, 템플릿 해설이 같은 표기를 쓰게 해요)."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any


def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def pct(v: float | None, digits: int = 1, signed: bool = True) -> str:
    """0.068 → '+6.8%'. 값이 없으면 '-'."""
    if not is_num(v):
        return "-"
    x = round(v * 100, digits)
    if x == 0:
        x = 0.0
    sign = "+" if (signed and x > 0) else ""
    return f"{sign}{x:.{digits}f}%"


def people_approx(v: float | None) -> str:
    """결론에 쓸 대략의 인원수. 만 명이 넘으면 '약 21.8만 명', 그보다 작으면 '1,234명' 그대로예요."""
    if not is_num(v):
        return "-"
    if abs(v) < 10_000:
        return people(v)
    return f"약 {v / 10_000:,.1f}만 명"


def pct_abs(v: float | None, digits: int = 1) -> str:
    """0.068 또는 -0.068 → '6.8%' (늘었어요/줄었어요 문장용)."""
    if not is_num(v):
        return "-"
    return f"{abs(round(v * 100, digits)):.{digits}f}%"


def num(v: float | None, digits: int = 0) -> str:
    if not is_num(v):
        return "-"
    return f"{v:,.{digits}f}"


def people(v: float | None) -> str:
    return "-" if not is_num(v) else f"{round(v):,}명"


def won(v: float | None) -> str:
    """금액: 1억 이상은 '12.3억 원', 1만 이상은 '1,234만 원', 그 밖은 '9,800원'."""
    if not is_num(v):
        return "-"
    a = abs(v)
    if a >= 1e8:
        return f"{v / 1e8:,.1f}억 원"
    if a >= 1e4:
        return f"{v / 1e4:,.0f}만 원"
    return f"{v:,.0f}원"


def ratio(v: float | None, digits: int = 2) -> str:
    return "-" if not is_num(v) else f"{v:.{digits}f}배"


def month_label(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def change_word(v: float | None, tau: float = 0.0, up: str = "늘었어요", down: str = "줄었어요", flat: str = "비슷했어요") -> str:
    """변화율을 '늘었어요/줄었어요/비슷했어요'로."""
    if not is_num(v):
        return "비교할 수 없어요"
    if v > tau:
        return up
    if v < -tau:
        return down
    return flat


def has_batchim(word: str) -> bool:
    """마지막 글자에 받침이 있는지 (조사 선택용). 숫자·영문은 받침 없는 것으로 봐요."""
    for ch in reversed(word.strip()):
        if "가" <= ch <= "힣":
            return (ord(ch) - ord("가")) % 28 != 0
        if ch.isdigit():
            return ch in "013678"
        if ch.isalpha():
            return False
    return False


def josa(word: str, pair: str) -> str:
    """조사 붙이기: josa('성산읍', '은는') → '성산읍은'. pair 는 '은는', '이가', '을를', '과와', '으로로'."""
    pairs = {"은는": ("은", "는"), "이가": ("이", "가"), "을를": ("을", "를"), "과와": ("과", "와"),
             "으로로": ("으로", "로"), "이에요예요": ("이에요", "예요")}
    with_b, without_b = pairs[pair]
    b = has_batchim(word)
    if pair == "으로로" and b:
        # ㄹ 받침은 '로'
        last = word.strip()[-1]
        if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 == 8:
            b = False
    return word + (with_b if b else without_b)


def join_names(names: list[str]) -> str:
    """['구좌읍', '안덕면', '한림읍'] → '구좌읍, 안덕면, 한림읍'."""
    return ", ".join(names)


def ages_label(ages: list[int]) -> str:
    """[20, 30] → '20·30대', [30] → '30대', [0] → '10세 미만'."""
    if not ages:
        return "전체 연령"
    parts = ["10세 미만" if a == 0 else ("70세 이상" if a >= 70 else f"{a}") for a in sorted(ages)]
    if all(p.isdigit() for p in parts):
        return "·".join(parts) + "대"
    return "·".join(p + "대" if p.isdigit() else p for p in parts)


def model_name(model_id: str) -> str:
    """모델 ID 를 화면에 보여 줄 이름으로 바꿔요. 'claude-opus-5-5' → 'Claude Opus 5.5', 'claude-3-5-sonnet-20241022' → 'Claude 3.5 Sonnet'."""
    parts = [p for p in model_id.strip().split("-") if p]
    if len(parts) > 1 and re.fullmatch(r"\d{8}", parts[-1]):  # 끝의 날짜 꼬리표는 빼요
        parts.pop()
    words: list[str] = []
    for p in parts:
        if p.isdigit() and words and re.fullmatch(r"\d+(\.\d+)*", words[-1]):
            words[-1] += f".{p}"  # 숫자가 이어지면 버전으로 묶어요 (5, 5 → 5.5)
        else:
            words.append(p if p.isdigit() else p.capitalize())
    return " ".join(words) or model_id
