"""카탈로그: config/catalog/*.yaml (테이블 설명 파일) 로딩과 검색."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ColumnSpec(BaseModel):
    name: str
    type: str
    desc: str = ""


class SourceSpec(BaseModel):
    # 허브
    dataset_id: int | None = None
    data_key: str | None = None
    dir: str | None = None
    date_format: str | None = None  # YYYYMMDD / YYYYMM
    window: Literal["day", "month", "all"] = "all"
    params: dict[str, str] = Field(default_factory=dict)
    # 센터
    spec_no: str | None = None
    file_glob: str | None = None
    # 공통
    title: str = ""
    note: str = ""
    loader: str | None = None
    place: dict[str, str] | None = None
    select: dict[str, str]
    filter: str | None = None
    aggregate: dict[str, str] = Field(default_factory=dict)


class TableSpec(BaseModel):
    table: str
    title: str
    stages: list[int] = Field(default_factory=list)
    grain: str = ""
    time_column: str
    time_grain: Literal["day", "month"]
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    columns: list[ColumnSpec]
    limits: list[str] = Field(default_factory=list)
    sources: dict[str, SourceSpec]

    def schema_text(self) -> str:
        """LLM 프롬프트와 화면에 보여 줄 테이블 설명."""
        cols = "\n".join(f"  - {c.name} ({c.type}): {c.desc}" for c in self.columns)
        return f"테이블 {self.table} — {self.title}\n단위: {self.grain}\n{self.description.strip()}\n컬럼:\n{cols}"


def _bigrams(text: str) -> set[str]:
    t = "".join(text.split())
    return {t[i : i + 2] for i in range(len(t) - 1)}


class Catalog:
    def __init__(self, tables: dict[str, TableSpec]):
        self.tables = tables

    @classmethod
    def load(cls, catalog_dir: Path) -> Catalog:
        tables: dict[str, TableSpec] = {}
        for path in sorted(Path(catalog_dir).glob("*.yaml")):
            spec = TableSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            tables[spec.table] = spec
        if not tables:
            raise FileNotFoundError(f"카탈로그 파일이 없어요: {catalog_dir}")
        return cls(tables)

    def get(self, table: str) -> TableSpec:
        return self.tables[table]

    def search(self, query: str, k: int = 3) -> list[tuple[TableSpec, float]]:
        """질문과 가장 관련 있는 테이블을 찾아요 (키워드 일치 + 글자 2-gram 겹침)."""
        q = "".join(query.split())
        qb = _bigrams(query)
        scored: list[tuple[TableSpec, float]] = []
        for spec in self.tables.values():
            score = sum(3.0 for kw in spec.keywords if kw and kw in q)
            text = spec.title + spec.description + " ".join(c.desc for c in spec.columns)
            tb = _bigrams(text)
            if qb and tb:
                score += 10.0 * len(qb & tb) / len(qb)
            scored.append((spec, round(score, 3)))
        scored.sort(key=lambda s: (-s[1], s[0].table))
        return [s for s in scored[:k] if s[1] > 0]

    def limits_for(self, tables: list[str]) -> list[str]:
        out: list[str] = []
        for t in tables:
            for lim in self.tables[t].limits if t in self.tables else []:
                if lim not in out:
                    out.append(lim)
        return out
