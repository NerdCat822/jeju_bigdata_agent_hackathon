"""공통 도구: 장소 표준화, 카탈로그 검색, 읽기 전용 SQL 실행."""

from __future__ import annotations

from ..data.warehouse import MART_SCHEMA, SqlRejected
from ..schemas import EvidenceTable, Fact, ToolResult
from .base import ToolContext, tool


@tool("resolve_place", "공통", "문장 속 장소 표현(읍면동·지구·시군구·거점)을 참조표의 표준 이름과 코드로 바꿔요.")
def resolve_place(ctx: ToolContext, text: str) -> ToolResult:
    matches = ctx.refs.find_places(text)
    facts = [Fact(key=f"place{i}", label=m.kind, value=m.key, unit="text", text=m.name, flag="ambiguous" if m.ambiguous else None)
             for i, m in enumerate(matches, 1)]
    return ToolResult(tool="resolve_place", ok=bool(matches), facts=facts,
                      message=None if matches else "참조표에서 장소를 찾지 못했어요.",
                      data={"matches": [{"kind": m.kind, "key": m.key, "name": m.name, "matched": m.matched,
                                         "ambiguous": m.ambiguous} for m in matches]})


@tool("search_catalog", "공통", "질문과 관련 있는 테이블을 카탈로그에서 찾아 스키마 설명을 돌려줘요.")
def search_catalog(ctx: ToolContext, query: str, k: int = 3) -> ToolResult:
    hits = ctx.catalog.search(query, k)
    usable = [(spec, score) for spec, score in hits if ctx.wh.has(spec.table)]
    return ToolResult(
        tool="search_catalog", ok=bool(usable),
        message=None if usable else "관련 테이블을 찾지 못했어요.",
        tables=[spec.table for spec, _ in usable],
        data={"tables": [{"table": spec.table, "title": spec.title, "score": score,
                          "period": ctx.table_period_label(spec.table), "schema": spec.schema_text(),
                          "mart": MART_SCHEMA.get(spec.table)}
                         for spec, score in usable]})


@tool("run_sql", "공통", "SELECT 한 문장을 읽기 전용으로 실행해요 (허용 테이블만, 행 수·시간 제한).")
def run_sql(ctx: ToolContext, sql: str, title: str = "조회 결과", max_rows: int | None = None) -> ToolResult:
    limit = max_rows or ctx.config.llm.evidence_max_rows
    try:
        res = ctx.wh.run_guarded(sql, max_rows=limit)
    except SqlRejected as e:
        return ToolResult(tool="run_sql", ok=False, message=str(e), data={"sql": sql})
    except Exception as e:  # noqa: BLE001  (DuckDB 문법·컬럼 오류)
        return ToolResult(tool="run_sql", ok=False, message=f"SQL 실행 오류: {str(e).splitlines()[0][:300]}", data={"sql": sql})
    rows = [[v.isoformat() if hasattr(v, "isoformat") else v for v in r] for r in res.rows]
    ev = EvidenceTable(id="free_sql", title=title, columns=res.columns, rows=rows, sql=res.sql,
                       note=f"최대 {limit}행까지 보여 줘요.")
    return ToolResult(tool="run_sql", evidence=[ev], data={"n_rows": len(rows)})
