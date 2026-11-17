"""네이버 클라우드 Maps API (선택). 지도를 보여 주는 데에만 쓰고, 분석 숫자와 검증에는 쓰지 않아요.

| API               | 쓰는 곳                                              |
|-------------------|------------------------------------------------------|
| Reverse Geocoding | 지도의 한 점 → 행정동 코드 → 우리 읍면동 (첫 화면)    |
| Geocoding         | 주소 → 좌표 → 읍면동 (첫 화면 '주소로 찾기')          |
| Directions 5      | 코스 선을 실제 도로로, 자동차 기준 거리·시간 (3단계)  |
| Static Map        | 최종 제안서의 위치 지도 이미지                        |
| Dynamic Map       | 화면의 지도 (브라우저가 Client ID 로 직접 불러요)     |

Client Secret 은 이 서버 안에서만 써요. 인터넷이 없거나 키가 없으면 None 을 돌려주고, 화면과 제안서는 기본 지도로 그려요.
누구나 부를 수 있는 공개 주소라서, API 마다 한 시간 호출 상한을 두고 같은 요청은 기억해 둔 답을 써요.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Any

import httpx

from .settings import Settings

BASE = "https://maps.apigw.ntruss.com"

# 제주도 범위 (추자도 · 마라도 포함). 이 밖의 좌표는 묻지 않아요.
JEJU_LAT = (33.0, 34.1)
JEJU_LON = (126.0, 127.1)

# 한 시간에 실제로 부르는 횟수 상한 (기억해 둔 답은 세지 않아요)
HOURLY_CAP = {"reverse": 600, "geocode": 300, "driving": 120, "static": 120}


class MapsUnavailable(RuntimeError):
    """키가 없거나, 인터넷이 없거나, 상한을 넘었거나, 네이버가 오류를 돌려줬어요."""


def in_jeju(lat: float, lon: float) -> bool:
    return JEJU_LAT[0] <= lat <= JEJU_LAT[1] and JEJU_LON[0] <= lon <= JEJU_LON[1]


class _Memo:
    """작은 LRU 기억 장소. 같은 질문은 네이버를 다시 부르지 않아요."""

    def __init__(self, size: int = 2048):
        self.size = size
        self._d: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
        return None

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)


class NaverMaps:
    def __init__(self, client_id: str, client_secret: str, timeout: float = 4.0,
                 transport: httpx.BaseTransport | None = None, caps: dict[str, int] | None = None):
        self.client_id = client_id
        self._client = httpx.Client(base_url=BASE, timeout=timeout, transport=transport, headers={
            "x-ncp-apigw-api-key-id": client_id, "x-ncp-apigw-api-key": client_secret})
        self._memo = _Memo()
        self._images = _Memo(32)  # 지도 그림은 크니까 조금만 기억해요
        self._caps = {**HOURLY_CAP, **(caps or {})}
        self._calls: dict[str, deque[float]] = {k: deque() for k in self._caps}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> NaverMaps | None:
        """키가 있고 꺼 두지 않았으면 만들어요. 같은 키면 서버 안에서 하나만 써요 (기억해 둔 답을 함께 써요)."""
        if not (settings.naver_maps and settings.naver_map_client_id and settings.naver_map_client_secret):
            return None
        key = (settings.naver_map_client_id, settings.naver_map_client_secret)
        with _SHARED_LOCK:
            if key not in _SHARED:
                _SHARED[key] = cls(*key)
            return _SHARED[key]

    # ------------------------------------------------------------------ 공통
    def _spend(self, kind: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._calls[kind]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self._caps[kind]:
                raise MapsUnavailable(f"지도 {kind} 호출이 한 시간 상한({self._caps[kind]}회)에 닿았어요.")
            q.append(now)

    def _get(self, kind: str, path: str, params: dict[str, Any] | list[tuple[str, str]]) -> httpx.Response:
        self._spend(kind)
        try:
            r = self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise MapsUnavailable(f"네이버 지도에 연결하지 못했어요: {type(e).__name__}") from e
        if r.status_code != 200:
            raise MapsUnavailable(f"네이버 지도가 HTTP {r.status_code}을 돌려줬어요.")
        return r

    # ------------------------------------------------------------------ Reverse Geocoding
    def admcode(self, lat: float, lon: float) -> str | None:
        """좌표가 속한 행정동 코드 10자리 (앞 8자리가 우리 읍면동 코드예요). 바다 위처럼 없으면 None."""
        lat, lon = round(lat, 4), round(lon, 4)  # 약 10m. 같은 동네를 여러 번 누르면 기억해 둔 답을 써요
        key = ("adm", lat, lon)
        if (hit := self._memo.get(key)) is not None:
            return hit or None
        d = self._get("reverse", "/map-reversegeocode/v2/gc",
                      {"coords": f"{lon},{lat}", "orders": "admcode", "output": "json"}).json()
        code = ""
        if d.get("status", {}).get("code") == 0:
            code = next((r["code"]["id"] for r in d.get("results", []) if r.get("name") == "admcode"), "")
        self._memo.put(key, code)
        return code or None

    # ------------------------------------------------------------------ Geocoding
    def geocode(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """도로명·지번 주소 → [{road, jibun, lat, lon}]. 장소 이름(예: '성산일출봉')은 찾지 못해요."""
        q = " ".join(query.split())[:80]
        key = ("geo", q)
        if (hit := self._memo.get(key)) is not None:
            return hit
        d = self._get("geocode", "/map-geocode/v2/geocode", {"query": q, "count": str(limit)}).json()
        out = [{"road": a.get("roadAddress") or "", "jibun": a.get("jibunAddress") or "",
                "lat": float(a["y"]), "lon": float(a["x"])} for a in d.get("addresses", [])[:limit]]
        self._memo.put(key, out)
        return out

    # ------------------------------------------------------------------ Directions 5
    def driving(self, points: list[tuple[float, float]], max_path: int = 400) -> dict[str, Any] | None:
        """(lat, lon) 순서대로 지나는 자동차 경로. {distance_m, duration_s, path: [(lat, lon), …]}. 길이 없으면 None.

        버스 노선의 실제 경로가 아니라 같은 곳들을 잇는 자동차 도로예요. 화면에서도 그렇게 밝혀요.
        """
        if not 2 <= len(points) <= 7:
            raise ValueError("경로의 점은 2~7개여야 해요 (경유지는 5개까지).")
        pts = [(round(lat, 5), round(lon, 5)) for lat, lon in points]
        key = ("drive", tuple(pts))
        if (hit := self._memo.get(key)) is not None:
            return hit or None
        params = {"start": f"{pts[0][1]},{pts[0][0]}", "goal": f"{pts[-1][1]},{pts[-1][0]}", "option": "trafast"}
        if len(pts) > 2:
            params["waypoints"] = "|".join(f"{lon},{lat}" for lat, lon in pts[1:-1])
        d = self._get("driving", "/map-direction/v1/driving", params).json()
        route = (d.get("route") or {}).get("trafast") or []
        if d.get("code") != 0 or not route:
            self._memo.put(key, {})
            return None
        r = route[0]
        path = [(float(lat), float(lon)) for lon, lat in r.get("path", [])]
        if len(path) > max_path:  # 화면에 그리기 충분할 만큼만 남겨요 (끝점은 꼭 남겨요)
            step = len(path) / (max_path - 1)
            path = [path[int(i * step)] for i in range(max_path - 1)] + [path[-1]]
        out = {"distance_m": int(r["summary"]["distance"]), "duration_s": int(round(r["summary"]["duration"] / 1000)),
               "path": path}
        self._memo.put(key, out)
        return out

    # ------------------------------------------------------------------ Static Map
    def static_base(self, lat: float, lon: float, level: int, width: int = 720, height: int = 400) -> bytes:
        """마커 없는 바탕 지도 JPEG (가운데·확대 단계를 우리가 정해요). 제안서에서 점과 선은 SVG 로 겹쳐 그려요.

        level 은 네이버 단계예요 (표준 웹 지도 줌 = level + 1). 그림은 2배 해상도로 받아요.
        """
        params = [("w", str(width)), ("h", str(height)), ("scale", "2"), ("format", "jpg"),
                  ("center", f"{round(lon, 6)},{round(lat, 6)}"), ("level", str(level))]
        key = ("base", tuple(params))
        if (hit := self._images.get(key)) is not None:
            return hit
        r = self._get("static", "/map-static/v2/raster", params)
        if not r.headers.get("content-type", "").startswith("image/"):
            raise MapsUnavailable("네이버 지도가 이미지가 아닌 답을 돌려줬어요.")
        self._images.put(key, r.content)
        return r.content

    def static_map(self, markers: list[dict[str, Any]], width: int = 720, height: int = 360) -> bytes:
        """마커가 모두 보이게 맞춘 지도 PNG. markers: [{lat, lon, color: '0xF08A12', label: '1', kind: 'pin'|'dot'}]."""
        params: list[tuple[str, str]] = [("w", str(width)), ("h", str(height)), ("scale", "2"), ("format", "png")]
        if len(markers) == 1:  # 마커가 하나면 범위를 정할 수 없어 그 자리를 가운데에 두고 넓게 보여 줘요
            params += [("center", f"{markers[0]['lon']},{markers[0]['lat']}"), ("level", "10")]
        for m in markers:
            kind = "d" if m.get("kind", "pin") == "pin" else "n"
            spec = f"type:{kind}|size:{'mid' if kind == 'd' else 'small'}|color:{m.get('color', '0xF08A12')}|pos:{m['lon']} {m['lat']}"
            if m.get("label") and kind == "n":
                spec += f"|label:{m['label']}"
            params.append(("markers", spec))
        key = ("static", tuple(params))
        if (hit := self._images.get(key)) is not None:
            return hit
        r = self._get("static", "/map-static/v2/raster", params)
        if not r.headers.get("content-type", "").startswith("image/"):
            raise MapsUnavailable("네이버 지도가 이미지가 아닌 답을 돌려줬어요.")
        self._images.put(key, r.content)
        return r.content


_SHARED: dict[tuple[str, str], NaverMaps] = {}
_SHARED_LOCK = threading.Lock()
