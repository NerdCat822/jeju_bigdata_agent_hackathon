"""제주데이터허브 Open API 수집기.

    https://open.jejudatahub.net/api/proxy/{dataKey}/{projectKey}?startDate=…&endDate=…&number=1&limit=100

- 실행 전에 허브에서 데이터마다 '프로젝트 담기'를 하고, 프로젝트 키를 MEOMUL_HUB_PROJECT_KEY 에 넣어야 해요.
- 받은 쪽(페이지)마다 data/hub/_raw 에 저장해 두고, 다음 실행 때는 없는 쪽만 이어서 받아요 (API별 하루 쿼터 대비).
- 한 구간(월)이 끝나면 data/hub/<폴더>/<구간>.parquet 로 묶어요. 분석 중에는 API를 부르지 않아요.

주의: 응답 형식(totCnt / hasMore / data)과 쪽 매개변수(number, limit)는 허브 기술문서를 따른 것이고,
프로젝트 키 없이는 실제 호출로 확인하지 못했어요. 형식이 다르면 _rows() 와 PAGE_PARAMS 를 고치면 돼요.
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


@dataclass
class FetchStats:
    table: str
    calls: int = 0
    rows: int = 0
    windows_done: int = 0
    windows_skipped: int = 0
    stopped: str = ""
    files: list[str] = field(default_factory=list)


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


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        last = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        out.append((max(cur, start), min(last, end)))
        cur = add_months(cur, 1)
    return out


class HubClient:
    def __init__(self, settings: Settings, max_calls: int = 900, limit: int = DEFAULT_LIMIT, pause: float = 0.2,
                 client: httpx.Client | None = None):
        if not settings.hub_project_key:
            raise HubError("MEOMUL_HUB_PROJECT_KEY 가 비어 있어요. 허브 마이페이지 > 프로젝트에서 프로젝트 키를 확인해 .env 에 넣으세요.")
        self.settings = settings
        self.max_calls = max_calls
        self.limit = limit
        self.pause = pause
        self.http = client or httpx.Client(timeout=60.0, headers={"Accept": "application/json"})
        self.hub_dir = settings.raw_dir("hub")

    # ------------------------------------------------------------------ 한 쪽 받기
    def _get(self, src: SourceSpec, params: dict[str, Any], stats: FetchStats) -> Any:
        if stats.calls >= self.max_calls:
            raise QuotaReached(f"호출 상한 {self.max_calls}회에 닿았어요.")
        url = f"{self.settings.hub_base_url.rstrip('/')}/{src.data_key}/{self.settings.hub_project_key}"
        last: Exception | None = None
        for attempt in range(3):
            try:
                stats.calls += 1
                r = self.http.get(url, params=params)
                if r.status_code in (401, 403):
                    raise HubError(f"허브 인증 실패({r.status_code}). 프로젝트 키와 '프로젝트 담기' 여부를 확인하세요: {src.title}")
                if r.status_code == 429:
                    raise QuotaReached("허브 쿼터를 넘었어요 (429).")
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise HubError(f"허브 호출에 세 번 실패했어요: {last}")

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
    def fetch_table(self, spec: TableSpec, start: date | None = None, end: date | None = None) -> FetchStats:
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
        else:  # 일 단위 자료: 달마다 나눠 받아요
            s_day = start or add_months(date(today.year, today.month, 1), -36)
            e_day = end or (today - timedelta(days=1))
            windows = [(w0.strftime("%Y%m"), {"startDate": w0.strftime("%Y%m%d"), "endDate": w1.strftime("%Y%m%d")})
                       for w0, w1 in month_windows(s_day, e_day)]
        try:
            for label, params in windows:
                target = out_dir / f"{label}.parquet"
                current = label == today.strftime("%Y%m") or label == "all"
                if target.exists() and not current:
                    stats.windows_skipped += 1
                    continue
                df = self._fetch_window(src, label, params, stats)
                if df is not None:
                    df.to_parquet(target, index=False)
                    stats.rows += len(df)
                    stats.files.append(target.name)
                stats.windows_done += 1
        except QuotaReached as e:
            stats.stopped = f"{e} 내일 같은 명령을 다시 실행하면 이어서 받아요."
        return stats


def fetch_all(settings: Settings, tables: list[str] | None = None, start: str | None = None, end: str | None = None,
              max_calls: int = 900) -> int:
    """CLI용: 카탈로그의 허브 테이블을 차례로 받아요. 반환값은 종료 코드."""
    catalog = Catalog.load(settings.catalog_dir)
    try:
        client = HubClient(settings, max_calls=max_calls)
    except HubError as e:
        print(f"수집을 시작하지 못했어요: {e}")
        return 2
    s = datetime.strptime(start, "%Y%m%d").date() if start else None
    e = datetime.strptime(end, "%Y%m%d").date() if end else None
    code = 0
    for name, spec in catalog.tables.items():
        if tables and name not in tables:
            continue
        try:
            st = client.fetch_table(spec, s, e)
        except HubError as err:
            print(f"- {name}: 실패 — {err}")
            code = 1
            continue
        print(f"- {name}: 호출 {st.calls}회, {st.rows:,}행, 구간 {st.windows_done}개 완료·{st.windows_skipped}개 건너뜀"
              + (f" → {st.stopped}" if st.stopped else ""))
    print("받은 뒤에는 `python -m meomulmeong build-data --mode hub` 로 데이터 창고를 만드세요.")
    return code
