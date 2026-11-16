"""배포 파일 점검: 이미지에 비밀정보나 원자료가 들어가지 않고, 서버가 이 PC 밖으로 열리지 않는지 확인해요."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        pytest.skip(f"{name} 이 없어요")
    return path.read_text(encoding="utf-8")


def test_dockerignore_keeps_secrets_and_raw_data_out_of_the_image():
    lines = [x.strip() for x in _read(".dockerignore").splitlines() if x.strip() and not x.startswith("#")]
    assert lines[0] == "*"  # 모두 빼고, 넣을 것만 골라 담아요
    for must in ("backend/.env", "backend/.env.*", "backend/data/center/", "backend/data/hub/", "backend/data/warehouse/",
                 "backend/data/export/", "backend/outputs/", "**/*.xlsx", "**/*.pdf", "**/*.key", "**/*.pem"):
        assert must in lines, f".dockerignore 에 {must} 가 빠졌어요"
    allowed = {x for x in lines if x.startswith("!")}
    assert allowed == {"!backend/", "!frontend/", "!backend/.env.example"}
    # 다시 넣는 규칙(!)이 빼는 규칙보다 뒤에 와서 비밀 파일을 되살리면 안 돼요
    assert lines.index("backend/.env") > lines.index("!backend/")


def test_dockerfile_runs_as_a_normal_user_and_copies_only_what_it_needs():
    text = _read("Dockerfile")
    assert "USER meomul" in text
    copies = [x.split() for x in text.splitlines() if x.startswith("COPY ")]
    assert copies and all(c[1] != "." for c in copies), "COPY . 처럼 통째로 넣지 않아요"
    assert not any(".env" in " ".join(c) for c in copies)
    assert "ARG " not in text  # 빌드 인자로 비밀값을 넘기지 않아요
    assert 'CMD ["serve", "--prepare", "--host", "0.0.0.0", "--port", "3000"]' in text
    assert "build-data" not in text  # 데이터는 이미지에 굽지 않고, 처음 뜰 때 PostgreSQL 에 넣어요


def test_compose_opens_the_port_on_this_pc_only():
    doc = yaml.safe_load(_read("docker-compose.yml"))
    app = doc["services"]["app"]
    assert app["ports"] == ["127.0.0.1:3000:3000"]  # 로그인 기능이 없어서 밖으로 열지 않아요
    assert app["env_file"] == [{"path": "backend/.env", "required": False}]
    env = app.get("environment", {})
    assert not any("KEY" in k for k in env), "API 키는 compose 파일에 적지 않아요"
    assert "restart" not in app  # PC를 켤 때 저절로 뜨지 않게 해요
    assert app["depends_on"] == {"db": {"condition": "service_healthy"}}  # 데이터 창고가 준비된 뒤에 떠요


def test_compose_database_is_open_on_this_pc_only():
    """데이터 창고(PostgreSQL)도 이 PC 안에서만 열고, 데이터는 이름 붙인 볼륨에 둬요."""
    doc = yaml.safe_load(_read("docker-compose.yml"))
    db = doc["services"]["db"]
    assert db["image"].startswith("postgres:")
    assert db["ports"] == ["127.0.0.1:5434:5432"]
    assert db["volumes"] == ["pgdata:/var/lib/postgresql/data"] and "pgdata" in doc["volumes"]
    assert "restart" not in db
    env = doc["services"]["app"]["environment"]
    assert env["MEOMUL_PG_HOST"] == "db" and str(env["MEOMUL_PG_PORT"]) == "5432"


def test_no_local_llm_setup_is_left():
    """로컬 LLM(Ollama · Qwen3)은 쓰지 않아요. 배포 파일과 환경변수 예시에 그 설정이 남지 않게 해요."""
    assert not (ROOT / "docker-compose.local-llm.yml").exists()
    for name in ("docker-compose.yml", "backend/.env.example"):
        text = _read(name).lower()
        assert "ollama" not in text and "qwen" not in text, f"{name} 에 로컬 LLM 설정이 남았어요"


def test_no_duckdb_setup_is_left():
    """데이터 창고는 PostgreSQL 하나만 써요. 창고 파일을 끼워 넣던 겹침 파일과 DuckDB 의존성이 남지 않게 해요."""
    assert not (ROOT / "docker-compose.hub.yml").exists()
    for name in ("backend/pyproject.toml", "backend/requirements.txt", "backend/requirements.lock"):
        assert "duckdb" not in _read(name).lower(), f"{name} 에 DuckDB 가 남았어요"
