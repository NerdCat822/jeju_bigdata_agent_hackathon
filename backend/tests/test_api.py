"""웹 API: React 화면이 부르는 경로를 시험해요 (확인 카드 → 실행 → 연계 → 제안서, 스트리밍, 모드 전환)."""

import json
import threading

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from test_llm import FakeLLM

from meomulmeong import progress
from meomulmeong.agent.orchestrator import Agent
from meomulmeong.api import create_app
from meomulmeong.llm.base import ExplainOut
from meomulmeong.service import AgentService
from meomulmeong.settings import Settings


@pytest.fixture()
def client(svc):
    return TestClient(create_app(service=svc))


def events(text: str) -> list[tuple[str, dict]]:
    """SSE 본문을 (이벤트 이름, 데이터) 목록으로 풀어요."""
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


# --------------------------------------------------------------------------- 첫 화면
def test_health_and_bootstrap(client):
    assert client.get("/api/health").json() == {"ok": True, "ready": True, "message": None}
    b = client.get("/api/bootstrap").json()
    assert set(b) == {"status", "places", "suggested", "options", "naver_map_key_id"}
    assert b["naver_map_key_id"] is None  # 테스트는 지도를 꺼 둬요
    assert len(b["places"]) == 43 and {"emd_cd", "emd_nm", "lat", "lon", "area_type"} <= set(b["places"][0])
    assert b["status"]["data_badge"] == "샘플 데이터" and b["status"]["llm_mode"] == "template"
    assert [s["stage"] for s in b["suggested"]] == [1, 2, 3] and all(s["questions"] for s in b["suggested"])
    opt = b["options"]
    assert len(opt["themes"]) == 6 and len(opt["hubs"]) == 6 and [t["code"] for t in opt["types"]] == ["A", "B", "C", "D", "유지"]
    assert opt["elasticity_grid"] == [0.5, 1.0, 1.5]
    modes = b["status"]["modes"]
    assert [m["mode"] for m in modes["data"] if m["current"]] == ["synthetic"]
    assert [m["mode"] for m in modes["llm"] if m["current"]] == ["template"]


def test_status_never_leaks_secrets(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("MEOMUL_HUB_PROJECT_KEY", "hub-secret-key")
    text = client.get("/api/status").text + client.get("/api/bootstrap").text
    assert "sk-test-not-a-real-key" not in text and "hub-secret-key" not in text
    assert next(m for m in client.get("/api/status").json()["modes"]["llm"] if m["mode"] == "anthropic")["available"] is True


def test_llm_mode_label_is_a_readable_model_name(client):
    """LLM 모드 이름은 모델 ID 대신 읽기 좋은 이름으로 보여 줘요."""
    from meomulmeong import fmt

    assert fmt.model_name("claude-opus-5-5") == "Claude Opus 5.5"
    assert fmt.model_name("claude-fable-5-2") == "Claude Fable 5.2"
    assert fmt.model_name("claude-3-5-sonnet-20241022") == "Claude 3.5 Sonnet"  # 끝의 날짜는 빼요
    assert fmt.model_name("claude-sonnet-4-20250514") == "Claude Sonnet 4"
    model = client.app.state.meomul.settings.anthropic_model
    labels = {m["mode"]: m["label"] for m in client.get("/api/status").json()["modes"]["llm"]}
    assert labels == {"template": "기본 (AI 없이)", "anthropic": fmt.model_name(model)}
    assert "클라우드" not in labels["anthropic"] and model not in labels["anthropic"]



def test_modes_can_be_locked_for_a_shared_deployment(svc):
    """여러 사람이 같은 주소를 쓰는 배포본: 모드를 바꾸는 API 를 막고, 화면이 읽기 전용으로 보이게 알려요."""
    locked = TestClient(create_app(service=svc, settings=svc.settings.model_copy(update={"lock_modes": True})))
    before = locked.get("/api/status").json()
    assert before["modes"]["locked"] is True
    r = locked.post("/api/modes", json={"llm_mode": "anthropic"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "modes_locked"
    assert locked.get("/api/status").json()["llm_mode"] == before["llm_mode"]  # 아무것도 바뀌지 않았어요


def test_api_docs_can_be_turned_off_for_a_public_address(svc, client):
    assert client.get("/docs").status_code == 200 and client.get("/openapi.json").status_code == 200
    closed = TestClient(create_app(service=svc, settings=svc.settings.model_copy(update={"api_docs": False})))
    for path in ("/docs", "/redoc", "/openapi.json"):
        r = closed.get(path)
        assert r.status_code == 404 or "openapi" not in r.text.lower(), path  # 화면(SPA)이 있으면 index.html 로 가요
    assert closed.get("/api/health").status_code == 200


def test_stream_says_when_it_waits_for_another_analysis(client):
    """분석은 한 번에 하나씩 돌아요. 앞 사람의 분석이 돌고 있으면 기다린다고 먼저 알려요."""
    query = client.post("/api/understand", json={"question": "성산읍 청년 인구 진단"}).json()["card"]["query"]
    state = client.app.state.meomul
    assert state.run_lock.acquire(timeout=5)  # 앞 사람의 분석이 도는 중인 것처럼
    released = threading.Timer(0.5, state.run_lock.release)
    released.start()
    try:
        r = client.post("/api/run/stream", json={"query": query, "session_id": None})
    finally:
        released.join()
    ev = events(r.text)
    assert ev[0][0] == "progress" and ev[0][1]["kind"] == "start" and ev[0][1]["run"]  # 실행 번호 (멈추기에 써요)
    assert ev[1] == ("progress", {"kind": "queue"})
    assert ev[-1][0] == "done"


def test_a_waiting_run_can_be_cancelled(client):
    """'멈추기': 앞 사람을 기다리던 실행은 차례를 기다리지 않고 멈추고, 잠금을 건드리지 않아요."""
    query = client.post("/api/understand", json={"question": "성산읍 청년 인구 진단"}).json()["card"]["query"]
    state = client.app.state.meomul
    assert state.run_lock.acquire(timeout=5)  # 앞 사람의 분석이 도는 중
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(r=client.post("/api/run/stream", json={"query": query, "session_id": None})))
    try:
        t.start()
        for _ in range(100):  # 실행이 등록될 때까지
            with state.runs_lock:
                runs = list(state.runs)
            if runs:
                break
            threading.Event().wait(0.05)
        assert len(runs) == 1
        assert client.post(f"/api/runs/{runs[0]}/cancel").json() == {"ok": True}
        t.join(timeout=10)
        ev = events(out["r"].text)
        assert ev[0][1]["run"] == runs[0] and ev[-1] == ("error", {"code": "cancelled", "message": "분석을 멈췄어요."})
        assert state.run_lock.locked()  # 앞 사람의 잠금은 그대로예요
    finally:
        state.run_lock.release()
    assert client.post(f"/api/runs/{runs[0]}/cancel").status_code == 404  # 끝난 실행은 없어요


# --------------------------------------------------------------------------- 확인 카드 → 실행
def test_understand_then_run_and_follow_up(client):
    r = client.post("/api/understand", json={"question": "성산읍 청년 인구 왜 줄었어?"}).json()
    sid, card = r["session_id"], r["card"]
    assert card["runnable"] and {"label": "장소", "value": "성산읍"} in card["chips"]
    a = client.post("/api/run", json={"query": card["query"], "session_id": sid}).json()
    assert a["session_id"] == sid and a["answer"]["ok"] and a["answer"]["verification"]["passed"]
    assert a["answer"]["stage"] == 1 and a["answer"]["charts"] and a["answer"]["evidence"][0]["sql"]
    # 같은 세션의 후속 질문은 장소를 이어받아요
    follow = client.post("/api/ask", json={"question": "거기 30대만?", "session_id": sid}).json()
    assert follow["kind"] == "answer" and follow["answer"]["query"]["place_name"] == "성산읍"
    assert follow["answer"]["query"]["ages"] == [30]
    # 세션이 없으면 새 대화라 장소를 모르고, 읍면동을 골라 달라고 해요
    alone = client.post("/api/ask", json={"question": "거기 30대만?"}).json()
    assert alone["session_id"] != sid and alone["answer"]["query"]["place_name"] is None


def test_run_fixes_up_an_edited_query(client, svc):
    card = client.post("/api/understand", json={"question": "성산읍 청년 인구 진단"}).json()["card"]
    q = dict(card["query"])
    q["place_name"] = "구좌읍"  # 화면은 이름만 바꿔 보내요. 코드는 서버가 다시 찾아요
    q["ages"] = [30, 999]
    q["last_n_months"] = 500
    a = client.post("/api/run", json={"query": q}).json()["answer"]
    assert a["ok"] and a["query"]["place_name"] == "구좌읍" and a["query"]["place_key"] == svc.agent.refs.find_emd("구좌읍").emd_cd
    assert a["query"]["ages"] == [30] and a["query"]["last_n_months"] is None
    # 참조표에 없는 장소 코드는 버리고, 읍면동을 골라 달라고 답해요 (SQL로 흘러가지 않아요)
    q2 = dict(card["query"], place_key="x' OR 1=1 --", place_name=None)
    r = client.post("/api/run", json={"query": q2})
    assert r.status_code == 200 and r.json()["answer"]["ok"] is False and "읍면동" in r.json()["answer"]["message"]
    q3 = dict(card["query"], intent="shift", theme="음식점", hub_id="없는거점", elasticity=99)
    a3 = client.post("/api/run", json={"query": q3}).json()["answer"]
    assert a3["ok"] and a3["stage"] == 2 and a3["query"]["theme"] == "식음료" and a3["query"]["hub_id"] is None
    assert a3["query"]["elasticity"] is None


def test_confirm_rebuilds_the_card_without_running(client):
    card = client.post("/api/understand", json={"question": "성산읍 청년 인구 진단"}).json()["card"]
    q = dict(card["query"], place_name="노형동", ages=[30])
    c2 = client.post("/api/confirm", json={"query": q}).json()["card"]
    assert {"label": "장소", "value": "노형동"} in c2["chips"] and {"label": "연령", "value": "30대"} in c2["chips"]
    assert c2["runnable"] and c2["query"]["place_kind"] == "emd"
    c3 = client.post("/api/confirm", json={"query": dict(card["query"], place_name="없는동네", place_key=None)}).json()["card"]
    assert not c3["runnable"] and any("읍면동" in w for w in c3["warnings"])


# --------------------------------------------------------------------------- 연계 실행 · 제안서
def test_ask_runs_the_chain_and_serves_the_report(client):
    r = client.post("/api/ask", json={"question": "성산읍 처음부터 끝까지 최종 제안서"}).json()
    assert r["kind"] == "chain" and [a["stage"] for a in r["chain"]["answers"]] == [1, 2, 3]
    assert r["report_url"].startswith("/api/reports/") and r["answer"] is None
    page = client.get(r["report_url"])
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "성산읍" in page.text and "3단계" in page.text
    assert "attachment" in client.get(r["report_url"], params={"download": "true"}).headers["content-disposition"]
    assert "attachment" not in page.headers.get("content-disposition", "")


def test_chain_endpoint(client):
    r = client.post("/api/chain", json={"place": "구좌읍"}).json()
    assert r["chain"]["place_name"] == "구좌읍" and len(r["chain"]["answers"]) == 3 and r["report_url"] is None
    assert all(a["verification"]["passed"] for a in r["chain"]["answers"])
    bad = client.post("/api/chain", json={"place": "없는동네"})
    assert bad.status_code == 404 and bad.json()["detail"]["code"] == "unknown_place"


def test_report_from_a_session(client):
    sid = client.post("/api/sessions").json()["session_id"]
    empty = client.post("/api/reports", json={"session_id": sid})
    assert empty.status_code == 400 and empty.json()["detail"]["code"] == "nothing_to_report"
    client.post("/api/ask", json={"question": "아라동 청년 인구 진단", "session_id": sid})
    made = client.post("/api/reports", json={"session_id": sid}).json()  # 빠진 Stage 2·3 은 먼저 실행해요
    assert "아라동" in made["filename"] and client.get(made["url"]).status_code == 200
    assert client.post("/api/reports", json={"session_id": sid, "place": "없는동네"}).status_code == 404


@pytest.mark.parametrize("name", ["없는파일.html", "..%2F..%2Fconfig%2Fsettings.yaml", "report.txt", "%2e%2e%2fREADME.md"])
def test_report_download_stays_inside_the_reports_folder(client, name):
    r = client.get(f"/api/reports/{name}")
    assert r.status_code == 404 and "analysis:" not in r.text


# --------------------------------------------------------------------------- 스트리밍
def test_chain_stream_sends_progress_and_one_answer_per_stage(client):
    r = client.post("/api/chain/stream", json={"place": "성산읍", "with_report": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    assert ev[0][0] == "progress" and ev[0][1]["kind"] == "start" and ev[-1][0] == "done"
    stages = [d["stage"] for e, d in ev if e == "progress" and d["kind"] == "stage"]
    answers = [d["stage"] for e, d in ev if e == "answer"]
    assert stages == [1, 2, 3] and answers == [1, 2, 3]
    tools = [d for e, d in ev if e == "progress" and d["kind"] == "tool"]
    assert {"s1_trend", "s2_shift", "s3_forecast"} <= {t["tool"] for t in tools}
    assert all(t["label"] and "seconds" in t for t in tools)
    names = [e if e != "progress" else f"progress:{d['kind']}" for e, d in ev]
    assert names.index("progress:stage") < names.index("answer") < len(names) - 1  # 단계 시작 → 답 → … → 끝
    done = ev[-1][1]
    assert done["kind"] == "chain" and done["place_name"] == "성산읍" and done["report_url"].startswith("/api/reports/")


def test_ask_and_run_stream_send_a_single_answer(client):
    ev = events(client.post("/api/ask/stream", json={"question": "성산읍에 누가 올까?"}).text)
    assert [e for e, _ in ev].count("answer") == 1 and ev[-1][1]["kind"] == "answer"
    answer = next(d for e, d in ev if e == "answer")
    assert answer["stage"] == 2 and answer["suggestions"] and ev[-1][1]["session_id"]
    card = client.post("/api/understand", json={"question": "국내선 10% 감편 시 12월 개별여행 입도객"}).json()["card"]
    ev2 = events(client.post("/api/run/stream", json={"query": card["query"]}).text)
    assert [e for e, _ in ev2][-2:] == ["answer", "done"] and next(d for e, d in ev2 if e == "answer")["stage"] == 3


def test_stream_reports_errors_as_events(client):
    ev = events(client.post("/api/chain/stream", json={"place": "없는동네"}).text)
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "unknown_place"


def test_stream_shows_llm_attempts(svc):
    """LLM 모드에서는 해설을 쓰는 중이라는 알림과 검증 결과가 흘러가요."""
    llm = FakeLLM({"explain": [ExplainOut(explanation="관광객이 늘었기 때문에 청년이 줄었어요."),
                               ExplainOut(explanation="성산읍의 20·30대 거주인구는 줄었고 방문자는 늘었어요.")]})
    fake = AgentService(svc.settings, svc.config, Agent(svc.agent.ctx, llm))
    ev = events(TestClient(create_app(service=fake)).post("/api/ask/stream", json={"question": "성산읍 청년 인구 진단"}).text)
    llm_events = [d for e, d in ev if e == "progress" and d["kind"] in ("llm", "llm_result")]
    assert [(d["kind"], d["attempt"]) for d in llm_events] == [("llm", 1), ("llm_result", 1), ("llm", 2), ("llm_result", 2)]
    assert llm_events[0]["label"] == "쉬운 해설 쓰기" and [d["ok"] for d in llm_events if d["kind"] == "llm_result"] == [False, True]
    answer = next(d for e, d in ev if e == "answer")
    assert answer["explained_by"] == "llm" and answer["verification"]["retries"] == 1


def test_progress_listener_is_scoped_and_never_breaks_the_run():
    seen = []
    progress.emit("tool", tool="x")  # 듣는 쪽이 없으면 아무 일도 없어요
    with progress.listen(seen.append):
        progress.emit("tool", tool="s1_trend", ok=True)
    progress.emit("tool", tool="y")
    assert seen == [{"kind": "tool", "tool": "s1_trend", "ok": True}]

    def broken(_ev):
        raise RuntimeError("화면 연결이 끊겼어요")

    with progress.listen(broken):
        progress.emit("tool", tool="z")  # 듣는 쪽 오류는 삼켜요


# --------------------------------------------------------------------------- 모드 · 세션 · 입력 검사
def test_modes_switch_keeps_the_conversation_for_llm_changes(client):
    sid = client.post("/api/ask", json={"question": "성산읍 청년 인구 진단"}).json()["session_id"]
    st = client.post("/api/modes", json={"llm_mode": "template"})
    assert st.status_code == 200 and st.json()["llm_mode"] == "template"
    follow = client.post("/api/ask", json={"question": "거기 30대만?", "session_id": sid}).json()
    assert follow["answer"]["query"]["place_name"] == "성산읍"  # LLM 모드만 바꾸면 대화 맥락은 이어져요
    missing = client.post("/api/modes", json={"data_mode": "hub"})
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "warehouse_missing"
    assert client.get("/api/status").json()["data_mode"] == "synthetic"  # 실패하면 그대로 둬요
    assert client.post("/api/modes", json={"llm_mode": "gpt"}).status_code == 422


def test_cloud_consent_is_stored_on_the_session(client, svc):
    sid = client.post("/api/sessions").json()["session_id"]
    assert svc.agent.session(sid).cloud_consent is False
    assert client.post(f"/api/sessions/{sid}/cloud-consent", json={"consent": True}).json() == {"session_id": sid, "consent": True}
    assert svc.agent.session(sid).cloud_consent is True
    assert client.post("/api/sessions/bad id!/cloud-consent", json={"consent": True}).status_code == 422


@pytest.mark.parametrize("path,body", [
    ("/api/understand", {"question": ""}),
    ("/api/ask", {"question": "가" * 501}),
    ("/api/ask", {"question": "성산읍", "session_id": "../../etc"}),
    ("/api/run", {"query": {"intent": "없는의도"}}),
    ("/api/chain", {}),
])
def test_bad_input_is_rejected(client, path, body):
    assert client.post(path, json=body).status_code == 422


def test_missing_warehouse_is_reported_not_crashed(tmp_path, home):
    import shutil

    shutil.copytree(home / "config", tmp_path / "config")
    shutil.copytree(home / "data" / "ref", tmp_path / "data" / "ref")
    c = TestClient(create_app(settings=make_settings(tmp_path, data_mode="synthetic", llm_mode="template")))
    h = c.get("/api/health").json()
    assert h["ok"] and h["ready"] is False and "build-data" in h["message"]
    r = c.post("/api/ask", json={"question": "성산읍 청년 인구 진단"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "warehouse_missing"


# --------------------------------------------------------------------------- 개발 서버 허용 · React 빌드 결과물
def test_cors_allows_only_the_dev_servers(client):
    pre = {"Access-Control-Request-Method": "POST"}
    ok = client.options("/api/ask", headers={"Origin": "http://localhost:5173", **pre})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    no = client.options("/api/ask", headers={"Origin": "http://evil.example", **pre})
    assert "access-control-allow-origin" not in no.headers


def test_built_frontend_is_served_from_the_same_address(svc, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>머물멍</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('머물멍')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("비밀", encoding="utf-8")
    c = TestClient(create_app(service=svc, web_dist=dist))
    assert "머물멍" in c.get("/").text and c.get("/assets/app.js").text.startswith("console.log")
    assert "<title>머물멍</title>" in c.get("/stage/2").text  # 화면 쪽 경로는 index.html 로 보내요
    assert c.get("/api/health").json()["ready"] is True  # API 는 그대로
    assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").json()["detail"]["code"] == "not_found"
    for path in ("/../secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"):
        assert "비밀" not in c.get(path).text


def test_without_a_build_the_root_explains_what_to_do(client):
    r = client.get("/").json()
    assert r["docs"] == "/docs" and "frontend" in r


def test_openapi_describes_the_answer_shape(client):
    """React 쪽에서 openapi.json 으로 타입을 만들 수 있게, 답의 모양이 문서에 들어 있어야 해요."""
    doc = client.get("/openapi.json").json()
    names = set(doc["components"]["schemas"])
    assert {"Answer", "ConfirmCard", "ChartSpec", "MapSpec", "EvidenceTable", "ChainResult", "BootstrapOut", "StatusOut"} <= names
    assert {"ParsedQuery-Input", "ParsedQuery-Output"} <= names  # 보낼 때는 고칠 값만, 받을 때는 모든 값이 있어요
    answer = doc["components"]["schemas"]["Answer"]
    assert {"charts", "maps", "evidence", "suggestions", "limits", "next_questions"} <= set(answer["required"])  # 목록은 항상 와요
    assert doc["paths"]["/api/run"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/AnswerOut")


def test_empty_env_values_fall_back_to_defaults(monkeypatch, tmp_path):
    """.env.example 을 그대로 복사하면 빈 값이 많아요. 빈 값이 기본값을 지우면 개발 서버에서 API를 못 불러요."""
    monkeypatch.setenv("MEOMUL_CORS_ORIGINS", "")
    monkeypatch.setenv("MEOMUL_WEB_DIST", "")
    monkeypatch.setenv("MEOMUL_API_PORT", "")
    s = Settings(home=tmp_path)
    assert "http://localhost:5173" in s.cors_origins and s.web_dist is None and s.api_port == 8501
    monkeypatch.setenv("MEOMUL_CORS_ORIGINS", "http://localhost:4000")
    monkeypatch.setenv("MEOMUL_API_PORT", "9000")
    s2 = Settings(home=tmp_path)
    assert s2.cors_origins == "http://localhost:4000" and s2.api_port == 9000


def test_frontend_openapi_snapshot_is_current(client):
    """화면 쪽 타입은 frontend/src/api/openapi.json 에서 만들어요. 백엔드 모델을 바꾸면 `npm run gen:api` 로 다시 만들어야 해요."""
    from pathlib import Path

    snap = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json"
    if not snap.exists():
        pytest.skip("frontend 폴더가 없어요")
    assert json.loads(snap.read_text(encoding="utf-8")) == client.get("/openapi.json").json(), (
        "API 명세가 바뀌었어요. frontend 폴더에서 `npm run gen:api` 를 실행해 타입을 다시 만들어 주세요.")
