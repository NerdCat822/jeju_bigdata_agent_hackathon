"""도구 실행 환경(ToolContext)과 도구 등록부."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

from ..data.catalog import Catalog
from ..data.periods import PeriodPair, PeriodRequest, resolve_period
from ..data.refs import Refs
from ..data.warehouse import Warehouse
from ..schemas import ToolResult
from ..settings import AppConfig, Settings


@dataclass
class ToolContext:
    """도구가 쓰는 자원 묶음. 요청 하나 동안 cache 를 공유해요."""

    wh: Warehouse
    refs: Refs
    catalog: Catalog
    config: AppConfig
    settings: Settings
    cache: dict[str, Any] = field(default_factory=dict)
    _playbook: list[dict] | None = None

    @property
    def min_month_days(self) -> int:
        """한 달을 지표에 넣는 최소 일수. 허브 자료는 쿼터 때문에 달마다 며칠만 받아서(fetch-hub --days) 기준을 따로 둬요."""
        a = self.config.analysis
        return a.min_month_days_hub if self.wh.data_mode == "hub" else a.min_month_days

    def period(self, table: str, request: PeriodRequest | None = None) -> PeriodPair:
        """테이블의 수록 기간 안에서 비교 기간을 정해요."""
        a = self.config.analysis
        key = f"period:{table}:{request}"
        if key not in self.cache:
            months = self.wh.valid_months(table, self.min_month_days)
            self.cache[key] = resolve_period(months, request, a.period_months, a.min_period_months)
        return self.cache[key]

    def table_period_label(self, table: str) -> str:
        p = self.wh.period(table)
        if not p:
            return "자료 없음"
        return f"{p[0].year}-{p[0].month:02d}~{p[1].year}-{p[1].month:02d}"

    def limits(self, tables: list[str]) -> list[str]:
        return self.catalog.limits_for(tables)

    @property
    def playbook(self) -> list[dict]:
        if self._playbook is None:
            path = self.settings.config_dir / "playbook.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self._playbook = sorted(data.get("rules", []), key=lambda r: (r.get("priority", 99), r["id"]))
        return self._playbook

    def new_request(self) -> ToolContext:
        """요청마다 캐시를 비운 복사본."""
        return ToolContext(self.wh, self.refs, self.catalog, self.config, self.settings, {}, self._playbook)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str  # 공통 / Stage 1 / Stage 2 / Stage 3 / 출력
    description: str
    fn: Callable[..., ToolResult]


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, group: str, description: str) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    """도구 등록 데코레이터."""

    def deco(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        TOOLS[name] = ToolSpec(name, group, description, fn)
        return fn

    return deco


def sql_in(values: list[Any]) -> str:
    """IN 절 리터럴. 참조표에서 온 값만 넣어요 (사용자 입력을 그대로 넣지 않아요)."""
    out = []
    for v in values:
        if isinstance(v, (int, float)):
            out.append(str(v))
        else:
            out.append("'" + str(v).replace("'", "''") + "'")
    return ", ".join(out) if out else "NULL"


def sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
