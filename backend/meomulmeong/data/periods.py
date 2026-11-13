"""비교 기간 결정.

기본은 최근 12개월(P1)과 직전 12개월(P0)이에요. 데이터가 모자라면 전년 동월 비교로 바꾸고 그 사실을 알려요.
기간은 모두 '월의 첫날' 날짜로 다뤄요 (양 끝 포함).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


def add_months(d: date, k: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + k, 12)
    return date(y, m + 1, 1)


def month_range(start: date, end: date) -> list[date]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def ym(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


@dataclass(frozen=True)
class PeriodPair:
    p1_start: date
    p1_end: date
    p0_start: date | None
    p0_end: date | None
    mode: Literal["rolling", "yoy", "single"]
    note: str | None = None

    @property
    def comparable(self) -> bool:
        return self.p0_start is not None

    @property
    def p1_label(self) -> str:
        return f"{ym(self.p1_start)}~{ym(self.p1_end)}"

    @property
    def p0_label(self) -> str:
        return f"{ym(self.p0_start)}~{ym(self.p0_end)}" if self.p0_start and self.p0_end else "-"

    @property
    def label(self) -> str:
        if not self.comparable:
            return f"{self.p1_label} (비교 기간 없음)"
        return f"{self.p1_label} vs {self.p0_label}"

    @property
    def n_months(self) -> int:
        return len(month_range(self.p1_start, self.p1_end))

    def sql_p1(self, col: str = "month") -> str:
        return f"{col} BETWEEN DATE '{self.p1_start}' AND DATE '{self.p1_end}'"

    def sql_p0(self, col: str = "month") -> str:
        if not self.comparable:
            return "FALSE"
        return f"{col} BETWEEN DATE '{self.p0_start}' AND DATE '{self.p0_end}'"

    def months_all(self) -> tuple[date, date]:
        """P0 시작부터 P1 끝까지 (추이 차트용)."""
        return (self.p0_start or self.p1_start, self.p1_end)


@dataclass(frozen=True)
class PeriodRequest:
    """사용자가 요청한 기간. 모두 None 이면 기본(최근 12개월 vs 직전 12개월)."""

    last_n_months: int | None = None  # "최근 6개월"
    year: int | None = None  # "2025년"
    month_of_year: int | None = None  # "12월" (Stage 3 대상 월)

    @property
    def is_default(self) -> bool:
        return self.last_n_months is None and self.year is None

    def describe(self) -> str:
        if self.year:
            return f"{self.year}년 vs {self.year - 1}년"
        if self.last_n_months:
            return f"최근 {self.last_n_months}개월 vs 전년 같은 기간"
        return "최근 12개월 vs 직전 12개월"


def resolve_period(
    valid_months: list[date],
    request: PeriodRequest | None = None,
    months: int = 12,
    min_months: int = 9,
) -> PeriodPair:
    """수록된 유효 월 목록에서 비교 기간을 정해요.

    - 유효 월이 P1·P0 각각 min_months 개 이상이면 연속 12개월 비교(rolling)
    - 모자라면 겹치는 달만으로 전년 동월 비교(yoy)
    - 1년 전 자료가 없으면 비교 없이 P1만(single)
    """
    if not valid_months:
        raise ValueError("유효한 달이 없어요")
    have = set(valid_months)
    first, last = min(have), max(have)
    request = request or PeriodRequest()

    if request.year:
        p1s, p1e = date(request.year, 1, 1), date(request.year, 12, 1)
        p1s, p1e = max(p1s, first), min(p1e, last)
        if p1s > p1e:
            raise ValueError(f"{request.year}년 자료가 없어요 (수록 기간 {ym(first)}~{ym(last)})")
        n = len(month_range(p1s, p1e))
    else:
        n = request.last_n_months or months
        p1e = last
        p1s = add_months(p1e, -(n - 1))
        if p1s < first:
            p1s = first
            n = len(month_range(p1s, p1e))

    p0s, p0e = add_months(p1s, -12), add_months(p1e, -12)
    p1_valid = [m for m in month_range(p1s, p1e) if m in have]
    p0_valid = [m for m in month_range(p0s, p0e) if m in have]

    need = min(min_months, n)
    if len(p1_valid) >= need and len(p0_valid) >= need:
        mode = "rolling" if (n == months and request.is_default) else "yoy"
        note = None if mode == "rolling" else "요청한 기간을 전년 같은 기간과 비교했어요."
        return PeriodPair(p1s, p1e, p0s, p0e, mode, note)

    # 전년 동월이 함께 있는 달만 골라 비교
    pairs = [m for m in p1_valid if add_months(m, -12) in have]
    if pairs:
        s, e = min(pairs), max(pairs)
        note = f"자료가 {ym(first)}~{ym(last)}뿐이라 전년 동월 비교({len(pairs)}개월)로 바꿨어요."
        return PeriodPair(s, e, add_months(s, -12), add_months(e, -12), "yoy", note)

    note = f"자료가 {ym(first)}~{ym(last)}뿐이라 이전 기간과 비교할 수 없어요."
    return PeriodPair(p1s, p1e, None, None, "single", note)


def overlap(a: tuple[date, date], b: tuple[date, date]) -> tuple[date, date] | None:
    """두 수록 기간의 공통 구간. 겹치지 않으면 None ('함께 볼 수 없음')."""
    s, e = max(a[0], b[0]), min(a[1], b[1])
    return (s, e) if s <= e else None
