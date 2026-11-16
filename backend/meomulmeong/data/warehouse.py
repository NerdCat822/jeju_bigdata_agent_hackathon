"""PostgreSQL 데이터 창고: 적재(표준화) · 월 집계 · 수록 기간표 · 읽기 전용 조회.

적재 흐름
  원본(Parquet/CSV: 합성 · 허브 수집본 · 센터 추출본)
    → 글자 그대로 임시 테이블(_raw_*)에 올림
    → 카탈로그의 select 식으로 표준 스키마 테이블 생성 (읍면동은 행정동 코드로 통일)
    → 월 집계 테이블(m_*)과 수록 기간표(meta_table) 생성
데이터 모드마다 스키마 하나(synthetic · hub · center)를 쓰고, 분석 중에는 읽기 전용으로만 열어요.
"""

from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from ..settings import DATA_BADGE, AppConfig, DataMode, Settings
from .catalog import Catalog, SourceSpec, TableSpec

# --------------------------------------------------------------------------- 표준화 함수
# 카탈로그의 select 식에서 쓰는 함수예요. 원본은 모두 글자(TEXT)로 올라오므로 글자를 받아요.
_NUMERIC = r"^[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$"
_FUNCTIONS = [
    # 숫자로 읽을 수 없는 값은 NULL 로 둬요 (멈추지 않고 빼요)
    f"""CREATE FUNCTION to_double(x text) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE WHEN trim(x) ~ '{_NUMERIC}' THEN CAST(trim(x) AS double precision) END $$""",
    f"""CREATE FUNCTION to_bigint(x text) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE WHEN trim(x) ~ '{_NUMERIC}' THEN CAST(round(CAST(trim(x) AS numeric)) AS bigint) END $$""",
    # 없는 날짜(2월 30일 등)는 NULL
    """CREATE FUNCTION ymd(y integer, m integer, d integer) RETURNS date LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE WHEN y BETWEEN 1 AND 9999 AND m BETWEEN 1 AND 12 AND d BETWEEN 1 AND 31 THEN
                  CASE WHEN EXTRACT(month FROM make_date(y, m, 1) + (d - 1)) = m THEN make_date(y, m, 1) + (d - 1) END
                END $$""",
    """CREATE FUNCTION std_date(x text) RETURNS date LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE
           WHEN trim(x) ~ '^[0-9]{8}$' THEN
             ymd(CAST(substr(trim(x), 1, 4) AS integer), CAST(substr(trim(x), 5, 2) AS integer), CAST(substr(trim(x), 7, 2) AS integer))
           WHEN trim(x) ~ '^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}$' THEN
             ymd(CAST(split_part(trim(x), '-', 1) AS integer), CAST(split_part(trim(x), '-', 2) AS integer),
                 CAST(split_part(trim(x), '-', 3) AS integer))
         END $$""",
    """CREATE FUNCTION std_month(x text) RETURNS date LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE
           WHEN trim(x) ~ '^[0-9]{6}$' THEN
             ymd(CAST(substr(trim(x), 1, 4) AS integer), CAST(substr(trim(x), 5, 2) AS integer), 1)
           WHEN trim(x) ~ '^[0-9]{4}-[0-9]{1,2}$' THEN
             ymd(CAST(split_part(trim(x), '-', 1) AS integer), CAST(split_part(trim(x), '-', 2) AS integer), 1)
           WHEN trim(x) ~ '^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}$' THEN CAST(date_trunc('month', std_date(x)) AS date)
         END $$""",
    """CREATE FUNCTION std_sex(x text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE WHEN trim(x) IN ('남', '남성', '남자', 'M') THEN '남'
                     WHEN trim(x) IN ('여', '여성', '여자', 'F') THEN '여' END $$""",
    """CREATE FUNCTION std_age(x text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE
           WHEN x IS NULL THEN NULL
           WHEN x LIKE '%미만%' THEN 0
           WHEN substring(x from '([0-9]+)') IS NULL THEN NULL
           ELSE LEAST(CAST(substring(x from '([0-9]+)') AS integer) / 10 * 10, 70) END $$""",
    # 센터 유동인구 연령 코드: SKT 4자리(2024=20~24세), KT 2자리(20)
    """CREATE FUNCTION std_age_code(x text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE
           WHEN x IS NULL OR trim(x) !~ '^[0-9]+$' THEN NULL
           WHEN length(trim(x)) >= 3 THEN LEAST(CAST(substr(lpad(trim(x), 4, '0'), 1, 2) AS integer) / 10 * 10, 70)
           ELSE LEAST(CAST(trim(x) AS integer) / 10 * 10, 70) END $$""",
    """CREATE FUNCTION std_user_type(x text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
         SELECT CASE WHEN x LIKE '%중국%' THEN '중국인' WHEN x LIKE '%내국%' THEN '내국인' ELSE trim(x) END $$""",
    """CREATE FUNCTION std_theme(x text) RETURNS text LANGUAGE sql STABLE AS $$
         SELECT COALESCE((SELECT theme FROM ref_theme WHERE raw = trim(x) LIMIT 1), '기타') $$""",
    # 허브 실데이터는 '201-12' 처럼 갈래 번호까지 붙어 와요. 참조표에 큰 번호(201)가 있으면 그 노선으로 묶어요.
    """CREATE FUNCTION std_route(x text) RETURNS text LANGUAGE sql STABLE AS $$
         SELECT COALESCE(
           (SELECT route_no FROM ref_route_alias WHERE alias = trim(x) LIMIT 1),
           (SELECT route_no FROM ref_route WHERE route_no = substring(trim(x) from '^([0-9]+)-') LIMIT 1),
           trim(x)) $$""",
    """CREATE FUNCTION std_nationality(x text) RETURNS text LANGUAGE sql STABLE AS $$
         SELECT COALESCE(
           (SELECT nationality FROM ref_nationality_alias WHERE alias = replace(trim(x), ' ', '') LIMIT 1),
           trim(x)) $$""",
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
               COUNT(DISTINCT base_date) AS n_days, CAST(SUM(user_cnt) AS BIGINT) AS riders
        FROM bus_route_daily
        GROUP BY 1, 2""",
}
# 자유 질문(LLM SQL)에 알려 줄 월 집계 테이블 설명
MART_SCHEMA = {
    "pop_kor_emd_daily": ("월 집계 테이블 m_pop_kor_emd_month (빠르고 간단해요): month (DATE, 매월 1일), emd_cd, age_band, "
                          "n_days (그 달의 수록 일수), resd_sum, work_sum, visit_sum (그 달 일별 값의 합). 하루 평균 = 합 ÷ n_days"),
    "pop_for_long_emd_daily": ("월 집계 테이블 m_pop_for_long_emd_month: month (DATE), emd_cd, nationality, n_days, "
                               "resd_sum, work_sum, visit_sum. 하루 평균 = 합 ÷ n_days"),
    "bus_route_daily": ("월 집계 테이블 m_bus_route_month: month (DATE, 매월 1일), route_no, n_days (그 달의 수록 일수), "
                        "riders (수록된 날의 이용자 합). 달마다 수록 일수가 다를 수 있으니 달끼리 비교할 때는 하루 평균(riders ÷ n_days)을 써요"),
}
_MART_SOURCE = {
    "m_pop_kor_emd_month": "pop_kor_emd_daily",
    "m_pop_for_long_emd_month": "pop_for_long_emd_daily",
    "m_bus_route_month": "bus_route_daily",
}

# 카탈로그 타입 → PostgreSQL 타입. 글자 컬럼은 정렬 순서가 어느 PC 에서나 같도록 "C" 로 맞춰요.
_TEXT = 'TEXT COLLATE "C"'
_PG_TYPE = {"VARCHAR": _TEXT, "TEXT": _TEXT, "DOUBLE": "DOUBLE PRECISION", "BIGINT": "BIGINT", "INTEGER": "INTEGER",
            "DATE": "DATE"}


class WarehouseMissing(RuntimeError):
    """데이터 창고(스키마)가 없거나 PostgreSQL 에 붙지 못할 때."""


class WarehouseUnreachable(WarehouseMissing):
    """PostgreSQL 서버에 연결하지 못했을 때."""


class SqlRejected(ValueError):
    """읽기 전용 가드가 SQL을 거부했을 때."""


def _ident(name: str) -> str:
    """식별자를 큰따옴표로 감싸요."""
    return '"' + str(name).replace('"', '""') + '"'


def _schema_name(name: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,50}", name):
        raise ValueError(f"스키마 이름으로 쓸 수 없어요: {name!r}")
    return name


def _cast(expr: str, type_: str) -> str:
    pg = _PG_TYPE.get(type_.upper(), type_)
    return f'CAST({expr} AS TEXT) COLLATE "C"' if pg == _TEXT else f"CAST({expr} AS {pg})"


def _py(v: Any) -> Any:
    if isinstance(v, Decimal):  # 정수 합계(numeric)는 정수로, 나머지는 실수로
        return int(v) if v.is_finite() and v.as_tuple().exponent >= 0 else float(v)
    if isinstance(v, datetime):
        return v.date() if (v.hour, v.minute, v.second) == (0, 0, 0) else v
    return v


def connect(settings: Settings) -> psycopg.Connection:
    """PostgreSQL 에 붙어요. 붙지 못하면 무엇을 해야 하는지 알려 줘요 (암호는 메시지에 넣지 않아요)."""
    try:
        con = psycopg.connect(settings.pg_conninfo, autocommit=True)
    except psycopg.OperationalError as e:
        raise WarehouseUnreachable(
            f"데이터 창고({settings.pg_label})에 연결하지 못했어요.\n"
            "먼저 `docker compose up -d db` 로 PostgreSQL 을 띄우세요. 다른 서버를 쓰면 backend/.env 의 MEOMUL_PG_* 값을 확인하세요."
        ) from e
    with con.cursor() as cur:
        cur.execute("SET max_parallel_workers_per_gather = 0")  # 같은 질문에 항상 같은 숫자 (병렬 합산은 끝자리가 흔들려요)
    return con


def warehouse_exists(settings: Settings, modes: list[str]) -> dict[str, bool]:
    """데이터 모드마다 창고(스키마)가 만들어져 있는지 알려 줘요. PostgreSQL 에 붙지 못하면 모두 False."""
    try:
        con = connect(settings)
    except WarehouseUnreachable:
        return dict.fromkeys(modes, False)
    try:
        with con.cursor() as cur:
            out = {}
            for m in modes:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL", [f"{_ident(settings.pg_schema(m))}.meta_build"])  # type: ignore[arg-type]
                out[m] = bool(cur.fetchone()[0])
            return out
    finally:
        con.close()


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
    """읽기 전용 데이터 창고. 연결 하나를 잠금으로 나눠 써요 (한 번에 질의 하나)."""

    def __init__(self, settings: Settings, mode: DataMode | None = None):
        self.settings = settings
        self.schema = _schema_name(settings.pg_schema(mode))
        self._lock = threading.RLock()
        self._con: psycopg.Connection | None = None
        self._meta: dict[str, TableMeta] | None = None
        self._build: dict[str, str] | None = None
        self._open()

    def _open(self) -> None:
        con = connect(self.settings)
        try:
            with con.cursor() as cur:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL", [f"{_ident(self.schema)}.meta_build"])
                if not cur.fetchone()[0]:
                    raise WarehouseMissing(
                        f"데이터 창고가 없어요: {self.settings.pg_label} 의 스키마 {self.schema}\n"
                        "먼저 `python -m meomulmeong build-data` 를 실행하세요."
                    )
                cur.execute(f"SET search_path = {_ident(self.schema)}")
                cur.execute("SET default_transaction_read_only = on")
        except BaseException:
            con.close()
            raise
        self._con = con

    def close(self) -> None:
        with self._lock:
            if self._con is not None and not self._con.closed:
                self._con.close()

    def _run(self, sql: str, timeout_ms: int = 0) -> tuple[list[str], list[tuple]]:
        with self._lock:
            for attempt in (1, 2):
                if self._con is None or self._con.closed or self._con.broken:
                    self._open()
                assert self._con is not None
                try:
                    with self._con.cursor() as cur:
                        if timeout_ms:
                            cur.execute(f"SET statement_timeout = {int(timeout_ms)}")
                        try:
                            cur.execute(sql)  # type: ignore[arg-type]
                            cols = [d.name for d in cur.description or []]
                            rows = [tuple(_py(v) for v in r) for r in cur.fetchall()]
                        finally:
                            if timeout_ms and not self._con.broken:
                                cur.execute("SET statement_timeout = 0")
                    return cols, rows
                except psycopg.errors.QueryCanceled:
                    raise
                except psycopg.OperationalError:  # 서버가 다시 떴거나 연결이 끊겼으면 한 번만 다시 붙어요
                    if attempt == 2:
                        raise
                    self._con = None
        raise AssertionError("unreachable")

    # ---- 내부(신뢰) SQL: 도구가 만든 템플릿 SQL
    def query(self, sql: str) -> Result:
        cols, rows = self._run(sql)
        return Result(cols, rows, sql.strip())

    # ---- 외부(비신뢰) SQL: LLM이 쓴 자유 질의
    _FORBIDDEN = re.compile(
        r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|install|load|export|import|call|"
        r"truncate|grant|revoke|vacuum|checkpoint|describe|summarize|analyze|explain|listen|notify|lock|reindex|"
        r"cluster|refresh|prepare|execute|deallocate|declare|discard|reset|into)\b", re.I)
    _EXTERNAL = re.compile(
        r"\b(read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|parquet_scan|csv_scan|glob|"
        r"sqlite_scan|postgres_scan|getenv|duckdb_\w+|pg_\w+|information_schema|current_setting|set_config|"
        r"dblink\w*|lo_\w+|\w+_to_xml\w*|current_user|session_user|current_database|current_schemas?|"
        r"inet_\w+|version)\b", re.I)

    def allowed_tables(self) -> set[str]:
        return {r[0] for r in self.query("SELECT table_name FROM meta_table").rows} | set(self._ref_tables())

    def _ref_tables(self) -> list[str]:
        return [r[0] for r in self.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
            r"AND (table_name LIKE 'ref\_%' OR table_name LIKE 'm\_%')").rows]

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
        if "$" in bare:
            raise SqlRejected("달러 따옴표($$)는 쓸 수 없어요.")
        allowed = self.allowed_tables()
        cte = set(re.findall(r"\b(\w+)\s+as\s*\(", bare, re.I))
        used = set(re.findall(r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", bare, re.I))
        unknown = {t for t in used if t.lower() not in {a.lower() for a in allowed} and t not in cte}
        if unknown:
            raise SqlRejected(f"카탈로그에 없는 테이블이에요: {', '.join(sorted(unknown))}")

        try:  # 읽기 전용 연결에서, 하위 질의로 감싸 SELECT 만 실행되게 해요
            cols, rows = self._run(f"SELECT * FROM ({s}) AS _q LIMIT {int(max_rows) + 1}", timeout_ms=int(timeout * 1000))
        except psycopg.errors.QueryCanceled as e:
            raise SqlRejected(f"{timeout:.0f}초 안에 끝나지 않아 중단했어요.") from e
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
    where: str
    mode: str
    tables: list[TableMeta] = field(default_factory=list)
    issues: list[tuple[str, str, str, int]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"데이터 창고: {self.where}  (모드: {self.mode} · {DATA_BADGE.get(self.mode, self.mode)})"]
        for t in self.tables:
            period = f"{t.min_date}~{t.max_date}" if t.min_date else "자료 없음"
            lines.append(f"  - {t.table:<28} {t.n_rows:>9,}행  {period}  [{t.source}] {t.note}")
        for table, issue, detail, n in self.issues:
            lines.append(f"  ! {table}: {issue} ({n:,}건) {detail}")
        return "\n".join(lines)


def _read_csv(path: Path) -> pd.DataFrame:
    """CSV를 글자 그대로 읽어요. UTF-8이 아니면 CP949로 읽어요. 빈 칸만 빈 값으로 봐요."""
    kw: dict[str, Any] = {"dtype": str, "keep_default_na": False, "na_values": [""]}
    try:
        return pd.read_csv(path, encoding="utf-8-sig", **kw)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949", encoding_errors="replace", **kw)


def _raw_frame(base: Path, src: SourceSpec) -> pd.DataFrame | None:
    """원본 파일을 읽어 표 하나로 합쳐요 (컬럼은 이름으로 맞춰요). 파일이 없으면 None."""
    if src.file_glob:  # 센터 추출본 CSV
        files = sorted(base.glob(src.file_glob))
        frames = [_read_csv(f) for f in files]
    elif src.dir:
        d = base / src.dir
        parquets = sorted(d.glob("*.parquet"))
        frames = [pd.read_parquet(f) for f in parquets] if parquets else [_read_csv(f) for f in sorted(d.glob("*.csv"))]
    else:
        frames = []
    if not frames:
        return None
    return frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True, sort=False)


def _exported_frame(export_dir: Path, spec: TableSpec) -> pd.DataFrame | None:
    """`export-csv` 로 내보낸 표(data/export/<모드>/<테이블>.csv)를 읽어요. 이미 표준 컬럼이라 변환 없이 올려요. 없으면 None."""
    path = export_dir / f"{spec.table}.csv"
    return _read_csv(path) if path.is_file() else None


def _copy_frame(cur: psycopg.Cursor, table: str, df: pd.DataFrame) -> list[str]:
    """표를 글자(TEXT) 컬럼 테이블로 올려요. 컬럼 이름은 소문자로 바꿔요 (select 식에서 따옴표 없이 쓰려고요)."""
    cols = [str(c).strip().lower() for c in df.columns]
    if len(set(cols)) != len(cols):
        raise ValueError(f"대소문자만 다른 컬럼 이름이 겹쳐요: {list(df.columns)}")
    cur.execute(f"CREATE TABLE {_ident(table)} ({', '.join(f'{_ident(c)} TEXT' for c in cols)})")  # type: ignore[arg-type]
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    with cur.copy(f"COPY {_ident(table)} FROM STDIN WITH (FORMAT csv, NULL '')") as cp:  # type: ignore[arg-type]
        while chunk := buf.read(1 << 20):
            cp.write(chunk)
    return cols


def _select_sql(spec: TableSpec, src: SourceSpec, raw: str, fmt: dict[str, Any]) -> tuple[str, list[str]]:
    """표준 컬럼을 만드는 SELECT 문과 그 결과 컬럼 이름."""
    items = [f"{expr.format(**fmt)} AS {col}" for col, expr in src.select.items()]
    names = list(src.select)
    join = ""
    if src.place:
        items.insert(1, "_a.emd_cd AS emd_cd")
        names.insert(1, "emd_cd")
        city, emd = src.place["city"], src.place["emd"]
        join = (f" LEFT JOIN ref_emd_alias _a ON _a.a_alias = replace(trim(CAST(r.{emd} AS VARCHAR)), ' ', '')"
                f" AND _a.a_city = trim(CAST(r.{city} AS VARCHAR))")
    where = f" WHERE {src.filter}" if src.filter else ""
    inner = f"SELECT {', '.join(items)} FROM {raw} AS r{join}{where}"
    if not src.aggregate:
        return inner, names
    cols = [c.name for c in spec.columns]
    keys = [c for c in cols if c not in src.aggregate]
    aggs = [f"{fn.upper()}({c}) AS {c}" for c, fn in src.aggregate.items()]
    return f"SELECT {', '.join(keys + aggs)} FROM ({inner}) AS s GROUP BY {', '.join(keys)}", keys + list(src.aggregate)


def _create_table(cur: psycopg.Cursor, spec: TableSpec, select_sql: str, names: list[str]) -> None:
    """SELECT 결과를 카탈로그에 적힌 타입으로 맞춰 테이블로 만들어요."""
    types = {c.name: c.type for c in spec.columns}
    items = [f"{_cast(n, types[n])} AS {n}" if n in types else n for n in names]
    cur.execute(f"CREATE TABLE {spec.table} AS SELECT {', '.join(items)} FROM ({select_sql}) AS q")  # type: ignore[arg-type]


def _load_foreign_visitors(cur: psycopg.Cursor, spec: TableSpec, src: SourceSpec, raw: str, cols: list[str], fmt: dict) -> None:
    """외국인관광객현황: 세로형(API: dtYearMonth/nationality/visitorCnt)과 가로형(파일: 연·월 + 국적 열) 모두 처리."""
    if "nationality" in cols:
        _create_table(cur, spec, *_select_sql(spec, src, raw, fmt))
        return
    # 가로형: 연/월 열을 찾고 나머지 숫자 열을 국적으로 펼쳐요.
    def pick(*names: str) -> str | None:
        return next((c for c in cols if any(n.lower() in c for n in names)), None)

    ym_col, y_col, m_col = pick("연월", "년월", "기준월", "dtYearMonth"), pick("연도", "년도", "년"), pick("월")
    if ym_col:
        month_expr = f"std_month(replace(replace({_ident(ym_col)}, '-', ''), '.', ''))"
        skip = {ym_col}
    elif y_col and m_col:
        month_expr = (f"ymd(CAST(substring({_ident(y_col)} from '([0-9]{{4}})') AS integer),"
                      f" CAST(substring({_ident(m_col)} from '([0-9]+)') AS integer), 1)")
        skip = {y_col, m_col}
    else:
        raise ValueError(f"외국인관광객현황 파일에서 연·월 열을 찾지 못했어요: {cols}")
    nat_cols = [c for c in cols if c not in skip and not any(k in c for k in ("합계", "총계", "계", "소계"))]
    pairs = ", ".join(f"('{c.replace(chr(39), chr(39) * 2)}', {_ident(c)})" for c in nat_cols)
    inner = f"""
        SELECT month, nationality, SUM(visitors) AS visitors FROM (
          SELECT {month_expr} AS month, std_nationality(u.nat) AS nationality,
                 to_bigint(replace(u.v, ',', '')) AS visitors
          FROM {raw} AS r CROSS JOIN LATERAL (VALUES {pairs}) AS u(nat, v)
        ) AS w WHERE month IS NOT NULL AND visitors IS NOT NULL
        GROUP BY 1, 2"""
    _create_table(cur, spec, inner, ["month", "nationality", "visitors"])


_LOADERS = {"foreign_visitors": _load_foreign_visitors}


def _load_refs(cur: psycopg.Cursor, ref_dir: Path) -> None:
    def raw(name: str) -> str:
        table = f"_raw_{name}"
        _copy_frame(cur, table, _read_csv(ref_dir / f"{name}.csv"))
        return table

    def t(col: str, default_empty: bool = False) -> str:  # 글자 컬럼
        expr = f"COALESCE({col}, '')" if default_empty else col
        return f'CAST({expr} AS TEXT) COLLATE "C" AS {col}'

    cur.execute(f"""CREATE TABLE ref_emd AS
        SELECT {t('emd_cd')}, {t('emd_nm')}, {t('city')}, {t('emd_type')}, {t('area_type')}, {t('region7')},
               CAST(lat AS DOUBLE PRECISION) AS lat, CAST(lon AS DOUBLE PRECISION) AS lon, {t('aliases', True)}
        FROM {raw('ref_emd')}""")  # type: ignore[arg-type]
    cur.execute("""CREATE TABLE ref_emd_alias AS
        SELECT DISTINCT a_city, a_alias, emd_cd FROM (
          SELECT city AS a_city, replace(emd_nm, ' ', '') AS a_alias, emd_cd FROM ref_emd
          UNION ALL
          SELECT city, replace(unnest(string_to_array(aliases, '|')), ' ', ''), emd_cd FROM ref_emd WHERE aliases <> ''
        ) AS x WHERE a_alias <> ''""")
    cur.execute(f"CREATE TABLE ref_zone AS SELECT {t('zone')}, {t('zone_type')}, {t('aliases', True)} FROM {raw('ref_zone')}")  # type: ignore[arg-type]
    cur.execute(f"CREATE TABLE ref_card_zone AS SELECT {t('zone')}, {t('emd_cd')}, {t('link')} FROM {raw('ref_card_zone')}")  # type: ignore[arg-type]
    cur.execute(f"CREATE TABLE ref_theme AS SELECT {t('raw')}, {t('theme')} FROM {raw('ref_theme')}")  # type: ignore[arg-type]
    cur.execute(f"""CREATE TABLE ref_hub AS SELECT {t('hub_id')}, {t('hub_nm')}, {t('hub_type')}, {t('emd_cd')},
        CAST(lat AS DOUBLE PRECISION) AS lat, CAST(lon AS DOUBLE PRECISION) AS lon FROM {raw('ref_hub')}""")  # type: ignore[arg-type]
    cur.execute(f"""CREATE TABLE ref_route AS SELECT {t('route_no')}, {t('route_nm')}, {t('route_type')}, {t('origin')},
        {t('destination')}, {t('variants', True)}, {t('source')} FROM {raw('ref_route')}""")  # type: ignore[arg-type]
    cur.execute("""CREATE TABLE ref_route_alias AS
        SELECT DISTINCT alias, route_no FROM (
          SELECT route_no AS alias, route_no FROM ref_route
          UNION ALL
          SELECT trim(unnest(string_to_array(variants, '|'))), route_no FROM ref_route WHERE variants <> ''
        ) AS x WHERE alias <> ''""")
    cur.execute(f"""CREATE TABLE ref_route_emd AS SELECT {t('route_no')}, CAST(seq AS INTEGER) AS seq, {t('emd_cd')}
        FROM {raw('ref_route_emd')}""")  # type: ignore[arg-type]
    cur.execute(f"CREATE TABLE ref_purpose AS SELECT {t('purpose')}, {t('purpose_group')} FROM {raw('ref_purpose')}")  # type: ignore[arg-type]
    cur.execute(f"CREATE TABLE ref_nationality AS SELECT {t('nationality')}, {t('aliases', True)} FROM {raw('ref_nationality')}")  # type: ignore[arg-type]
    cur.execute("""CREATE TABLE ref_nationality_alias AS
        SELECT DISTINCT alias, nationality FROM (
          SELECT replace(nationality, ' ', '') AS alias, nationality FROM ref_nationality
          UNION ALL
          SELECT replace(unnest(string_to_array(aliases, '|')), ' ', ''), nationality FROM ref_nationality WHERE aliases <> ''
        ) AS x WHERE alias <> ''""")
    cur.execute("""CREATE TABLE ref_month_dow AS
        SELECT CAST(date_trunc('month', d) AS DATE) AS month,
               CAST(CASE CAST(EXTRACT(dow FROM d) AS INTEGER) WHEN 0 THEN '일' WHEN 1 THEN '월' WHEN 2 THEN '화'
                    WHEN 3 THEN '수' WHEN 4 THEN '목' WHEN 5 THEN '금' ELSE '토' END AS TEXT) COLLATE "C" AS dow,
               COUNT(*) AS n_days
        FROM generate_series(TIMESTAMP '2010-01-01', TIMESTAMP '2035-12-31', INTERVAL '1 day') AS g(d)
        GROUP BY 1, 2""")


def _empty_table_sql(spec: TableSpec) -> str:
    cols = ", ".join(f"{c.name} {_PG_TYPE.get(c.type.upper(), c.type)}" for c in spec.columns)
    return f"CREATE TABLE {spec.table} ({cols})"


def build_warehouse(settings: Settings, config: AppConfig, catalog: Catalog, mode: DataMode | None = None) -> BuildReport:
    """원본을 읽어 데이터 창고를 새로 만들어요. 임시 스키마에 다 만든 뒤 기존 스키마와 바꿔치기해요."""
    mode = mode or settings.data_mode
    schema = _schema_name(settings.pg_schema(mode))
    tmp = _schema_name(schema + "__new")
    fmt = {"pop_scale": repr(float(config.sources.pop_scale))}
    report = BuildReport(where=f"{settings.pg_label} · 스키마 {schema}", mode=mode)

    con = connect(settings)
    try:
        cur = con.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {_ident(tmp)} CASCADE")
        cur.execute(f"CREATE SCHEMA {_ident(tmp)}")
        cur.execute(f"SET search_path = {_ident(tmp)}")
        _load_refs(cur, settings.ref_dir)
        for f in _FUNCTIONS:
            cur.execute(f)  # type: ignore[arg-type]
        cur.execute(f"""CREATE TABLE meta_table (table_name {_TEXT}, title {_TEXT}, source {_TEXT}, source_title {_TEXT},
            n_rows BIGINT, time_grain {_TEXT}, min_date DATE, max_date DATE, note {_TEXT})""")  # type: ignore[arg-type]
        cur.execute(f"CREATE TABLE meta_issue (table_name {_TEXT}, issue {_TEXT}, detail {_TEXT}, n BIGINT)")  # type: ignore[arg-type]
        cur.execute(f"CREATE TABLE meta_build (key {_TEXT}, value {_TEXT})")  # type: ignore[arg-type]

        # 원본을 찾는 순서: 센터 모드는 센터 → 허브, 허브 모드는 허브, 샘플 모드는 합성
        order = {"synthetic": [("synthetic", "hub")], "hub": [("hub", "hub")],
                 "center": [("center", "center"), ("hub", "hub")]}[mode]
        for spec in catalog.tables.values():
            used, frame, src, exported = None, None, None, False
            for base_mode, src_key in order:
                cand = spec.sources.get(src_key)
                if not cand:
                    continue
                df = _raw_frame(settings.raw_dir(base_mode), cand)
                if df is None:  # 수집본이 없으면 export-csv 로 내보낸 표를 찾아요 (다른 PC 에서 만든 창고를 옮길 때)
                    df = _exported_frame(settings.export_dir(base_mode), spec)
                    exported = df is not None
                if df is not None:
                    used, frame, src = base_mode, df, cand
                    break
            note = ""
            if frame is None or src is None:
                cur.execute(_empty_table_sql(spec))  # type: ignore[arg-type]
                used, note = "none", "원본 파일이 없어 빈 테이블이에요"
                report.issues.append((spec.table, "원본 없음", "data 폴더에 수집본을 넣어 주세요", 0))
            else:
                raw = f"_raw_{spec.table}"
                cols = _copy_frame(cur, raw, frame)
                del frame
                loader = _LOADERS.get(src.loader or "")
                if exported:
                    names = [c.name for c in spec.columns]
                    missing = [n for n in names if n not in cols]
                    if missing:
                        raise ValueError(f"{settings.export_dir(used)}/{spec.table}.csv 에 표준 컬럼이 빠졌어요: {missing}. "
                                         "export-csv 로 내보낸 파일인지 확인해 주세요.")
                    _create_table(cur, spec, f"SELECT {', '.join(names)} FROM {raw}", names)
                    note = "내보낸 표(CSV)에서 올렸어요"
                elif loader:
                    loader(cur, spec, src, raw, cols, fmt)
                else:
                    _create_table(cur, spec, *_select_sql(spec, src, raw, fmt))
                if src.place and not exported:  # 행정동으로 연결하지 못한 이름 보고
                    city, emd = src.place["city"], src.place["emd"]
                    cur.execute(f"""
                        SELECT trim(CAST(r.{city} AS VARCHAR)) || ' ' || trim(CAST(r.{emd} AS VARCHAR)) AS nm, COUNT(*) AS n
                        FROM {raw} AS r LEFT JOIN ref_emd_alias _a
                          ON _a.a_alias = replace(trim(CAST(r.{emd} AS VARCHAR)), ' ', '') AND _a.a_city = trim(CAST(r.{city} AS VARCHAR))
                        WHERE _a.emd_cd IS NULL GROUP BY 1 ORDER BY n DESC, nm LIMIT 20""")  # type: ignore[arg-type]
                    for nm, n in cur.fetchall():
                        report.issues.append((spec.table, "행정동 미연결", str(nm), int(n)))
                    cur.execute(f"DELETE FROM {spec.table} WHERE emd_cd IS NULL")  # type: ignore[arg-type]
                cur.execute(f"SELECT COUNT(*) FROM {spec.table} WHERE {spec.time_column} IS NULL")  # type: ignore[arg-type]
                n_null = cur.fetchone()[0]
                if n_null:
                    report.issues.append((spec.table, "날짜 변환 실패", "해당 행 제외", int(n_null)))
                    cur.execute(f"DELETE FROM {spec.table} WHERE {spec.time_column} IS NULL")  # type: ignore[arg-type]
                cur.execute(f"DROP TABLE {raw}")  # type: ignore[arg-type]
            cur.execute(f"SELECT COUNT(*), MIN({spec.time_column}), MAX({spec.time_column}) FROM {spec.table}")  # type: ignore[arg-type]
            n, lo, hi = cur.fetchone()
            src_title = src.title if src else ""
            tm = TableMeta(spec.table, spec.title, used or "none", src_title, int(n), spec.time_grain, lo, hi, note)
            report.tables.append(tm)
            cur.execute("INSERT INTO meta_table VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        [tm.table, tm.title, tm.source, tm.source_title, tm.n_rows, tm.time_grain, tm.min_date, tm.max_date, tm.note])

        for mart, sql in _MARTS.items():
            cur.execute(f"CREATE TABLE {mart} AS {sql}")  # type: ignore[arg-type]
        for table, issue, detail, n in report.issues:
            cur.execute("INSERT INTO meta_issue VALUES (%s, %s, %s, %s)", [table, issue, detail, n])

        # 배지: 원본에 합성 데이터가 하나라도 섞이면 '샘플 데이터'
        sources = {t.source for t in report.tables if t.source != "none"}
        badge_mode = "synthetic" if "synthetic" in sources else ("center" if "center" in sources else "hub")
        cur.execute("SELECT COALESCE(MAX(source), '') FROM ref_route")
        route_src = cur.fetchone()[0]
        build = {
            "data_mode": mode,
            "data_badge": DATA_BADGE[badge_mode],
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "pop_scale": fmt["pop_scale"],
            "route_ref_source": route_src,
        }
        cur.executemany("INSERT INTO meta_build VALUES (%s, %s)", list(build.items()))

        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
        for (name,) in cur.fetchall():
            if name.startswith("_raw_"):
                cur.execute(f"DROP TABLE {_ident(name)}")  # type: ignore[arg-type]
            else:
                cur.execute(f"ANALYZE {_ident(name)}")  # type: ignore[arg-type]
        with con.transaction():  # 다 만든 뒤 한 번에 바꿔치기
            cur.execute(f"DROP SCHEMA IF EXISTS {_ident(schema)} CASCADE")
            cur.execute(f"ALTER SCHEMA {_ident(tmp)} RENAME TO {_ident(schema)}")
    except BaseException:
        try:
            con.execute(f"DROP SCHEMA IF EXISTS {_ident(tmp)} CASCADE")  # type: ignore[arg-type]
        except psycopg.Error:
            pass
        raise
    finally:
        con.close()
    return report


def export_csv(settings: Settings, mode: DataMode | None = None, out_dir: Path | None = None) -> list[tuple[str, int, int]]:
    """데이터 창고의 표준 테이블과 월 집계 테이블을 CSV 로 내보내요. (테이블, 행 수, 바이트) 목록을 돌려줘요.

    허브·센터 자료는 재배포할 수 없어요. 내보낸 파일은 이 PC 에서만 쓰고 저장소에 올리지 않아요.
    """
    mode = mode or settings.data_mode
    wh = Warehouse(settings, mode)
    out = Path(out_dir or settings.export_dir(mode))
    out.mkdir(parents=True, exist_ok=True)
    done: list[tuple[str, int, int]] = []
    try:
        tables = list(wh.meta()) + sorted(_MART_SOURCE)
        with wh._lock:
            assert wh._con is not None
            for table in tables:
                path = out / f"{table}.csv"
                with wh._con.cursor() as cur, path.open("wb") as f:
                    f.write(b"\xef\xbb\xbf")  # 엑셀에서 한글이 깨지지 않게
                    with cur.copy(f"COPY (SELECT * FROM {_ident(table)} ORDER BY 1, 2) TO STDOUT WITH (FORMAT csv, HEADER)") as cp:  # type: ignore[arg-type]
                        for chunk in cp:
                            f.write(chunk)
                    n = cur.rowcount
                done.append((table, int(n), path.stat().st_size))
    finally:
        wh.close()
    return done
