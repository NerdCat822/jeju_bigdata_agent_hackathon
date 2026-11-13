"""시드 고정 합성(샘플) 데이터 생성기.

허브 Open API 응답과 같은 컬럼 이름·형식으로 만들어서, 실데이터와 똑같은 적재 경로(sources.hub 변환식)를
통과해요. 숫자는 실제 통계가 아니며, 화면에는 항상 '샘플 데이터' 배지가 붙어요.

읍면동마다 숨은 유형(A 정착 성장 · B 출퇴근 · C 방문 의존 · D 활력 저하 · 유지)을 심어 두어
세 단계가 끝까지 이어지는지 시험할 수 있어요.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .refs import Refs

SEED = 20261119
FIRST_MONTH = "2023-11-01"
LAST_DAY = "2026-10-31"  # 36개월

# 읍면동별 대략 인구 (명, 샘플용)
_POP = {
    "한림읍": 21000, "애월읍": 37000, "구좌읍": 15000, "조천읍": 26000, "한경면": 9000, "추자면": 1500,
    "우도면": 1700, "일도1동": 2500, "일도2동": 33000, "이도1동": 8000, "이도2동": 50000, "삼도1동": 13000,
    "삼도2동": 8000, "용담1동": 7000, "용담2동": 15000, "건입동": 9000, "화북동": 24000, "삼양동": 26000,
    "봉개동": 5000, "아라동": 38000, "오라동": 16000, "연동": 43000, "노형동": 55000, "외도동": 22000,
    "이호동": 4500, "도두동": 3300, "대정읍": 21000, "남원읍": 18000, "성산읍": 15000, "안덕면": 12000,
    "표선면": 12000, "송산동": 4000, "정방동": 2200, "중앙동": 3500, "천지동": 3500, "효돈동": 5000,
    "영천동": 5000, "동홍동": 24000, "서홍동": 11000, "대륜동": 15000, "대천동": 14000, "중문동": 12000,
    "예래동": 4000,
}
# 숨은 유형 (나머지는 '유지')
_LATENT = {
    "A": ["아라동", "노형동", "애월읍", "삼양동", "외도동", "대천동", "오라동"],
    "B": ["이도2동", "용담2동", "중문동", "대륜동", "건입동"],
    "C": ["성산읍", "구좌읍", "안덕면", "한림읍", "우도면", "조천읍"],
    "D": ["추자면", "한경면", "남원읍", "일도1동", "정방동", "송산동", "삼도2동"],
}
# (청년 거주, 청년 근무, 방문) 연 변화율 범위
_RATE = {
    "A": ((0.05, 0.09), (0.02, 0.06), (-0.01, 0.05)),
    "B": ((-0.01, 0.02), (0.05, 0.09), (-0.01, 0.02)),
    "C": ((-0.09, -0.05), (-0.03, 0.01), (0.04, 0.10)),
    "D": ((-0.10, -0.05), (-0.04, 0.00), (-0.10, -0.04)),
    "유지": ((-0.02, 0.02), (-0.02, 0.02), (-0.02, 0.02)),
}
_JOB_HEAVY = {"연동": 2.6, "노형동": 2.0, "이도2동": 2.4, "일도1동": 3.0, "건입동": 2.2, "용담2동": 2.8,
              "중문동": 2.4, "대륜동": 2.0, "중앙동": 2.5, "삼도1동": 1.8}
_TOUR_HEAVY = {"성산읍": 4.0, "구좌읍": 3.0, "애월읍": 2.6, "안덕면": 3.2, "중문동": 3.6, "우도면": 9.0,
               "한림읍": 2.4, "조천읍": 2.2, "용담2동": 3.0, "연동": 1.8, "표선면": 1.8, "정방동": 3.0,
               "천지동": 2.4, "대정읍": 1.6, "예래동": 2.6}
_YOUNG_TOWN = {"아라동", "노형동", "연동", "이도2동", "삼양동", "외도동", "오라동", "대천동"}

_AGE_LABELS = ["10세미만", "10대", "20대", "30대", "40대", "50대", "60대", "70세이상"]
_AGE_SHARE_URBAN = np.array([0.08, 0.10, 0.11, 0.12, 0.16, 0.17, 0.14, 0.12])
_AGE_SHARE_YOUNG = np.array([0.10, 0.11, 0.13, 0.15, 0.17, 0.15, 0.11, 0.08])
_AGE_SHARE_RURAL = np.array([0.06, 0.08, 0.08, 0.10, 0.14, 0.18, 0.18, 0.18])
_AGE_SHARE_TINY = np.array([0.04, 0.06, 0.04, 0.05, 0.13, 0.20, 0.23, 0.25])  # 추자면: 작은 표본 사례
_VISIT_AGE = np.array([0.04, 0.07, 0.19, 0.22, 0.20, 0.15, 0.09, 0.04])
_WORK_AGE = np.array([0.0, 0.01, 0.17, 0.24, 0.26, 0.21, 0.09, 0.02])
_SEASON = np.array([0.82, 0.85, 0.95, 1.05, 1.10, 1.02, 1.12, 1.20, 1.00, 1.10, 0.95, 0.84])  # 1~12월 방문 계절성

_DOW_KR = ["월", "화", "수", "목", "금", "토", "일"]  # Monday=0


def _month_index(days: pd.DatetimeIndex) -> np.ndarray:
    first = pd.Timestamp(FIRST_MONTH)
    return ((days.year - first.year) * 12 + (days.month - first.month)).to_numpy()


def _write(df: pd.DataFrame, out_dir: Path, name: str) -> int:
    d = out_dir / name
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.parquet"):
        old.unlink()
    df.to_parquet(d / "synthetic.parquet", index=False)
    return len(df)


def latent_types(refs: Refs) -> dict[str, str]:
    out = {e.emd_nm: "유지" for e in refs.emds.values()}
    for t, names in _LATENT.items():
        for n in names:
            out[n] = t
    return out


def generate(out_dir: Path, refs: Refs, seed: int = SEED) -> dict:
    """합성 데이터 전체를 out_dir 아래에 Parquet 으로 써요. 반환값은 요약(MANIFEST)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    days = pd.date_range(FIRST_MONTH, LAST_DAY, freq="D")
    months = pd.date_range(FIRST_MONTH, LAST_DAY, freq="MS")
    m_idx = _month_index(days)  # (D,)
    dow = days.day_of_week.to_numpy()  # Monday=0
    season = _SEASON[days.month.to_numpy() - 1]
    n_days, n_emd, n_age = len(days), len(refs.emds), len(_AGE_LABELS)
    emds = list(refs.emds.values())
    latent = latent_types(refs)

    # ---------------------------------------------------------------- 1) 내국인 유동인구
    rates = np.zeros((n_emd, 3))
    for i, e in enumerate(emds):
        lo_hi = _RATE[latent[e.emd_nm]]
        rates[i] = [rng.uniform(*lo_hi[0]), rng.uniform(*lo_hi[1]), rng.uniform(*lo_hi[2])]
    pop = np.array([_POP[e.emd_nm] for e in emds], dtype=float)
    age_share = np.stack([
        _AGE_SHARE_TINY if e.emd_nm == "추자면"
        else _AGE_SHARE_YOUNG if e.emd_nm in _YOUNG_TOWN
        else _AGE_SHARE_RURAL if e.area_type == "읍면"
        else _AGE_SHARE_URBAN
        for e in emds
    ])  # (E, A)
    job = np.array([_JOB_HEAVY.get(e.emd_nm, 1.0) for e in emds])
    tour = np.array([_TOUR_HEAVY.get(e.emd_nm, 1.0) for e in emds])
    youth = np.array([a in ("20대", "30대") for a in _AGE_LABELS])
    old = np.array([a in ("60대", "70세이상") for a in _AGE_LABELS])

    # 연령별 연 변화율: 청년은 유형별 값, 고령은 +1.5%, 나머지는 -0.5%
    def age_rates(youth_rate: np.ndarray) -> np.ndarray:
        r = np.where(old, 0.015, -0.005)[None, :].repeat(n_emd, axis=0)
        r[:, youth] = youth_rate[:, None]
        return r  # (E, A)

    r_resd, r_work = age_rates(rates[:, 0]), age_rates(rates[:, 1])
    g = lambda r: (1.0 + r[None, :, :]) ** ((m_idx[:, None, None] - 23.5) / 12.0)  # noqa: E731  (D, E, A)
    wk_resd = np.where(dow >= 5, 1.03, 1.0)[:, None, None]
    wk_work = np.where(dow >= 5, 0.45, 1.0)[:, None, None]
    wk_visit = np.select([dow == 5, dow == 6, dow == 4], [1.25, 1.15, 1.05], 1.0)[:, None, None]

    resd = pop[None, :, None] * 0.60 * age_share[None] * g(r_resd) * wk_resd
    work = pop[None, :, None] * 0.12 * job[None, :, None] * _WORK_AGE[None, None, :] * g(r_work) * wk_work
    visit = (pop[None, :, None] * 0.25 * tour[None, :, None] * _VISIT_AGE[None, None, :]
             * ((1.0 + rates[:, 2])[None, :, None] ** ((m_idx[:, None, None] - 23.5) / 12.0))
             * season[:, None, None] * wk_visit)

    frames = []
    sex_split = {"남": 0.5, "여": 0.5}
    for sex, share in sex_split.items():
        noise = lambda: rng.lognormal(0.0, 0.03, size=(n_days, n_emd, n_age))  # noqa: E731
        tilt = 1.04 if sex == "남" else 0.96  # 근무는 남성이 조금 많게
        frames.append(pd.DataFrame({
            "baseDate": np.repeat(days.strftime("%Y%m%d").to_numpy(), n_emd * n_age),
            "city": np.tile(np.repeat([e.city for e in emds], n_age), n_days),
            "emd": np.tile(np.repeat([e.emd_nm for e in emds], n_age), n_days),
            "gender": sex,
            "ageGroup": np.tile(_AGE_LABELS, n_days * n_emd),
            # 허브 원본은 하루 24개 시각 값의 합이라고 보고 ×24
            "resdPop": np.rint(resd * share * noise() * 24).astype(np.int64).ravel(),
            "workPop": np.rint(work * share * tilt * noise() * 24).astype(np.int64).ravel(),
            "visitPop": np.rint(visit * share * noise() * 24).astype(np.int64).ravel(),
        }))
    pop_df = pd.concat(frames, ignore_index=True)
    counts = {"pop_kor_emd": _write(pop_df, out_dir, "pop_kor_emd")}
    del pop_df, frames, resd, work, visit

    # ---------------------------------------------------------------- 2) 외국인 장기체류 유동인구
    nats = ["중국", "베트남", "인도네시아", "미국", "일본", "태국", "캐나다", "말레이시아"]
    nat_share = np.array([0.34, 0.22, 0.14, 0.07, 0.06, 0.07, 0.03, 0.07])
    labor = np.array([2.2 if e.emd_nm in ("한림읍", "성산읍", "구좌읍", "대정읍", "남원읍", "한경면") else 1.0 for e in emds])
    f_rate = np.array([rng.uniform(0.08, 0.20) if latent[e.emd_nm] in ("C", "D") else rng.uniform(0.0, 0.06) for e in emds])
    base = pop[None, :, None] * 0.03 * labor[None, :, None] * nat_share[None, None, :]
    gf = (1.0 + f_rate)[None, :, None] ** ((m_idx[:, None, None] - 23.5) / 12.0)
    shape = (n_days, n_emd, len(nats))
    f_resd = base * 0.62 * gf * rng.lognormal(0, 0.05, shape)
    f_work = base * 0.30 * gf * np.where(dow >= 5, 0.6, 1.0)[:, None, None] * rng.lognormal(0, 0.05, shape)
    f_visit = base * 0.18 * season[:, None, None] * rng.lognormal(0, 0.08, shape)
    for_df = pd.DataFrame({
        "baseDate": np.repeat(days.strftime("%Y%m%d").to_numpy(), n_emd * len(nats)),
        "nationality": np.tile(nats, n_days * n_emd),
        "city": np.tile(np.repeat([e.city for e in emds], len(nats)), n_days),
        "emd": np.tile(np.repeat([e.emd_nm for e in emds], len(nats)), n_days),
        "resdPop": np.rint(f_resd * 24).astype(np.int64).ravel(),
        "workPop": np.rint(f_work * 24).astype(np.int64).ravel(),
        "visitPop": np.rint(f_visit * 24).astype(np.int64).ravel(),
    })
    counts["pop_for_long_emd"] = _write(for_df, out_dir, "pop_for_long_emd")
    del for_df

    # ---------------------------------------------------------------- 월 단위 공통
    ym = months.strftime("%Y%m").to_numpy()
    mm = np.arange(len(months))
    m_season = _SEASON[months.month.to_numpy() - 1]
    mg = lambda r: (1.0 + r) ** ((mm - 23.5) / 12.0)  # noqa: E731

    # ---------------------------------------------------------------- 3) 방문목적별 입도객
    purposes = {"개별여행": (900000, -0.05), "패키지": (40000, 0.08), "부분패키지": (25000, 0.04),
                "레저스포츠": (45000, 0.02), "휴양및관람": (60000, -0.02), "회의및업무": (55000, 0.03),
                "교육여행": (20000, 0.01), "친지방문": (70000, -0.01), "기타방문": (15000, 0.0)}
    rows = []
    indiv = None
    for p, (base_n, r) in purposes.items():
        v = base_n * mg(r) * m_season * rng.lognormal(0, 0.03, len(months))
        v = np.rint(v).astype(np.int64)
        if p == "개별여행":
            indiv = v.astype(float)
        rows.append(pd.DataFrame({"dtYearMonth": ym, "visitPurpose": p, "visitorCnt": v}))
    counts["arrivals_purpose"] = _write(pd.concat(rows, ignore_index=True), out_dir, "arrivals_purpose")

    # ---------------------------------------------------------------- 4) 외국인관광객현황 (국적 12종)
    nat12 = {"일본": (6000, 0.12), "중국": (110000, 0.22), "홍콩": (5000, 0.10), "대만": (16000, 0.38),
             "싱가폴": (4000, 0.25), "말레이시아": (3000, 0.08), "인도네시아": (2000, 0.15), "베트남": (2000, 0.18),
             "태국": (2500, 0.05), "아시아-기타": (4000, 0.06), "미국": (5000, 0.15), "서구-기타": (6000, 0.09)}
    rows = []
    for n, (base_n, r) in nat12.items():
        v = base_n * mg(r) * (0.6 + 0.4 * m_season) * rng.lognormal(0, 0.04, len(months))
        rows.append(pd.DataFrame({"dtYearMonth": ym, "nationality": n, "visitorCnt": np.rint(v).astype(np.int64)}))
    counts["foreign_visitors"] = _write(pd.concat(rows, ignore_index=True), out_dir, "foreign_visitors")

    # ---------------------------------------------------------------- 5) 중국인 관광객 지역·업종별 카드
    markets = {"쇼핑": 0.45, "소매": 0.10, "식음료": 0.15, "숙박": 0.15, "교통": 0.03, "유흥": 0.02,
               "문화/레져": 0.06, "기타": 0.04}
    area_base = {("제주시", "도심"): 5.0e9, ("제주시", "읍면"): 6.0e8, ("서귀포시", "도심"): 1.5e9,
                 ("서귀포시", "읍면"): 5.0e8}
    area_rate = {
        ("서귀포시", "읍면"): {"식음료": 0.28, "숙박": 0.18, "쇼핑": 0.06, "소매": 0.12, "문화/레져": 0.15},
        ("제주시", "읍면"): {"식음료": 0.22, "숙박": 0.12, "쇼핑": 0.04, "소매": 0.09, "문화/레져": 0.10},
        ("서귀포시", "도심"): {"식음료": 0.11, "숙박": 0.07, "쇼핑": 0.12, "소매": 0.05},
        ("제주시", "도심"): {"식음료": 0.08, "숙박": 0.03, "쇼핑": 0.14, "소매": 0.04},
    }
    per_user = {"쇼핑": 400000, "소매": 60000, "식음료": 70000, "숙박": 260000, "교통": 45000, "유흥": 90000,
                "문화/레져": 55000, "기타": 50000}
    rows = []
    for (city, area), total in area_base.items():
        acc = np.zeros((3, len(months)))
        for mk, share in markets.items():
            r = area_rate[(city, area)].get(mk, 0.02)
            amt = total * share * mg(r) * (0.7 + 0.3 * m_season) * rng.lognormal(0, 0.04, len(months))
            users = amt / per_user[mk]
            cnt = users * 1.6
            vals = np.rint(np.stack([users, cnt, amt])).astype(np.int64)
            acc += vals
            rows.append(pd.DataFrame({"sido": "제주도", "sigungu": city, "cityGubun": area, "marketType": mk,
                                      "dtYearMonth": ym, "userCount": vals[0], "useCount": vals[1], "useCost": vals[2]}))
        rows.append(pd.DataFrame({"sido": "제주도", "sigungu": city, "cityGubun": area, "marketType": "전체",
                                  "dtYearMonth": ym, "userCount": acc[0].astype(np.int64),
                                  "useCount": acc[1].astype(np.int64), "useCost": acc[2].astype(np.int64)}))
    counts["card_cn_area"] = _write(pd.concat(rows, ignore_index=True), out_dir, "card_cn_area")

    # ---------------------------------------------------------------- 6) 관광지 및 상업지구 요일별 카드
    zone_base = {"상업지": (9.0e9, 2.2e9), "내국인 주요 관광지": (6.0e9, 4.0e8), "중국인 주요 관광지": (1.5e9, 2.6e9),
                 "제주시 구도심": (3.0e9, 5.0e8), "서귀포시 구도심": (1.8e9, 3.0e8)}  # (내국인, 중국인) 월 이용금액
    # 요일 가중치 (월~일): 내국인은 주말 쏠림, 중국인은 평일에도 고름
    dow_w_kr = {"상업지": [1, 1, 1, 1, 1.1, 1.15, 1.05], "내국인 주요 관광지": [1, 1, 1, 1, 1.1, 1.55, 1.40],
                "중국인 주요 관광지": [1, 1, 1, 1, 1.05, 1.25, 1.2], "제주시 구도심": [1, 1, 1, 1, 1.1, 1.2, 1.1],
                "서귀포시 구도심": [1, 1, 1, 1, 1.1, 1.3, 1.2]}
    dow_w_cn = [1.0, 1.02, 1.03, 1.02, 1.0, 0.92, 0.88]
    day_month = days.to_period("M").to_timestamp().to_numpy()
    n_dow = np.zeros((len(months), 7))
    for k, mth in enumerate(months.to_numpy()):
        sel = day_month == mth
        n_dow[k] = np.bincount(dow[sel], minlength=7)
    rows = []
    for zone, (kr, cn) in zone_base.items():
        for utype, base_amt, w, r in (("내국인관광객", kr, dow_w_kr[zone], -0.02), ("중국인관광객", cn, dow_w_cn, 0.15)):
            w = np.array(w)
            daily = base_amt * mg(r) * (0.75 + 0.25 * m_season) / 30.4  # 하루 기준 금액 (월별)
            for d in range(7):
                amt = daily * w[d] * n_dow[:, d] * rng.lognormal(0, 0.03, len(months))
                users = amt / (95000 if utype.startswith("내") else 210000)
                rows.append(pd.DataFrame({"districtType": zone, "userType": utype, "dtYearMonth": ym,
                                          "dtWeek": _DOW_KR[d], "userCount": np.rint(users).astype(np.int64),
                                          "useCount": np.rint(users * 1.5).astype(np.int64),
                                          "useCost": np.rint(amt).astype(np.int64)}))
    counts["card_zone_dow"] = _write(pd.concat(rows, ignore_index=True), out_dir, "card_zone_dow")

    # ---------------------------------------------------------------- 7) 단체/개별 관광객 소비
    # (개별 인당, 단체 인당) 원
    per_person = {
        "중국인관광객": {"식음료": (85000, 60000), "숙박": (310000, 250000), "쇼핑": (700000, 900000),
                     "소매": (90000, 80000), "교통": (60000, 30000), "유흥": (120000, 100000),
                     "문화/레져": (70000, 65000), "기타": (50000, 52000)},
        "내국인관광객": {"식음료": (120000, 80000), "숙박": (220000, 150000), "쇼핑": (180000, 160000),
                     "소매": (70000, 60000), "교통": (140000, 60000), "유흥": (110000, 100000),
                     "문화/레져": (60000, 55000), "기타": (45000, 44000)},
    }
    rows = []
    for utype, table in per_person.items():
        for mk, (ind, grp) in table.items():
            for ttype, base_v in (("개별", ind), ("단체", grp)):
                cost = base_v * mg(0.02) * rng.lognormal(0, 0.03, len(months))
                rows.append(pd.DataFrame({"marketType": mk, "userType": utype, "individualGroup": ttype,
                                          "dtYearMonth": ym, "eventSum": np.rint(cost / 1.6).astype(np.int64),
                                          "costOfPerson": np.rint(cost).astype(np.int64)}))
    counts["spend_tour_type"] = _write(pd.concat(rows, ignore_index=True), out_dir, "spend_tour_type")

    # ---------------------------------------------------------------- 8) 일일 노선별 버스 이용자
    route_base = {"101": (2400, 0.60), "102": (2200, 0.50), "111": (1500, 0.90), "112": (1200, 0.80),
                  "121": (800, 0.50), "131": (700, 0.20), "151": (1300, 0.60), "181": (3000, 0.25),
                  "201": (9000, 0.35), "202": (8500, 0.30), "281": (7500, 0.05), "282": (4200, 0.10),
                  "600": (1800, 1.10)}  # (하루 이용자, 관광 민감도 β)
    rel = indiv / indiv.mean()
    month_of_day = m_idx
    move = {"승차": 0.85, "환승": 0.15}
    price = {"일반": 0.78, "청소년": 0.12, "어린이": 0.03, "기타": 0.07}
    pay = {"카드": 0.96, "현금": 0.04}
    combos = [(a, b, c, wa * wb * wc) for a, wa in move.items() for b, wb in price.items() for c, wc in pay.items()]
    rows = []
    for route_no, (base_n, beta) in route_base.items():
        route = refs.routes[route_no]
        monthly = (rel ** beta) * mg(0.01) * rng.lognormal(0, 0.04, len(months))
        daily = base_n * monthly[month_of_day] * np.where(dow >= 5, 0.80 + 0.5 * beta, 1.0)
        for k, variant in enumerate(route.variants or (route_no,)):
            ends = (route.origin, route.destination) if k == 0 else (route.destination, route.origin)
            sub = f"{variant}({ends[0]}~{ends[1]})"
            half = daily / max(len(route.variants), 1)
            for mv, pr, py, w in combos:
                n = rng.poisson(np.maximum(half * w, 0.01))
                rows.append(pd.DataFrame({"baseDate": days.strftime("%Y%m%d").to_numpy(), "routeName": variant,
                                          "routeSubName": sub, "moveType": mv, "priceType": pr, "payType": py,
                                          "userCount": n.astype(np.int64)}))
    counts["bus_route"] = _write(pd.concat(rows, ignore_index=True), out_dir, "bus_route")

    manifest = {
        "kind": "synthetic",
        "note": "시드 고정 합성 데이터예요. 실제 통계가 아니에요.",
        "seed": seed,
        "first_day": str(days[0].date()),
        "last_day": str(days[-1].date()),
        "generated_on": str(date.today()),
        "rows": counts,
        "latent_types": latent,
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
