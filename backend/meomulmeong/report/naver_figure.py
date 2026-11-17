"""제안서 지도: 네이버 Static Map 바탕 위에 점·선을 SVG 로 겹쳐 그려요.

제안서는 자바스크립트 없이 열리고 인쇄되는 문서라 움직이는 지도(Dynamic Map)를 넣을 수 없어요.
그래서 바탕 그림만 네이버에서 받고, 읍면동 점·유형 글자·코스 선은 화면과 같은 모양으로 직접 그려요.
바탕 그림의 범위는 우리가 정해서(가운데 + 확대 단계) 점의 자리를 계산해요.

네이버 Static Map 의 level 은 표준 웹 지도(256px 타일, 웹 메르카토르)의 줌보다 1 작아요 (줌 = level + 1).
이미지 배율(scale)과는 상관없어요. 마커를 찍어 확인했어요.
"""

from __future__ import annotations

import base64
import math
from collections import Counter
from html import escape
from typing import Any

from ..maps import MapsUnavailable, NaverMaps
from ..schemas import MapSpec
from .svg import PALETTE, TYPE_COLOR

W, H = 720, 400  # 그림의 논리 크기 (받는 그림은 2배 해상도)
PAD = 40  # 가장자리 여백 (이름표 자리)
OFF_MAP_LAT = 33.8  # 이보다 북쪽(추자면)은 본섬 지도에서 빼요
TEXT_ON = {"A": "#ffffff", "B": "#ffffff", "C": "#ffffff", "D": "#2b211b", "유지": "#ffffff"}
TARGET = "#f7941d"
INK = "#2b211b"


def world(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """위도·경도 → 표준 웹 메르카토르 픽셀 좌표 (줌 zoom, 256px 타일)."""
    s = 256 * 2 ** zoom
    siny = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
    return (lon + 180) / 360 * s, (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * s


def unworld(x: float, y: float, zoom: int) -> tuple[float, float]:
    s = 256 * 2 ** zoom
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / s)))), x / s * 360 - 180


class Frame:
    """점들이 여백 안에 다 들어오는 가장 큰 확대 단계와 가운데. project 로 점의 그림 속 자리를 구해요."""

    def __init__(self, points: list[tuple[float, float]], width: int = W, height: int = H, pad: int = PAD):
        self.width, self.height = width, height
        self.level = 6
        for level in range(13, 5, -1):  # 가장 크게 확대한 단계부터
            xs, ys = zip(*(world(lat, lon, level + 1) for lat, lon in points), strict=True)
            if max(xs) - min(xs) <= width - 2 * pad and max(ys) - min(ys) <= height - 2 * pad:
                self.level = level
                break
        self.zoom = self.level + 1
        xs, ys = zip(*(world(lat, lon, self.zoom) for lat, lon in points), strict=True)
        self.cx, self.cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.center = unworld(self.cx, self.cy, self.zoom)

    def project(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = world(lat, lon, self.zoom)
        return x - self.cx + self.width / 2, y - self.cy + self.height / 2


def _label(x: float, y: float, r: float, text: str, bold: bool = True) -> str:
    return (f'<text x="{x + r + 4:.1f}" y="{y + 4:.1f}" font-size="13" font-weight="{700 if bold else 500}" fill="{INK}" '
            f'stroke="#fff" stroke-width="4" paint-order="stroke" stroke-linejoin="round">{escape(text)}</text>')


def _minutes(s: int) -> str:
    m = max(1, round(s / 60))
    return f"약 {m}분" if m < 60 else f"약 {m // 60}시간" + (f" {m % 60}분" if m % 60 else "")


def map_figure(m: MapSpec, maps: NaverMaps, routes: dict[str, dict[str, Any]] | None = None) -> str:
    """지도 하나를 HTML 로 (네이버 바탕 그림 + SVG). 바탕 그림을 받지 못하면 MapsUnavailable."""
    routes = routes or {}
    important = [p for p in m.points if p.role != "other"]
    # 대상·비교·거점이 추자면이 아니면 본섬에 맞춰요 (멀리 떨어진 추자면 때문에 섬이 작아지지 않게)
    keep = [p for p in m.points if p.lat <= OFF_MAP_LAT] if all(p.lat <= OFF_MAP_LAT for p in important) else list(m.points)
    coords = [(p.lat, p.lon) for p in keep]
    for r in routes.values():
        coords += [tuple(pt) for pt in r.get("path", [])]  # type: ignore[misc]
    if not coords:
        raise MapsUnavailable("그릴 점이 없어요.")
    frame = Frame(coords)
    image = maps.static_base(frame.center[0], frame.center[1], frame.level, W, H)

    inside = {p.key: p for p in keep}
    parts: list[str] = []
    # 코스 선: 도로 경로를 받았으면 실선, 아니면 점선 직선. 앞 코스를 더 굵게 깔아 겹쳐도 색이 모두 보이게 해요
    for k, line in enumerate(m.lines):
        road = routes.get(line.label, {}).get("path")
        pts = road or [(inside[key].lat, inside[key].lon) for key in line.keys if key in inside]
        if len(pts) < 2:
            continue
        xy = " ".join(f"{x:.1f},{y:.1f}" for x, y in (frame.project(lat, lon) for lat, lon in pts))
        width = 4 + 2 * (len(m.lines) - 1 - k) if road else 3
        dash = "" if road else ' stroke-dasharray="6 5"'
        parts.append(f'<polyline points="{xy}" fill="none" stroke="{PALETTE[k % len(PALETTE)]}" stroke-width="{width}" '
                     f'stroke-opacity="0.85" stroke-linecap="round" stroke-linejoin="round"{dash}/>')
    # 거점의 코스 번호 (화면과 같아요)
    course_no: dict[str, list[str]] = {}
    for k, line in enumerate(m.lines):
        if line.keys:
            course_no.setdefault(line.keys[0], []).append(str(k + 1))

    order = {"other": 0, "via": 1, "peer": 2, "hub": 3, "target": 4}
    labels: list[str] = []
    for p in sorted(keep, key=lambda p: order.get(p.role, 0)):
        x, y = frame.project(p.lat, p.lon)
        if not (-10 <= x <= W + 10 and -10 <= y <= H + 10):
            continue
        typed = p.category in TYPE_COLOR
        if p.role == "hub":
            no = "·".join(course_no.get(p.key, []))
            parts.append(f'<rect x="{x - 9:.1f}" y="{y - 9:.1f}" width="18" height="18" rx="4" fill="{INK}" stroke="#fff" stroke-width="2"/>')
            if no:
                parts.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">{escape(no)}</text>')
            else:
                labels.append(_label(x, y, 9, p.name))
            continue
        if p.role == "target":
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="none" stroke="{TARGET}" stroke-width="3"/>')
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{TYPE_COLOR.get(p.category or "", TARGET)}" stroke="#fff" stroke-width="2.5"/>')
            labels.append(_label(x, y, 14, p.name))
        elif p.role == "via":
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#fff" stroke="{INK}" stroke-width="2"/>')
            labels.append(_label(x, y, 6, p.name, bold=False))
        else:
            r = 8 if p.role == "peer" else (6.5 if typed and p.category != "유지" else 5)
            fill = TYPE_COLOR.get(p.category or "", "#b8bec9")
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="#fff" stroke-width="1.8"/>')
            if typed and p.category != "유지" and r >= 6.5:
                parts.append(f'<text x="{x:.1f}" y="{y + 3.3:.1f}" text-anchor="middle" font-size="9" font-weight="700" '
                             f'fill="{TEXT_ON[p.category]}">{escape(p.category or "")}</text>')
            if p.role == "peer":
                labels.append(_label(x, y, r, p.name))
    svg = (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(m.title)}" xmlns="http://www.w3.org/2000/svg">'
           + "".join(parts) + "".join(labels) + "</svg>")
    img = f'<img src="data:image/jpeg;base64,{base64.b64encode(image).decode("ascii")}" alt="{escape(m.title)} 바탕 지도">'

    rows = []
    names = {p.key: p.name for p in m.points}
    for k, line in enumerate(m.lines):
        r = routes.get(line.label)
        if not r or not line.keys:
            continue
        rows.append(f'<li><span class="rkey" style="background:{PALETTE[k % len(PALETTE)]}"></span>{escape(line.label)} · '
                    f'{escape(names.get(line.keys[0], ""))} → {escape(names.get(line.keys[-1], ""))} · '
                    f'도로 {r["distance_m"] / 1000:.1f}km · 자동차 {_minutes(int(r["duration_s"]))}</li>')
    route_list = f'<ul class="rlist">{"".join(rows)}</ul>' if rows else ""
    legend = ""
    if m.legend:  # 유형 범례: 화면처럼 유형 글자와 곳 수를 함께 적어요 (색만으로 구분하지 않게)
        counts = Counter(p.category for p in m.points if p.category)
        legend = '<ul class="tlegend">' + "".join(
            f'<li><span class="tdot" style="background:{TYPE_COLOR.get(code, "#b8bec9")};color:{TEXT_ON.get(code, "#fff")}">'
            f'{"" if code == "유지" else escape(code)}</span>{escape(label)} <span class="cnt">{counts.get(code, 0)}</span></li>'
            for code, label in m.legend.items()) + "</ul>"
    note = "지도 © NAVER Corp."
    target = next((p.name for p in m.points if p.role == "target"), "")
    if any(p.role == "hub" for p in m.points) and m.lines:
        note += f" · 주황 원은 {target}, 검은 네모는 출발 거점이고 숫자는 코스 번호예요."
    if rows:
        note += " 코스의 도로 경로와 시간은 네이버 길찾기의 자동차 기준이라, 버스는 정류장을 들르고 배차를 기다려서 더 걸려요."
    return (f'<figure class="nfig"><div class="nbox">{img}{svg}</div>{legend}{route_list}'
            f'<figcaption class="note">{escape(note)}</figcaption></figure>')


def course_routes(m: MapSpec, maps: NaverMaps) -> dict[str, dict[str, Any]]:
    """코스 선마다 자동차 도로 경로 (받지 못한 선은 빼요. 그 선은 점선 직선으로 그려요)."""
    where = {p.key: (p.lat, p.lon) for p in m.points}
    out: dict[str, dict[str, Any]] = {}
    for line in m.lines:
        pts = [where[k] for k in line.keys if k in where]
        if not 2 <= len(pts) <= 7:
            continue
        try:
            r = maps.driving(pts)
        except (MapsUnavailable, ValueError):
            continue
        if r:
            out[line.label] = r
    return out
