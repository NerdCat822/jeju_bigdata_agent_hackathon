"""여러 단계가 함께 쓰는 계산: 요일별 카드(주말 소비비·요일 피크)."""

from __future__ import annotations

from dataclasses import dataclass

from ..data.periods import PeriodPair
from ..schemas import EvidenceTable
from .base import ToolContext, sql_in

DOWS = ["월", "화", "수", "목", "금", "토", "일"]
CARD_ZONE = "card_zone_dow_monthly"


@dataclass
class DowProfile:
    zone: str
    user_type: str
    weekend_ratio: float | None  # 토·일 하루 평균 ÷ 평일 하루 평균
    peak_dow: str | None
    per_day: dict[str, float]


def dow_profiles(ctx: ToolContext, zones: list[str], period: PeriodPair) -> tuple[list[DowProfile], EvidenceTable | None]:
    """지구별·관광객구분별 요일 프로필 (P1 기간). 요일 수로 나눠 '하루 평균'으로 비교해요."""
    if not zones or not ctx.wh.has(CARD_ZONE):
        return [], None
    sql = f"""
SELECT c.zone, c.user_type, c.dow,
       SUM(c.use_amt) * 1.0 / SUM(k.n_days) AS amt_per_day
FROM card_zone_dow_monthly AS c
JOIN ref_month_dow AS k ON k.month = c.month AND k.dow = c.dow
WHERE c.zone IN ({sql_in(zones)}) AND {period.sql_p1('c.month')}
GROUP BY c.zone, c.user_type, c.dow
ORDER BY c.zone, c.user_type"""
    res = ctx.wh.query(sql)
    grouped: dict[tuple[str, str], dict[str, float]] = {}
    for zone, user_type, dow, amt in res.rows:
        grouped.setdefault((zone, user_type), {})[dow] = float(amt)
    profiles: list[DowProfile] = []
    rows = []
    for (zone, user_type), per_day in grouped.items():
        we = [per_day[d] for d in ("토", "일") if d in per_day]
        wd = [per_day[d] for d in ("월", "화", "수", "목", "금") if d in per_day]
        ratio = (sum(we) / len(we)) / (sum(wd) / len(wd)) if we and wd and sum(wd) > 0 else None
        peak = max(per_day, key=per_day.get) if per_day else None
        profiles.append(DowProfile(zone, user_type, ratio, peak, per_day))
        rows.append([zone, user_type, *[round(per_day.get(d, 0.0)) for d in DOWS],
                     round(ratio, 3) if ratio is not None else None, peak])
    ev = EvidenceTable(
        id="dow", title="요일별 하루 평균 카드 이용금액과 주말 소비비",
        columns=["지구", "관광객구분", *DOWS, "주말 소비비", "피크 요일"], rows=rows,
        formats={**{d: "won" for d in DOWS}, "주말 소비비": "num2"},
        sql=res.sql, tables=[CARD_ZONE], period=period.p1_label,
        note="주말 소비비 = 토·일 하루 평균 이용금액 ÷ 평일 하루 평균 이용금액",
    )
    return profiles, ev
