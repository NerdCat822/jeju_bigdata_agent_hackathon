"""기대값 계산기: 에이전트의 SQL과 다른 경로(pandas, 원본 Parquet)로 같은 지표를 다시 계산해요.

에이전트가 쓰는 PostgreSQL 테이블·SQL 템플릿을 전혀 거치지 않으므로, 두 값이 같으면 계산식이 맞다는 뜻이에요.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date
from functools import cached_property
from pathlib import Path

import pandas as pd

AGE_BAND = {"10세미만": 0, "10대": 10, "20대": 20, "30대": 30, "40대": 40, "50대": 50, "60대": 60, "70세이상": 70}
DOW = ["월", "화", "수", "목", "금", "토", "일"]


def _ym_add(ym: str, k: int) -> str:
    y, m = divmod(int(ym[:4]) * 12 + int(ym[4:]) - 1 + k, 12)
    return f"{y}{m + 1:02d}"


def _label(a: str, b: str) -> str:
    return f"{a[:4]}-{a[4:]}~{b[:4]}-{b[4:]}"


class Expected:
    def __init__(self, raw_dir: Path, ref_dir: Path, tau: float = 0.03, min_base_pop: float = 100.0,
                 pop_scale: float = 1 / 24, min_days: int = 20):
        self.raw, self.ref = Path(raw_dir), Path(ref_dir)
        self.tau, self.min_base, self.scale, self.min_days = tau, min_base_pop, pop_scale, min_days

    def _read(self, name: str) -> pd.DataFrame:
        return pd.concat([pd.read_parquet(f) for f in sorted((self.raw / name).glob("*.parquet"))], ignore_index=True)

    def _ref(self, name: str) -> list[dict[str, str]]:
        with (self.ref / name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    # ---------------------------------------------------------------- Stage 1
    @cached_property
    def pop_monthly(self) -> pd.DataFrame:
        df = self._read("pop_kor_emd")
        df["month"] = df["baseDate"].astype(str).str[:6]
        df["band"] = df["ageGroup"].map(AGE_BAND)
        days = df.groupby(["month", "emd"])["baseDate"].nunique().rename("days").reset_index()
        agg = df.groupby(["month", "city", "emd", "band"], as_index=False)[["resdPop", "workPop", "visitPop"]].sum()
        agg = agg.merge(days, on=["month", "emd"])
        return agg[agg["days"] >= self.min_days]

    def periods(self, last_n: int | None = None) -> tuple[list[str], list[str]]:
        months = sorted(self.pop_monthly["month"].unique())
        n = last_n or 12
        p1 = months[-n:]
        return p1, [_ym_add(m, -12) for m in p1]

    def _daily(self, df: pd.DataFrame, months: list[str], col: str) -> float:
        d = df[df["month"].isin(months)]
        days = d.drop_duplicates(["month", "emd"])["days"].sum()
        return float(d[col].sum()) / float(days) * self.scale

    def classify(self, resd: float, work: float, visit: float) -> str:
        t = self.tau
        if resd >= t and work >= 0:
            return "A"
        if work >= t:
            return "B"
        if resd <= -t and visit >= 0:
            return "C"
        if resd <= -t and visit < 0:
            return "D"
        return "유지"

    def s1(self, emds: list[str], ages: list[int] | None = None, last_n: int | None = None) -> dict:
        """읍면동 하나(또는 여러 곳을 합친 지구)의 청년 거주·근무·방문 변화와 유형."""
        ages = ages or [20, 30]
        p1, p0 = self.periods(last_n)
        m = self.pop_monthly[self.pop_monthly["emd"].isin(emds)]
        y = m[m["band"].isin(ages)]
        if len(emds) == 1:
            r1, r0 = self._daily(y, p1, "resdPop"), self._daily(y, p0, "resdPop")
            w1, w0 = self._daily(y, p1, "workPop"), self._daily(y, p0, "workPop")
            v1, v0 = self._daily(m, p1, "visitPop"), self._daily(m, p0, "visitPop")
        else:  # 지구: 읍면동별 하루 평균을 더한 뒤 달 평균
            def zone(df: pd.DataFrame, months: list[str], col: str) -> float:
                d = df[df["month"].isin(months)].copy()
                d["per_day"] = d[col] / d["days"]
                return float(d.groupby("month")["per_day"].sum().mean()) * self.scale
            r1, r0 = zone(y, p1, "resdPop"), zone(y, p0, "resdPop")
            w1, w0 = zone(y, p1, "workPop"), zone(y, p0, "workPop")
            v1, v0 = zone(m, p1, "visitPop"), zone(m, p0, "visitPop")
        out = {"youth_resd_p1": r1, "youth_resd_chg": r1 / r0 - 1, "youth_work_chg": w1 / w0 - 1, "visit_chg": v1 / v0 - 1,
               "small": r0 < self.min_base, "period": f"{_label(p1[0], p1[-1])} vs {_label(p0[0], p0[-1])}"}
        out["type"] = self.classify(out["youth_resd_chg"], out["youth_work_chg"], out["visit_chg"])
        return out

    def s1_ranking(self, ages: list[int] | None = None, area: str | None = None) -> list[tuple[str, float]]:
        """청년 거주 변화율 순위 (작은 표본 제외). area: '읍면' / '도심' / None."""
        rows = []
        for r in self._ref("ref_emd.csv"):
            if area and r["area_type"] != area:
                continue
            s = self.s1([r["emd_nm"]], ages)
            if not s["small"]:
                rows.append((r["emd_nm"], s["youth_resd_chg"], s["youth_work_chg"], r["emd_cd"]))
        rows.sort(key=lambda t: (-t[1], -t[2], t[3]))
        return [(n, c) for n, c, _w, _cd in rows]

    # ---------------------------------------------------------------- Stage 2
    def cn_growth(self, city: str, area_type: str, theme: str) -> float:
        theme_map = {r["raw"]: r["theme"] for r in self._ref("ref_theme.csv")}
        df = self._read("card_cn_area")
        df = df[(df["sigungu"] == city) & (df["cityGubun"] == area_type) & (df["marketType"] != "전체")].copy()
        df["theme"] = df["marketType"].map(theme_map)
        df["month"] = df["dtYearMonth"].astype(str)
        months = sorted(df["month"].unique())
        p1 = months[-12:]
        p0 = [_ym_add(m, -12) for m in p1]
        d = df[df["theme"] == theme]
        return float(d[d["month"].isin(p1)]["useCost"].sum()) / float(d[d["month"].isin(p0)]["useCost"].sum()) - 1

    def weekend_ratio(self, zones: list[str], user_type: str) -> float:
        df = self._read("card_zone_dow")
        df = df[df["districtType"].isin(zones) & df["userType"].str.contains(user_type)].copy()
        df["month"] = df["dtYearMonth"].astype(str)
        p1 = sorted(df["month"].unique())[-12:]
        df = df[df["month"].isin(p1)]
        ratios = []
        for _zone, z in df.groupby("districtType"):
            per_day = {}
            for dow, g in z.groupby("dtWeek"):
                n = sum(sum(1 for wk in calendar.monthcalendar(int(m[:4]), int(m[4:])) if wk[DOW.index(dow)])
                        for m in g["month"])
                per_day[dow] = float(g["useCost"].sum()) / n
            we = (per_day["토"] + per_day["일"]) / 2
            wd = sum(per_day[d] for d in DOW[:5]) / 5
            ratios.append(we / wd)
        return sum(ratios) / len(ratios)

    # ---------------------------------------------------------------- Stage 3
    def scenario(self, target_month: int | None, supply_change: float, elasticity: float = 1.0,
                 purpose: str | None = None) -> dict:
        df = self._read("arrivals_purpose")
        df["month"] = df["dtYearMonth"].astype(str)
        last = max(df["month"])
        target = _ym_add(last, 1)
        while target_month and int(target[4:]) != target_month:
            target = _ym_add(target, 1)
        base = _ym_add(target, -12)
        while base > last:
            base = _ym_add(base, -12)
        d = df[df["month"] == base]
        if purpose:
            d = d[d["visitPurpose"] == purpose]
        baseline = float(d["visitorCnt"].sum())
        return {"target": f"{target[:4]}-{target[4:]}", "baseline_month": f"{base[:4]}-{base[4:]}", "baseline": baseline,
                "scenario": baseline * max(0.0, 1 + elasticity * supply_change)}


def today_tag() -> str:
    return date.today().isoformat()
