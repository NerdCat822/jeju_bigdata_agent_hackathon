"""네이버 지도 (선택 기능): 실제로 부르지 않고 가짜 전송 계층과 가짜 지도로 시험해요."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from meomulmeong.api import create_app
from meomulmeong.maps import MapsUnavailable, NaverMaps
from meomulmeong.report import builder
from meomulmeong.report.naver_figure import Frame
from meomulmeong.settings import Settings


def transport(log: list[httpx.Request], answers: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handle(req: httpx.Request) -> httpx.Response:
        log.append(req)
        for path, resp in answers.items():
            if req.url.path.endswith(path):
                return resp
        return httpx.Response(404, json={"error": "no fake"})
    return httpx.MockTransport(handle)


REVERSE = {"status": {"code": 0, "name": "ok"}, "results": [{"name": "admcode", "code": {"id": "5013025900"}}]}
GEOCODE = {"status": "OK", "addresses": [{"roadAddress": "제주특별자치도 서귀포시 성산읍 일출로 284-12",
                                          "jibunAddress": "제주특별자치도 서귀포시 성산읍 성산리 114", "x": "126.9363", "y": "33.4621"}]}
DRIVE = {"code": 0, "route": {"trafast": [{"summary": {"distance": 45627, "duration": 3317221},
                                          "path": [[126.49 + i * 0.001, 33.50 - i * 0.0001] for i in range(1000)]}]}}


def test_client_reads_naver_answers_and_remembers_them():
    log: list[httpx.Request] = []
    m = NaverMaps("id", "secret", transport=transport(log, {
        "/gc": httpx.Response(200, json=REVERSE),
        "/geocode": httpx.Response(200, json=GEOCODE),
        "/driving": httpx.Response(200, json=DRIVE),
        "/raster": httpx.Response(200, content=b"\x89PNG fake", headers={"content-type": "image/png"}),
    }))
    assert m.admcode(33.45891, 126.94082) == "5013025900"
    assert m.admcode(33.45889, 126.94078) == "5013025900"  # 약 10m 안의 같은 자리는 다시 부르지 않아요
    assert len(log) == 1 and log[0].headers["x-ncp-apigw-api-key-id"] == "id" and log[0].headers["x-ncp-apigw-api-key"] == "secret"
    assert m.geocode("성산읍 일출로 284-12") == [{"road": "제주특별자치도 서귀포시 성산읍 일출로 284-12",
                                              "jibun": "제주특별자치도 서귀포시 성산읍 성산리 114", "lat": 33.4621, "lon": 126.9363}]
    r = m.driving([(33.507, 126.493), (33.45, 126.7), (33.437, 126.918)])
    assert r["distance_m"] == 45627 and r["duration_s"] == 3317
    assert len(r["path"]) == 400 and r["path"][0] == (33.50, 126.49) and r["path"][-1] == pytest.approx((33.4001, 127.489))
    drive = next(q for q in log if q.url.path.endswith("/driving"))
    assert drive.url.params["start"] == "126.493,33.507" and drive.url.params["waypoints"] == "126.7,33.45"
    assert m.static_map([{"lat": 33.437, "lon": 126.918}]).startswith(b"\x89PNG")


def test_client_fails_softly():
    m = NaverMaps("id", "bad", transport=transport([], {"/gc": httpx.Response(401, json={"error": {"message": "Authentication Failed"}})}))
    with pytest.raises(MapsUnavailable, match="401"):
        m.admcode(33.45, 126.94)

    def offline(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no internet", request=req)
    with pytest.raises(MapsUnavailable, match="연결하지 못했어요"):
        NaverMaps("id", "s", transport=httpx.MockTransport(offline)).geocode("제주시 연동")
    with pytest.raises(MapsUnavailable, match="이미지가 아닌"):
        NaverMaps("id", "s", transport=transport([], {"/raster": httpx.Response(200, json={"error": 1})})).static_map(
            [{"lat": 33.4, "lon": 126.5}])


def test_client_stops_at_the_hourly_cap():
    """공개 주소라 누구나 부를 수 있어요. 한 시간 상한을 넘으면 네이버를 부르지 않아요."""
    log: list[httpx.Request] = []
    m = NaverMaps("id", "s", transport=transport(log, {"/gc": httpx.Response(200, json=REVERSE)}), caps={"reverse": 2})
    m.admcode(33.41, 126.51)
    m.admcode(33.42, 126.52)
    with pytest.raises(MapsUnavailable, match="상한"):
        m.admcode(33.43, 126.53)
    assert len(log) == 2


def test_maps_are_off_without_keys_or_when_switched_off():
    assert NaverMaps.from_settings(Settings(naver_maps=True, naver_map_client_id="", naver_map_client_secret="")) is None
    assert NaverMaps.from_settings(Settings(naver_maps=False, naver_map_client_id="a", naver_map_client_secret="b")) is None
    on = NaverMaps.from_settings(Settings(naver_maps=True, naver_map_client_id="a", naver_map_client_secret="b"))
    assert on is not None and on is NaverMaps.from_settings(Settings(naver_maps=True, naver_map_client_id="a", naver_map_client_secret="b"))


# --------------------------------------------------------------------------- 웹 API
class FakeMaps:
    client_id = "fake-key"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple] = []

    def _check(self) -> None:
        if self.fail:
            raise MapsUnavailable("오프라인")

    def admcode(self, lat: float, lon: float) -> str | None:
        self._check()
        self.calls.append(("adm", lat, lon))
        return None if lon > 126.99 else "5013025900"  # 동쪽 바다는 읍면동이 없어요

    def geocode(self, query: str) -> list[dict]:
        self._check()
        self.calls.append(("geo", query))
        seoul = {"road": "서울특별시 구로구 중앙로 105", "jibun": "", "lat": 37.49, "lon": 126.85}
        if "중앙로" in query:  # 다른 지역에도 있는 주소: 시를 붙여야 제주가 나와요
            jeju = {"road": "제주특별자치도 서귀포시 중앙로 105", "jibun": "", "lat": 33.25, "lon": 126.56}
            return [jeju] if "서귀포시" in query else [seoul]
        return [{"road": "제주특별자치도 서귀포시 성산읍 일출로 284-12", "jibun": "", "lat": 33.4621, "lon": 126.9363}, seoul]

    def driving(self, points: list[tuple[float, float]]) -> dict:
        self._check()
        self.calls.append(("drive", tuple(points)))
        return {"distance_m": 45627, "duration_s": 3317, "path": [points[0], points[-1]]}


def test_map_api_without_keys(svc):
    client = TestClient(create_app(service=svc))  # 테스트는 지도를 꺼 둬요 (conftest)
    assert client.get("/api/bootstrap").json()["naver_map_key_id"] is None
    for path in ("/api/map/locate?lat=33.45&lon=126.94", "/api/map/search?q=성산읍", "/api/map/route?keys=HUB_CJU,50130259"):
        r = client.get(path)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "maps_off", path


def test_map_api_with_keys(svc):
    fake = FakeMaps()
    c = TestClient(create_app(service=svc, maps=fake))
    assert c.get("/api/bootstrap").json()["naver_map_key_id"] == "fake-key"  # Secret 은 내보내지 않아요
    assert "secret" not in c.get("/api/bootstrap").text.lower()

    assert c.get("/api/map/locate", params={"lat": 33.4589, "lon": 126.9408}).json() == {"emd_cd": "50130259", "emd_nm": "성산읍"}
    assert c.get("/api/map/locate", params={"lat": 33.45, "lon": 127.05}).status_code == 404  # 바다
    assert c.get("/api/map/locate", params={"lat": 37.56, "lon": 126.97}).status_code == 400  # 제주 밖은 묻지 않아요

    hits = c.get("/api/map/search", params={"q": "성산읍 일출로 284-12"}).json()
    assert [(h["emd_nm"], h["address"]) for h in hits] == [("성산읍", "제주특별자치도 서귀포시 성산읍 일출로 284-12")]
    assert [c for c in fake.calls if c[0] == "geo"] == [("geo", "성산읍 일출로 284-12")]  # 제주 안에서 찾았으면 한 번만
    again = c.get("/api/map/search", params={"q": "중앙로 105"}).json()  # 제주가 안 나오면 시를 붙여 다시 찾아요
    assert [h["address"] for h in again] == ["제주특별자치도 서귀포시 중앙로 105"]
    assert ("geo", "제주특별자치도 제주시 중앙로 105") in fake.calls and ("geo", "제주특별자치도 서귀포시 중앙로 105") in fake.calls

    hub = next(iter(svc.agent.refs.hubs.values()))
    route = c.get("/api/map/route", params={"keys": f"{hub.hub_id},50130259"}).json()
    assert route["distance_m"] == 45627 and route["path"][0] == [hub.lat, hub.lon]
    assert c.get("/api/map/route", params={"keys": "50130259"}).status_code == 400
    bad = c.get("/api/map/route", params={"keys": f"{hub.hub_id},NOPE"})
    assert bad.status_code == 400 and "NOPE" in bad.json()["detail"]["message"]

    down = TestClient(create_app(service=svc, maps=FakeMaps(fail=True)))
    r = down.get("/api/map/locate", params={"lat": 33.4589, "lon": 126.9408})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "maps_unavailable"


def test_openapi_lists_the_map_routes(svc):
    doc = TestClient(create_app(service=svc)).get("/openapi.json").json()
    assert {"/api/map/locate", "/api/map/search", "/api/map/route"} <= set(doc["paths"])
    assert json.dumps(doc).count("naver_map_key_id") >= 1


# --------------------------------------------------------------------------- 최종 제안서
class FakeStatic:
    def __init__(self, fail_base: bool = False):
        self.markers: list[dict] = []
        self.bases: list[tuple] = []
        self.fail_base = fail_base

    def static_map(self, markers: list[dict]) -> bytes:
        self.markers = markers
        return b"\x89PNG fake map"

    def static_base(self, lat: float, lon: float, level: int, width: int = 720, height: int = 400) -> bytes:
        if self.fail_base:
            raise MapsUnavailable("오프라인")
        self.bases.append((lat, lon, level))
        return b"\xff\xd8 fake jpeg"

    def driving(self, points: list[tuple[float, float]]) -> dict:
        return {"distance_m": 17300, "duration_s": 1320, "path": [points[0], points[-1]]}


def test_report_gets_a_location_map_when_maps_are_on(agent, monkeypatch):
    fake = FakeStatic()
    monkeypatch.setattr(builder.NaverMaps, "from_settings", classmethod(lambda cls, s: fake))
    result = agent.ask("성산읍 처음부터 끝까지 최종 제안서", agent.session())
    html = open(result.report_path, encoding="utf-8").read()
    assert 'class="locmap"' in html and "data:image/png;base64," in html and "주황 핀: 성산읍" in html
    assert fake.markers[0]["kind"] == "pin" and all(m["kind"] == "dot" for m in fake.markers[1:])
    # 유형 지도와 코스 지도도 네이버 바탕 지도 위에 점·선을 SVG 로 겹쳐 그려요
    assert html.count('class="nfig"') == 2 and html.count("data:image/jpeg;base64,") == 2 and len(fake.bases) == 2
    assert "도로 17.3km · 자동차 약 22분" in html and "자동차 기준" in html
    assert 'class="tlegend"' in html and "정착 성장형" in html  # 유형 범례도 그대로 있어요
    assert "<script" not in html  # 그림은 문서 안에 넣어요. 자바스크립트는 여전히 없어요


def test_report_maps_fall_back_to_plain_svg_when_the_base_map_fails(agent, monkeypatch):
    monkeypatch.setattr(builder.NaverMaps, "from_settings", classmethod(lambda cls, s: FakeStatic(fail_base=True)))
    html = open(agent.ask("성산읍 처음부터 끝까지 최종 제안서", agent.session()).report_path, encoding="utf-8").read()
    assert 'class="nfig"' not in html and "<svg" in html  # 예전처럼 SVG 점 지도로 그려요


def test_map_frame_fits_points_and_matches_naver_levels():
    """그림 범위: 점이 모두 여백 안에 들어오는 가장 큰 단계. 네이버 level 은 표준 줌보다 1 작아요."""
    pts = [(33.5070, 126.4930), (33.4370, 126.9180), (33.2490, 126.5620)]
    f = Frame(pts, width=720, height=400, pad=40)
    assert f.zoom == f.level + 1
    xy = [f.project(*p) for p in pts]
    assert all(40 - 1e-6 <= x <= 680 + 1e-6 and 40 - 1e-6 <= y <= 360 + 1e-6 for x, y in xy)
    bigger = Frame(pts, width=720, height=400, pad=40)
    bigger.zoom += 1  # 한 단계 더 확대하면 넘쳐요
    bigger.cx, bigger.cy = (v * 2 for v in (f.cx, f.cy))
    assert any(not (40 <= x <= 680 and 40 <= y <= 360) for x, y in (bigger.project(*p) for p in pts))
    lat, lon = f.center
    assert f.project(lat, lon) == pytest.approx((360, 200), abs=1e-6)


def test_report_without_maps_has_no_location_map(agent):
    result = agent.ask("성산읍 처음부터 끝까지 최종 제안서", agent.session())
    assert 'class="locmap"' not in open(result.report_path, encoding="utf-8").read()
