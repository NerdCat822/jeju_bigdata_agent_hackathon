"""제주데이터허브 Open API 수집기.

    https://open.jejudatahub.net/api/proxy/{dataKey}/{projectKey}?startDate=…&endDate=…&number=1&limit=100

- 실행 전에 허브에서 데이터마다 '프로젝트 담기'를 하고, 프로젝트 키를 MEOMUL_HUB_PROJECT_KEY 에 넣어야 해요.
- 받은 쪽(페이지)마다 data/hub/_raw 에 저장해 두고, 다음 실행 때는 없는 쪽만 이어서 받아요 (API별 하루 쿼터 대비).
- 한 구간(월)이 끝나면 data/hub/<폴더>/<구간>.parquet 로 묶어요. 분석 중에는 API를 부르지 않아요.

실제 호출로 확인한 것 (2026-11-16)
- 응답은 {"totCnt": N, "hasMore": true, "data": [...]} 이고, 쪽 매개변수는 number(1부터)와 limit 이에요. limit 은 100이 상한이에요.
- 허브 프록시가 요청 두 번에 한 번꼴로 502(가끔 403)를 돌려줘요. 그래서 실패한 요청은 여러 번 다시 보내요.
- 쿼터는 실패한 요청까지 세요. 쿼터가 차면 403 과 함께 "Today's quota is full" 을 돌려줘요.
- 일 단위 자료는 하루 수백~수천 행이라 쿼터(API별 하루 1,000건) 안에서 다 받기 어려워요.
  --days 로 달마다 받을 날짜를 골라 받고, 분석은 받은 날의 하루 평균으로 해요.
"""

from __future__ import annotations

import calendar
import json
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from ..settings import Settings
from .catalog import Catalog, SourceSpec, TableSpec
from .periods import add_months

PAGE_PARAMS = ("number", "limit")  # 쪽 번호(1부터), 쪽 크기
DEFAULT_LIMIT = 100
MONTHLY_START = "201601"


class HubError(RuntimeError):
    pass


class QuotaReached(HubError):
    """이번 실행의 호출 상한에 닿았어요. 다음에 이어서 받으면 돼요."""


class AuthFailed(HubError):
    """프로젝트 키나 데이터 신청에 문제가 있어요. 다른 구간도 같을 테니 그 테이블은 멈춰요."""


@dataclass
class FetchStats:
    table: str
    calls: int = 0  # 성공한 호출
    failed: int = 0  # 허브가 502·403 등으로 실패해 다시 보낸 요청 (이것도 쿼터에 들어가요)
    rows: int = 0
    windows_done: int = 0
    windows_skipped: int = 0
    stopped: str = ""
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 허브가 계속 서버 오류를 내서 건너뛴 구간


def _rows(payload: Any) -> tuple[list[dict[str, Any]], int | None, bool | None]:
    """응답에서 (행 목록, 전체 건수, 다음 쪽 여부)를 꺼내요."""
    if isinstance(payload, list):
        return payload, None, None
    if not isinstance(payload, dict):
        raise HubError(f"예상하지 못한 응답 형식이에요: {str(payload)[:200]}")
    for key in ("data", "items", "list", "result"):
        if isinstance(payload.get(key), list):
            total = payload.get("totCnt", payload.get("totalCount", payload.get("recordsTotal")))
            more = payload.get("hasMore")
            return payload[key], int(total) if isinstance(total, (int, float, str)) and str(total).isdigit() else None, more
    msg = payload.get("message") or payload.get("msg") or payload.get("error") or str(payload)[:200]
    raise HubError(f"허브 API 오류: {msg}")


def parse_days(text: str | None) -> list[int] | None:
    """'1,9,17,25' 나 '1-7' 을 날짜 목록으로 바꿔요. 비우면 None (그 달 전체)."""
    if not text:
        return None
    days: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            days.update(range(a, b + 1))
        elif part:
            days.add(int(part))
    if not days or min(days) < 1 or max(days) > 31:
        raise ValueError(f"날짜는 1~31 사이로 적어 주세요: {text}")
    return sorted(days)


def sample_dates(start: date, end: date, days: list[int]) -> list[date]:
    """start~end 사이에서 달마다 고른 날짜만 꺼내요 (그 달에 없는 날짜는 건너뛰어요)."""
    out = []
    for w0, w1 in month_windows(start, end):
        last = calendar.monthrange(w0.year, w0.month)[1]
        out += [d for d in (date(w0.year, w0.month, k) for k in days if k <= last) if w0 <= d <= w1]
    return out


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        last = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        out.append((max(cur, start), min(last, end)))
        cur = add_months(cur, 1)
    return out


class HubClient:
    def __init__(self, settings: Settings, max_calls: int = 900, limit: int = DEFAULT_LIMIT, pause: float = 0.1,
                 client: httpx.Client | None = None, retries: int = 10, retry_pause: float = 0.2):
        if not settings.hub_project_key:
            raise HubError("MEOMUL_HUB_PROJECT_KEY 가 비어 있어요. 허브 마이페이지 > 프로젝트에서 프로젝트 키를 확인해 .env 에 넣으세요.")
        self.settings = settings
        self.max_calls = max_calls
        self.limit = limit
        self.pause = pause
        self.retries = retries
        self.retry_pause = retry_pause
        self.http = client or httpx.Client(timeout=60.0, headers={"Accept": "application/json"})
        self.hub_dir = settings.raw_dir("hub")

    # ------------------------------------------------------------------ 한 쪽 받기
    def _get(self, src: SourceSpec, params: dict[str, Any], stats: FetchStats) -> Any:
        if stats.calls + stats.failed >= self.max_calls:
            raise QuotaReached(f"호출 상한 {self.max_calls}회에 닿았어요.")
        url = f"{self.settings.hub_base_url.rstrip('/')}/{src.data_key}/{self.settings.hub_project_key}"
        last = ""
        for attempt in range(self.retries):
            try:
                r = self.http.get(url, params=params)
            except httpx.TransportError as e:  # 오류 문장에 키가 든 주소가 들어 있어서 종류만 남겨요
                last = type(e).__name__
            else:
                if r.status_code == 429 or "quota" in r.text[:200].lower():
                    raise QuotaReached("허브의 오늘 쿼터가 찼어요.")
                if r.status_code == 200:
                    try:
                        payload = r.json()
                    except json.JSONDecodeError:
                        last = "JSON 이 아닌 응답"
                    else:
                        stats.calls += 1
                        return payload
                else:
                    last = str(r.status_code)
            # 허브 프록시는 502·403 을 섞어 돌려줘서, 실패해도 잠깐 쉬고 다시 보내요
            stats.failed += 1
            if stats.calls + stats.failed >= self.max_calls:
                raise QuotaReached(f"호출 상한 {self.max_calls}회에 닿았어요.")
            time.sleep(min(self.retry_pause * (attempt + 1), 3.0))
        if last in ("401", "403"):
            raise AuthFailed(f"허브 인증 실패({last}). 프로젝트 키와 '프로젝트 담기' 여부를 확인하세요: {src.title}")
        raise HubError(f"허브 호출에 {self.retries}번 실패했어요 (마지막 응답 {last}): {src.title}")

    def _fetch_window(self, src: SourceSpec, label: str, params: dict[str, Any], stats: FetchStats) -> pd.DataFrame | None:
        """한 구간의 모든 쪽을 받아요. 받은 쪽은 _raw 에 남겨 다음 실행 때 건너뛰어요."""
        raw_dir = self.hub_dir / "_raw" / str(src.dir) / label
        raw_dir.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        page, total_pages = 1, None
        while True:
            f = raw_dir / f"{page:05d}.json"
            if f.exists():
                payload = json.loads(f.read_text(encoding="utf-8"))
            else:
                payload = self._get(src, {**src.params, **params, PAGE_PARAMS[0]: page, PAGE_PARAMS[1]: self.limit}, stats)
                f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                time.sleep(self.pause)
            data, total, more = _rows(payload)
            rows += data
            if total is not None:
                total_pages = max(1, math.ceil(total / self.limit))
            done = (total_pages is not None and page >= total_pages) or more is False or len(data) < self.limit
            if done:
                break
            page += 1
        if not rows:
            return None
        # 값의 형이 쪽마다 달라도(숫자·문자열) 저장되게 문자열로 통일해요. 형 변환은 적재 단계에서 해요.
        return pd.DataFrame(rows).astype("string")

    # ------------------------------------------------------------------ 테이블 하나
    def fetch_table(self, spec: TableSpec, start: date | None = None, end: date | None = None,
                    days: list[int] | None = None) -> FetchStats:
        """테이블 하나를 받아요. 일 단위 자료는 days 를 주면 달마다 그 날짜만 받아요 (예: [1, 9, 17, 25])."""
        src = spec.sources.get("hub")
        stats = FetchStats(table=spec.table)
        if not src or not src.data_key or not src.dir:
            stats.stopped = "허브 API 정보가 없어요"
            return stats
        out_dir = self.hub_dir / src.dir
        out_dir.mkdir(parents=True, exist_ok=True)
        today = date.today()
        if src.window == "all":  # 월 단위 자료: 한 번에 전 기간
            s = (start or datetime.strptime(MONTHLY_START, "%Y%m").date()).strftime("%Y%m")
            e = (end or today).strftime("%Y%m")
            windows = [("all", {"startDate": s, "endDate": e})]
        else:  # 일 단위 자료: 달마다 나눠 받거나, 고른 날짜만 하루씩 받아요
            s_day = start or add_months(date(today.year, today.month, 1), -36)
            e_day = end or (today - timedelta(days=1))
            if days:
                windows = [(d.strftime("%Y%m%d"), {"startDate": d.strftime("%Y%m%d"), "endDate": d.strftime("%Y%m%d")})
                           for d in sample_dates(s_day, e_day, days)]
            else:
                windows = [(w0.strftime("%Y%m"), {"startDate": w0.strftime("%Y%m%d"), "endDate": w1.strftime("%Y%m%d")})
                           for w0, w1 in month_windows(s_day, e_day)]
        try:
            for label, params in windows:
                target = out_dir / f"{label}.parquet"
                current = label in (today.strftime("%Y%m"), today.strftime("%Y%m%d"), "all")
                if target.exists() and not current:
                    stats.windows_skipped += 1
                    continue
                try:
                    df = self._fetch_window(src, label, params, stats)
                except (QuotaReached, AuthFailed):
                    raise
                except HubError:  # 그 구간만 허브가 계속 서버 오류를 내요 (예: 외국인 장기체류 2025-04·05). 건너뛰고 계속 받아요
                    stats.errors.append(label)
                    continue
                if df is not None:
                    df.to_parquet(target, index=False)
                    stats.rows += len(df)
                    stats.files.append(target.name)
                stats.windows_done += 1
        except QuotaReached as e:
            stats.stopped = f"{e} 내일 같은 명령을 다시 실행하면 이어서 받아요."
        return stats


def fetch_all(settings: Settings, tables: list[str] | None = None, start: str | None = None, end: str | None = None,
              max_calls: int = 900, days: str | None = None) -> int:
    """CLI용: 카탈로그의 허브 테이블을 차례로 받아요. 반환값은 종료 코드."""
    catalog = Catalog.load(settings.catalog_dir)
    try:
        client = HubClient(settings, max_calls=max_calls)
    except HubError as e:
        print(f"수집을 시작하지 못했어요: {e}")
        return 2
    try:
        day_list = parse_days(days)
    except ValueError as err:
        print(f"수집을 시작하지 못했어요: {err}")
        return 2
    s = datetime.strptime(start, "%Y%m%d").date() if start else None
    e = datetime.strptime(end, "%Y%m%d").date() if end else None
    code = 0
    for name, spec in catalog.tables.items():
        if tables and name not in tables:
            continue
        try:
            st = client.fetch_table(spec, s, e, day_list)
        except HubError as err:
            print(f"- {name}: 실패 — {err}")
            code = 1
            continue
        print(f"- {name}: 호출 {st.calls}회(다시 보낸 요청 {st.failed}회), {st.rows:,}행, 구간 {st.windows_done}개 완료·{st.windows_skipped}개 건너뜀"
              + (f" → {st.stopped}" if st.stopped else ""))
        if st.errors:
            print(f"  허브가 계속 서버 오류를 내서 못 받은 구간 {len(st.errors)}개: {', '.join(st.errors)}")
            code = code or 1
    print("받은 뒤에는 `python -m meomulmeong build-data --mode hub` 로 데이터 창고를 만드세요.")
    return code
