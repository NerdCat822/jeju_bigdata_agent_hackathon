"""DuckDB 데이터 창고: 적재(표준화) · 월 집계 · 수록 기간표 · 읽기 전용 조회.

적재 흐름
  원본(Parquet/CSV: 합성 · 허브 수집본 · 센터 추출본)
    → 카탈로그의 select 식으로 표준 스키마 테이블 생성 (읍면동은 행정동 코드로 통일)
    → 월 집계 테이블(m_*)과 수록 기간표(meta_table) 생성
분석 중에는 이 파일을 읽기 전용으로만 열어요.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from ..settings import DATA_BADGE, AppConfig, DataMode, Settings
from .catalog import Catalog, SourceSpec, TableSpec

# --------------------------------------------------------------------------- 표준화 매크로
_MACROS = [
    """CREATE OR REPLACE MACRO std_date(x) AS CAST(COALESCE(
         try_strptime(CAST(x AS VARCHAR), '%Y%m%d'), try_strptime(CAST(x AS VARCHAR), '%Y-%m-%d')) AS DATE)""",
    """CREATE OR REPLACE MACRO std_month(x) AS CAST(COALESCE(
         try_strptime(CAST(x AS VARCHAR) || '01', '%Y%m%d'),
         try_strptime(CAST(x AS VARCHAR) || '-01', '%Y-%m-%d'),
         date_trunc('month', try_strptime(CAST(x AS VARCHAR), '%Y-%m-%d'))) AS DATE)""",
    """CREATE OR REPLACE MACRO std_sex(x) AS CASE
         WHEN trim(CAST(x AS VARCHAR)) IN ('남', '남성', '남자', 'M') THEN '남'
         WHEN trim(CAST(x AS VARCHAR)) IN ('여', '여성', '여자', 'F') THEN '여' END""",
    """CREATE OR REPLACE MACRO std_age(x) AS CASE
         WHEN x IS NULL THEN NULL
         WHEN CAST(x AS VARCHAR) LIKE '%미만%' THEN 0
         WHEN regexp_extract(CAST(x AS VARCHAR), '([0-9]+)', 1) = '' THEN NULL
         ELSE LEAST(CAST(regexp_extract(CAST(x AS VARCHAR), '([0-9]+)', 1) AS INTEGER) // 10 * 10, 70) END""",
    # 센터 유동인구 연령 코드: SKT 4자리(2024=20~24세), KT 2자리(20)
    """CREATE OR REPLACE MACRO std_age_code(x) AS CASE
         WHEN x IS NULL OR TRY_CAST(trim(CAST(x AS VARCHAR)) AS INTEGER) IS NULL THEN NULL
         WHEN length(trim(CAST(x AS VARCHAR))) >= 3
           THEN LEAST(CAST(substr(lpad(trim(CAST(x AS VARCHAR)), 4, '0'), 1, 2) AS INTEGER) // 10 * 10, 70)
         ELSE LEAST(CAST(trim(CAST(x AS VARCHAR)) AS INTEGER) // 10 * 10, 70) END""",
    """CREATE OR REPLACE MACRO std_user_type(x) AS CASE
         WHEN CAST(x AS VARCHAR) LIKE '%중국%' THEN '중국인'
         WHEN CAST(x AS VARCHAR) LIKE '%내국%' THEN '내국인'
         ELSE trim(CAST(x AS VARCHAR)) END""",
    """CREATE OR REPLACE MACRO std_theme(x) AS COALESCE(
         (SELECT theme FROM ref_theme WHERE raw = trim(CAST(x AS VARCHAR)) LIMIT 1), '기타')""",
    # 허브 실데이터는 '201-12' 처럼 갈래 번호까지 붙어 와요. 참조표에 큰 번호(201)가 있으면 그 노선으로 묶어요.
    """CREATE OR REPLACE MACRO std_route(x) AS COALESCE(
         (SELECT route_no FROM ref_route_alias WHERE alias = trim(CAST(x AS VARCHAR)) LIMIT 1),
         (SELECT route_no FROM ref_route
           WHERE route_no = regexp_extract(trim(CAST(x AS VARCHAR)), '^([0-9]+)-', 1) LIMIT 1),
         trim(CAST(x AS VARCHAR)))""",
    """CREATE OR REPLACE MACRO std_nationality(x) AS COALESCE(
         (SELECT nationality FROM ref_nationality_alias
           WHERE alias = replace(trim(CAST(x AS VARCHAR)), ' ', '') LIMIT 1),
         trim(CAST(x AS VARCHAR)))""",
]

_MARTS = {
    "m_pop_kor_emd_month": """
        SELECT CAST(date_trunc('month', base_date) AS DATE) AS month, emd_cd, age_band,
               COUNT(DISTINCT base_date) AS n_days,
               SUM(resd_pop) AS resd_sum, SUM(work_pop) AS work_sum, SUM(visit_pop) AS visit_sum
        FROM pop_kor_emd_daily
        WHERE emd_cd IS NOT NULL AND age_band IS NOT NULL
        GROUP BY 1, 2, 3""",
    "m_pop_for_long_emd_month": """
        SELECT CAST(date_trunc('month', base_date) AS DATE) AS month, emd_cd, nationality,
               COUNT(DISTINCT base_date) AS n_days,
               SUM(resd_pop) AS resd_sum, SUM(work_pop) AS work_sum, SUM(visit_pop) AS visit_sum
        FROM pop_for_long_emd_daily
        WHERE emd_cd IS NOT NULL
        GROUP BY 1, 2, 3""",
    "m_bus_route_month": """
        SELECT CAST(date_trunc('month', base_date) AS DATE) AS month, route_no,
               COUNT(DISTINCT base_date) AS n_days, SUM(user_cnt) AS riders
        FROM bus_route_daily
        GROUP BY 1, 2""",
}
# 자유 질문(LLM SQL)에 알려 줄 월 집계 테이블 설명
MART_SCHEMA = {
    "pop_kor_emd_daily": ("월 집계 테이블 m_pop_kor_emd_month (빠르고 간단해요): month (DATE, 매월 1일), emd_cd, age_band, "
                          "n_days (그 달의 수록 일수), resd_sum, work_sum, visit_sum (그 달 일별 값의 합). 하루 평균 = 합 ÷ n_days"),
    "pop_for_long_emd_daily": ("월 집계 테이블 m_pop_for_long_emd_month: month (DATE), emd_cd, nationality, n_days, "
                               "resd_sum, work_sum, visit_sum. 하루 평균 = 합 ÷ n_days"),
    "bus_route_daily": "월 집계 테이블 m_bus_route_month: month (DATE, 매월 1일), route_no, n_days, riders (그 달 이용자 합)",
}
_MART_SOURCE = {
    "m_pop_kor_emd_month": "pop_kor_emd_daily",
    "m_pop_for_long_emd_month": "pop_for_long_emd_daily",
    "m_bus_route_month": "bus_route_daily",
}


class WarehouseMissing(FileNotFoundError):
    """데이터 창고 파일이 없을 때."""


class SqlRejected(ValueError):
    """읽기 전용 가드가 SQL을 거부했을 때."""


def _q(path: Path | str) -> str:
    """SQL 문자열 리터럴용 경로 (슬래시 통일, 작은따옴표 이스케이프)."""
    return Path(path).as_posix().replace("'", "''")


def _py(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.date() if (v.hour, v.minute, v.second) == (0, 0, 0) else v
    return v


@dataclass
class Result:
    columns: list[str]
    rows: list[tuple]
    sql: str = ""

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r, strict=True)) for r in self.rows]

    def col(self, name: str) -> list[Any]:
        i = self.columns.index(name)
        return [r[i] for r in self.rows]

    def first(self) -> dict[str, Any] | None:
        return dict(zip(self.columns, self.rows[0], strict=True)) if self.rows else None

    def scalar(self) -> Any:
        return self.rows[0][0] if self.rows else None

    def __len__(self) -> int:
        return len(self.rows)


@dataclass
class TableMeta:
    table: str
    title: str
    source: str
    source_title: str
    n_rows: int
    time_grain: str
    min_date: date | None
    max_date: date | None
    note: str = ""


# =========================================================================== 읽기
class Warehouse:
    """읽기 전용 데이터 창고. 스레드마다 커서를 새로 만들어 써요."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise WarehouseMissing(
                f"데이터 창고가 없어요: {self.path}\n먼저 `python -m meomulmeong build-data` 를 실행하세요."
            )
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._con.execute("SET threads = 1")  # 같은 질문에 항상 같은 숫자 (병렬 합산은 끝자리가 흔들려요)
        self._meta: dict[str, TableMeta] | None = None
        self._build: dict[str, str] | None = None

    def close(self) -> None:
        self._con.close()

    # ---- 내부(신뢰) SQL: 도구가 만든 템플릿 SQL
    def query(self, sql: str) -> Result:
        cur = self._con.cursor()
        try:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [tuple(_py(v) for v in r) for r in cur.fetchall()]
        finally:
            cur.close()
        return Result(cols, rows, sql.strip())

    # ---- 외부(비신뢰) SQL: LLM이 쓴 자유 질의
    _FORBIDDEN = re.compile(
        r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|install|load|export|import|call|"
        r"truncate|grant|vacuum|checkpoint|describe|summarize)\b", re.I)
    _EXTERNAL = re.compile(
        r"\b(read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|parquet_scan|csv_scan|glob|"
        r"sqlite_scan|postgres_scan|getenv|duckdb_\w+|pg_\w+|information_schema)\b", re.I)

    def allowed_tables(self) -> set[str]:
        return {r[0] for r in self.query("SELECT table_name FROM meta_table").rows} | set(self._ref_tables())

    def _ref_tables(self) -> list[str]:
        return [r[0] for r in self.query(
            "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'ref_%' OR table_name LIKE 'm_%'").rows]

    def run_guarded(self, sql: str, max_rows: int = 200, timeout: float = 15.0) -> Result:
        """자유 SQL을 검사한 뒤 실행해요: SELECT 한 문장, 허용 테이블만, 행 수·시간 제한."""
        s = sql.strip().rstrip(";").strip()
        bare = re.sub(r"'(?:[^']|'')*'", "''", s)  # 문자열 리터럴 제거 후 검사
        bare = re.sub(r"--[^\n]*|/\*.*?\*/", " ", bare, flags=re.S)
        if ";" in bare:
            raise SqlRejected("한 번에 SELECT 문 하나만 실행할 수 있어요.")
        if not re.match(r"^\s*(select|with)\b", bare, re.I):
            raise SqlRejected("SELECT 문만 실행할 수 있어요.")
        if m := self._FORBIDDEN.search(bare):
            raise SqlRejected(f"허용되지 않는 키워드예요: {m.group(1)}")
        if m := self._EXTERNAL.search(bare):
            raise SqlRejected(f"파일·시스템 접근 함수는 쓸 수 없어요: {m.group(1)}")
        allowed = self.allowed_tables()
        cte = set(re.findall(r"\b(\w+)\s+as\s*\(", bare, re.I))
        used = set(re.findall(r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", bare, re.I))
        unknown = {t for t in used if t.lower() not in {a.lower() for a in allowed} and t not in cte}
        if unknown:
            raise SqlRejected(f"카탈로그에 없는 테이블이에요: {', '.join(sorted(unknown))}")

        cur = self._con.cursor()
        timer = threading.Timer(timeout, cur.interrupt)
        timer.start()
        try:
            cur.execute(f"SELECT * FROM ({s}) AS _q LIMIT {int(max_rows) + 1}")
            cols = [d[0] for d in cur.description]
            rows = [tuple(_py(v) for v in r) for r in cur.fetchall()]
        except duckdb.InterruptException as e:
            raise SqlRejected(f"{timeout:.0f}초 안에 끝나지 않아 중단했어요.") from e
        finally:
            timer.cancel()
            cur.close()
        return Result(cols, rows[:max_rows], s)

    # ---- 메타
    def meta(self) -> dict[str, TableMeta]:
        if self._meta is None:
            res = self.query("SELECT table_name, title, source, source_title, n_rows, time_grain, min_date, max_date, note FROM meta_table")
            self._meta = {r[0]: TableMeta(*r) for r in res.rows}
        return self._meta

    def build_info(self) -> dict[str, str]:
        if self._build is None:
            self._build = dict(self.query("SELECT key, value FROM meta_build").rows)
        return self._build

    @property
    def data_mode(self) -> str:
        return self.build_info().get("data_mode", "synthetic")

    @property
    def data_badge(self) -> str:
        return self.build_info().get("data_badge", DATA_BADGE["synthetic"])

    def has(self, table: str) -> bool:
        m = self.meta().get(table)
        return bool(m and m.n_rows > 0)

    def period(self, table: str) -> tuple[date, date] | None:
        m = self.meta().get(table)
        return (m.min_date, m.max_date) if m and m.min_date and m.max_date else None

    def valid_months(self, table: str, min_days: int = 20) -> list[date]:
        """지표에 쓸 수 있는 달 목록. 일 단위 테이블은 수록 일수가 min_days 이상인 달만."""
        spec_grain = self.meta()[table].time_grain
        if spec_grain == "day":
            mart = {v: k for k, v in _MART_SOURCE.items()}[table]
            sql = f"SELECT month FROM {mart} GROUP BY month HAVING MAX(n_days) >= {int(min_days)} ORDER BY month"
        else:
            sql = f"SELECT DISTINCT month FROM {table} WHERE month IS NOT NULL ORDER BY month"
        return [r[0] for r in self.query(sql).rows]

    def issues(self) -> list[dict[str, Any]]:
        return self.query("SELECT table_name, issue, detail, n FROM meta_issue ORDER BY table_name, n DESC").dicts()


# =========================================================================== 적재
@dataclass
class BuildReport:
    path: Path
    mode: str
    tables: list[TableMeta] = field(default_factory=list)
    issues: list[tuple[str, str, str, int]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"데이터 창고: {self.path}  (모드: {self.mode} · {DATA_BADGE.get(self.mode, self.mode)})"]
        for t in self.tables:
            period = f"{t.min_date}~{t.max_date}" if t.min_date else "자료 없음"
            lines.append(f"  - {t.table:<28} {t.n_rows:>9,}행  {period}  [{t.source}] {t.note}")
        for table, issue, detail, n in self.issues:
            lines.append(f"  ! {table}: {issue} ({n:,}건) {detail}")
        return "\n".join(lines)


def _stage_utf8(src: Path, stage_dir: Path) -> Path:
    """CSV를 UTF-8로 맞춰요. 이미 UTF-8이면 그대로, 아니면 CP949로 읽어 임시 파일로 옮겨요."""
    try:
        with src.open(encoding="utf-8-sig") as f:
            while f.read(1 << 20):
                pass
        return src
    except UnicodeDecodeError:
        stage_dir.mkdir(parents=True, exist_ok=True)
        dst = stage_dir / (src.stem + ".utf8.csv")
        with src.open(encoding="cp949", errors="replace", newline="") as fi, dst.open("w", encoding="utf-8", newline="") as fo:
            while chunk := fi.read(1 << 20):
                fo.write(chunk)
        return dst


def _raw_relation(base: Path, src: SourceSpec, stage_dir: Path) -> str | None:
    """원본 파일을 읽는 DuckDB 식. 파일이 없으면 None."""
    if src.file_glob:  # 센터 추출본 CSV
        files = sorted(base.glob(src.file_glob))
        if not files:
            return None
        staged = [_stage_utf8(f, stage_dir) for f in files]
        lst = ", ".join(f"'{_q(f)}'" for f in staged)
        return f"read_csv([{lst}], header = true, all_varchar = true, union_by_name = true)"
    if not src.dir:
        return None
    d = base / src.dir
    if sorted(d.glob("*.parquet")):
        return f"read_parquet('{_q(d)}/*.parquet', union_by_name = true)"
    csvs = sorted(d.glob("*.csv"))
    if csvs:
        staged = [_stage_utf8(f, stage_dir) for f in csvs]
        lst = ", ".join(f"'{_q(f)}'" for f in staged)
        return f"read_csv([{lst}], header = true, all_varchar = true, union_by_name = true)"
    return None


def _select_sql(spec: TableSpec, src: SourceSpec, raw: str, fmt: dict[str, Any]) -> str:
    items = [f"{expr.format(**fmt)} AS {col}" for col, expr in src.select.items()]
    join = ""
    if src.place:
        items.insert(1, "_a.emd_cd AS emd_cd")
        city, emd = src.place["city"], src.place["emd"]
        join = (f" LEFT JOIN ref_emd_alias _a ON _a.a_alias = replace(trim(CAST(r.{emd} AS VARCHAR)), ' ', '')"
                f" AND _a.a_city = trim(CAST(r.{city} AS VARCHAR))")
    where = f" WHERE {src.filter}" if src.filter else ""
    inner = f"SELECT {', '.join(items)} FROM {raw} AS r{join}{where}"
    if not src.aggregate:
        return inner
    cols = [c.name for c in spec.columns]
    keys = [c for c in cols if c not in src.aggregate]
    aggs = [f"{fn.upper()}({c}) AS {c}" for c, fn in src.aggregate.items()]
    return f"SELECT {', '.join(keys + aggs)} FROM ({inner}) GROUP BY {', '.join(keys)}"


def _load_foreign_visitors(con: duckdb.DuckDBPyConnection, spec: TableSpec, src: SourceSpec, raw: str, fmt: dict) -> None:
    """외국인관광객현황: 세로형(API: dtYearMonth/nationality/visitorCnt)과 가로형(파일: 연·월 + 국적 열) 모두 처리."""
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {raw}").fetchall()]
    lower = {c.lower(): c for c in cols}
    if "nationality" in lower:
        con.execute(f"CREATE TABLE {spec.table} AS {_select_sql(spec, src, raw, fmt)}")
        return
    # 가로형: 연/월 열을 찾고 나머지 숫자 열을 국적으로 펼쳐요.
    def pick(*names: str) -> str | None:
        return next((c for c in cols if any(n in c for n in names)), None)

    ym_col, y_col, m_col = pick("연월", "년월", "기준월", "dtYearMonth"), pick("연도", "년도", "년"), pick("월")
    if ym_col:
        month_expr = f"std_month(replace(replace(CAST(\"{ym_col}\" AS VARCHAR), '-', ''), '.', ''))"
        skip = {ym_col}
    elif y_col and m_col:
        month_expr = (f"make_date(CAST(regexp_extract(CAST(\"{y_col}\" AS VARCHAR), '([0-9]{{4}})', 1) AS INTEGER),"
                      f" CAST(regexp_extract(CAST(\"{m_col}\" AS VARCHAR), '([0-9]+)', 1) AS INTEGER), 1)")
        skip = {y_col, m_col}
    else:
        raise ValueError(f"외국인관광객현황 파일에서 연·월 열을 찾지 못했어요: {cols}")
    nat_cols = [c for c in cols if c not in skip and not any(k in c for k in ("합계", "총계", "계", "소계"))]
    on = ", ".join(f'"{c}"' for c in nat_cols)
    con.execute(f"""
        CREATE TABLE {spec.table} AS
        SELECT month, nationality, SUM(visitors) AS visitors FROM (
          SELECT {month_expr} AS month, std_nationality(nat) AS nationality,
                 TRY_CAST(replace(CAST(v AS VARCHAR), ',', '') AS BIGINT) AS visitors
          FROM (UNPIVOT (SELECT * FROM {raw}) ON {on} INTO NAME nat VALUE v)
        ) WHERE month IS NOT NULL AND visitors IS NOT NULL
        GROUP BY 1, 2""")


_LOADERS = {"foreign_visitors": _load_foreign_visitors}


def _load_refs(con: duckdb.DuckDBPyConnection, ref_dir: Path) -> None:
    def csv(name: str) -> str:
        return f"read_csv('{_q(ref_dir / name)}', header = true, all_varchar = true)"

    con.execute(f"""CREATE TABLE ref_emd AS
        SELECT emd_cd, emd_nm, city, emd_type, area_type, region7,
               CAST(lat AS DOUBLE) AS lat, CAST(lon AS DOUBLE) AS lon, COALESCE(aliases, '') AS aliases
        FROM {csv('ref_emd.csv')}""")
    con.execute("""CREATE TABLE ref_emd_alias AS
        SELECT DISTINCT a_city, a_alias, emd_cd FROM (
          SELECT city AS a_city, replace(emd_nm, ' ', '') AS a_alias, emd_cd FROM ref_emd
          UNION ALL
          SELECT city, replace(unnest(string_split(aliases, '|')), ' ', ''), emd_cd FROM ref_emd WHERE aliases <> ''
        ) WHERE a_alias <> ''""")
    con.execute(f"CREATE TABLE ref_zone AS SELECT zone, zone_type, COALESCE(aliases, '') AS aliases FROM {csv('ref_zone.csv')}")
    con.execute(f"CREATE TABLE ref_card_zone AS SELECT zone, emd_cd, link FROM {csv('ref_card_zone.csv')}")
    con.execute(f"CREATE TABLE ref_theme AS SELECT raw, theme FROM {csv('ref_theme.csv')}")
    con.execute(f"""CREATE TABLE ref_hub AS SELECT hub_id, hub_nm, hub_type, emd_cd,
        CAST(lat AS DOUBLE) AS lat, CAST(lon AS DOUBLE) AS lon FROM {csv('ref_hub.csv')}""")
    con.execute(f"""CREATE TABLE ref_route AS SELECT route_no, route_nm, route_type, origin, destination,
        COALESCE(variants, '') AS variants, source FROM {csv('ref_route.csv')}""")
    con.execute("""CREATE TABLE ref_route_alias AS
        SELECT DISTINCT alias, route_no FROM (
          SELECT route_no AS alias, route_no FROM ref_route
          UNION ALL
          SELECT trim(unnest(string_split(variants, '|'))), route_no FROM ref_route WHERE variants <> ''
        ) WHERE alias <> ''""")
    con.execute(f"""CREATE TABLE ref_route_emd AS SELECT route_no, CAST(seq AS INTEGER) AS seq, emd_cd
        FROM {csv('ref_route_emd.csv')}""")
    con.execute(f"CREATE TABLE ref_purpose AS SELECT purpose, purpose_group FROM {csv('ref_purpose.csv')}")
    con.execute(f"CREATE TABLE ref_nationality AS SELECT nationality, COALESCE(aliases, '') AS aliases FROM {csv('ref_nationality.csv')}")
    con.execute("""CREATE TABLE ref_nationality_alias AS
        SELECT DISTINCT alias, nationality FROM (
          SELECT replace(nationality, ' ', '') AS alias, nationality FROM ref_nationality
          UNION ALL
          SELECT replace(unnest(string_split(aliases, '|')), ' ', ''), nationality FROM ref_nationality WHERE aliases <> ''
        ) WHERE alias <> ''""")
    con.execute("""CREATE TABLE ref_month_dow AS
        SELECT CAST(date_trunc('month', d) AS DATE) AS month,
               CASE dayofweek(d) WHEN 0 THEN '일' WHEN 1 THEN '월' WHEN 2 THEN '화' WHEN 3 THEN '수'
                                 WHEN 4 THEN '목' WHEN 5 THEN '금' ELSE '토' END AS dow,
               COUNT(*) AS n_days
        FROM (SELECT CAST(unnest(generate_series(DATE '2010-01-01', DATE '2035-12-31', INTERVAL 1 DAY)) AS DATE) AS d)
        GROUP BY 1, 2""")


def _empty_table_sql(spec: TableSpec) -> str:
    cols = ", ".join(f"{c.name} {c.type}" for c in spec.columns)
    return f"CREATE TABLE {spec.table} ({cols})"


def build_warehouse(settings: Settings, config: AppConfig, catalog: Catalog, mode: DataMode | None = None) -> BuildReport:
    """원본을 읽어 데이터 창고를 새로 만들어요. 기존 파일은 완성된 뒤에 바꿔치기해요."""
    mode = mode or settings.data_mode
    path = settings.warehouse_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".building")
    for p in (tmp, Path(str(tmp) + ".wal")):
        if p.exists():
            p.unlink()
    stage_dir = path.parent / "_stage"
    fmt = {"pop_scale": repr(float(config.sources.pop_scale))}
    report = BuildReport(path=path, mode=mode)

    con = duckdb.connect(str(tmp))
    try:
        _load_refs(con, settings.ref_dir)
        for m in _MACROS:
            con.execute(m)
        con.execute("""CREATE TABLE meta_table (table_name VARCHAR, title VARCHAR, source VARCHAR, source_title VARCHAR,
            n_rows BIGINT, time_grain VARCHAR, min_date DATE, max_date DATE, note VARCHAR)""")
        con.execute("CREATE TABLE meta_issue (table_name VARCHAR, issue VARCHAR, detail VARCHAR, n BIGINT)")
        con.execute("CREATE TABLE meta_build (key VARCHAR, value VARCHAR)")

        # 원본을 찾는 순서: 센터 모드는 센터 → 허브, 허브 모드는 허브, 샘플 모드는 합성
        order = {"synthetic": [("synthetic", "hub")], "hub": [("hub", "hub")],
                 "center": [("center", "center"), ("hub", "hub")]}[mode]
        for spec in catalog.tables.values():
            used, raw, src = None, None, None
            for base_mode, src_key in order:
                cand = spec.sources.get(src_key)
                if not cand:
                    continue
                rel = _raw_relation(settings.raw_dir(base_mode), cand, stage_dir)
                if rel:
                    used, raw, src = base_mode, rel, cand
                    break
            note = ""
            if raw is None or src is None:
                con.execute(_empty_table_sql(spec))
                used, note = "none", "원본 파일이 없어 빈 테이블이에요"
                report.issues.append((spec.table, "원본 없음", "data 폴더에 수집본을 넣어 주세요", 0))
            else:
                loader = _LOADERS.get(src.loader or "")
                if loader:
                    loader(con, spec, src, raw, fmt)
                else:
                    con.execute(f"CREATE TABLE {spec.table} AS {_select_sql(spec, src, raw, fmt)}")
                if src.place:  # 행정동으로 연결하지 못한 이름 보고
                    city, emd = src.place["city"], src.place["emd"]
                    bad = con.execute(f"""
                        SELECT trim(CAST(r.{city} AS VARCHAR)) || ' ' || trim(CAST(r.{emd} AS VARCHAR)) AS nm, COUNT(*) AS n
                        FROM {raw} AS r LEFT JOIN ref_emd_alias _a
                          ON _a.a_alias = replace(trim(CAST(r.{emd} AS VARCHAR)), ' ', '') AND _a.a_city = trim(CAST(r.{city} AS VARCHAR))
                        WHERE _a.emd_cd IS NULL GROUP BY 1 ORDER BY n DESC LIMIT 20""").fetchall()
                    for nm, n in bad:
                        report.issues.append((spec.table, "행정동 미연결", str(nm), int(n)))
                    con.execute(f"DELETE FROM {spec.table} WHERE emd_cd IS NULL")
                n_null = con.execute(f"SELECT COUNT(*) FROM {spec.table} WHERE {spec.time_column} IS NULL").fetchone()[0]
                if n_null:
                    report.issues.append((spec.table, "날짜 변환 실패", "해당 행 제외", int(n_null)))
                    con.execute(f"DELETE FROM {spec.table} WHERE {spec.time_column} IS NULL")
            n, lo, hi = con.execute(
                f"SELECT COUNT(*), MIN({spec.time_column}), MAX({spec.time_column}) FROM {spec.table}").fetchone()
            src_title = src.title if src else ""
            tm = TableMeta(spec.table, spec.title, used or "none", src_title, int(n), spec.time_grain, lo, hi, note)
            report.tables.append(tm)
            con.execute("INSERT INTO meta_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [tm.table, tm.title, tm.source, tm.source_title, tm.n_rows, tm.time_grain, tm.min_date, tm.max_date, tm.note])

        for mart, sql in _MARTS.items():
            con.execute(f"CREATE TABLE {mart} AS {sql}")
        for table, issue, detail, n in report.issues:
            con.execute("INSERT INTO meta_issue VALUES (?, ?, ?, ?)", [table, issue, detail, n])

        # 배지: 원본에 합성 데이터가 하나라도 섞이면 '샘플 데이터'
        sources = {t.source for t in report.tables if t.source != "none"}
        badge_mode = "synthetic" if "synthetic" in sources else ("center" if "center" in sources else "hub")
        route_src = con.execute("SELECT COALESCE(MAX(source), '') FROM ref_route").fetchone()[0]
        build = {
            "data_mode": mode,
            "data_badge": DATA_BADGE[badge_mode],
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "pop_scale": fmt["pop_scale"],
            "route_ref_source": route_src,
        }
        con.executemany("INSERT INTO meta_build VALUES (?, ?)", list(build.items()))
        con.execute("CHECKPOINT")
    finally:
        con.close()
    os.replace(tmp, path)
    return report
