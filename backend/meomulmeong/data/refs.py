"""참조표 로딩과 장소 표준화.

에이전트는 여기에 없는 읍면동·지구·거점·노선을 출력하지 않아요 (검증기의 '참조 대조').
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def _norm(text: str) -> str:
    return "".join(str(text).split())


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or "").split("|") if v.strip())


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


@dataclass(frozen=True)
class Emd:
    emd_cd: str
    emd_nm: str
    city: str
    emd_type: str  # 읍 / 면 / 동
    area_type: str  # 도심 / 읍면
    region7: str
    lat: float
    lon: float
    aliases: tuple[str, ...]

    @property
    def full_nm(self) -> str:
        return f"{self.city} {self.emd_nm}"


@dataclass(frozen=True)
class Zone:
    zone: str
    zone_type: str
    aliases: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class Hub:
    hub_id: str
    hub_nm: str
    hub_type: str
    emd_cd: str
    lat: float
    lon: float
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Route:
    route_no: str
    route_nm: str
    route_type: str
    origin: str
    destination: str
    variants: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class PlaceMatch:
    kind: Literal["emd", "zone", "city", "hub"]
    key: str  # emd_cd / 지구명 / 시군구명 / hub_id
    name: str
    matched: str
    pos: int
    ambiguous: bool = False


# '연동'은 "연동되다" 같은 일반 단어에도 나와서, 뒤 글자를 보고 걸러요.
_FALSE_FOLLOWERS = {"연동": "되하해시된한할형성"}

_CITY_ALIASES = {"제주시": "제주시", "서귀포시": "서귀포시", "서귀포": "서귀포시"}


class Refs:
    """data/ref 의 CSV를 읽어 조회·표준화 기능을 제공해요."""

    def __init__(self, ref_dir: Path):
        self.ref_dir = Path(ref_dir)
        self.emds: dict[str, Emd] = {}
        for r in _read_csv(self.ref_dir / "ref_emd.csv"):
            self.emds[r["emd_cd"]] = Emd(
                emd_cd=r["emd_cd"], emd_nm=r["emd_nm"], city=r["city"], emd_type=r["emd_type"],
                area_type=r["area_type"], region7=r["region7"], lat=float(r["lat"]), lon=float(r["lon"]),
                aliases=_split(r.get("aliases")),
            )
        self.zones: dict[str, Zone] = {
            r["zone"]: Zone(r["zone"], r["zone_type"], _split(r.get("aliases")), r.get("note", ""))
            for r in _read_csv(self.ref_dir / "ref_zone.csv")
        }
        self._zone_of_emd: dict[str, str] = {}
        for r in _read_csv(self.ref_dir / "ref_card_zone.csv"):
            if r["emd_cd"]:
                self._zone_of_emd[r["emd_cd"]] = r["zone"]
        self.theme_map: dict[str, str] = {r["raw"]: r["theme"] for r in _read_csv(self.ref_dir / "ref_theme.csv")}
        self.themes: list[str] = []
        for t in self.theme_map.values():
            if t != "전체" and t not in self.themes:
                self.themes.append(t)
        self.theme_alias: dict[str, str] = {
            r["alias"]: r["theme"] for r in _read_csv(self.ref_dir / "ref_theme_alias.csv")
        }
        self.hubs: dict[str, Hub] = {
            r["hub_id"]: Hub(r["hub_id"], r["hub_nm"], r["hub_type"], r["emd_cd"], float(r["lat"]), float(r["lon"]),
                             _split(r.get("aliases")))
            for r in _read_csv(self.ref_dir / "ref_hub.csv")
        }
        self.routes: dict[str, Route] = {
            r["route_no"]: Route(r["route_no"], r["route_nm"], r["route_type"], r["origin"], r["destination"],
                                 _split(r.get("variants")), r.get("source", ""))
            for r in _read_csv(self.ref_dir / "ref_route.csv")
        }
        seq: dict[str, list[tuple[int, str]]] = {}
        for r in _read_csv(self.ref_dir / "ref_route_emd.csv"):
            seq.setdefault(r["route_no"], []).append((int(r["seq"]), r["emd_cd"]))
        self._route_emds: dict[str, list[str]] = {k: [e for _, e in sorted(v)] for k, v in seq.items()}
        self.purposes: dict[str, str] = {
            r["purpose"]: r["purpose_group"] for r in _read_csv(self.ref_dir / "ref_purpose.csv")
        }
        self.nationalities: dict[str, tuple[str, ...]] = {
            r["nationality"]: _split(r.get("aliases")) for r in _read_csv(self.ref_dir / "ref_nationality.csv")
        }
        self._build_alias_index()

    # ------------------------------------------------------------------ 색인
    def _build_alias_index(self) -> None:
        emd_alias: dict[str, list[str]] = {}
        for e in self.emds.values():
            for name in (e.emd_nm, *e.aliases):
                emd_alias.setdefault(_norm(name), [])
                if e.emd_cd not in emd_alias[_norm(name)]:
                    emd_alias[_norm(name)].append(e.emd_cd)
        self._emd_alias = emd_alias
        cands: list[tuple[str, str, str]] = []  # (정규화 별칭, 종류, 키)
        for alias in emd_alias:
            cands.append((alias, "emd", alias))
        for z in self.zones.values():
            for name in (z.zone, *z.aliases):
                cands.append((_norm(name), "zone", z.zone))
        for h in self.hubs.values():
            for name in (h.hub_nm, *h.aliases):
                cands.append((_norm(name), "hub", h.hub_id))
        for alias, city in _CITY_ALIASES.items():
            cands.append((alias, "city", city))
        # 긴 별칭부터 맞춰야 '성산읍'이 '성산'보다 먼저 잡혀요.
        self._cands = sorted(set(cands), key=lambda c: (-len(c[0]), c[0]))

    # ------------------------------------------------------------------ 조회
    def emd(self, emd_cd: str) -> Emd:
        return self.emds[emd_cd]

    def emd_name(self, emd_cd: str) -> str:
        e = self.emds.get(emd_cd)
        return e.emd_nm if e else emd_cd

    def find_emd(self, name: str, city: str | None = None) -> Emd | None:
        """읍면동 이름(행정동·법정동·별칭)으로 행정동을 찾아요. 여러 곳이면 city 로 고르고, 못 고르면 None."""
        codes = self._emd_alias.get(_norm(name), [])
        if city:
            codes = [c for c in codes if self.emds[c].city == city] or codes
        return self.emds[codes[0]] if len(codes) == 1 else None

    def zone_of(self, emd_cd: str) -> str | None:
        """읍면동이 직접 속한 카드 지구 (없으면 None)."""
        return self._zone_of_emd.get(emd_cd)

    def card_zones_for(self, emd_cd: str) -> list[tuple[str, bool]]:
        """요일별 카드 분석에 쓸 지구 목록: (지구, 직접 대응 여부).

        직접 속한 지구가 없으면 관광지 지구 두 곳을 참고 지구로 돌려줘요.
        """
        direct = self.zone_of(emd_cd)
        if direct:
            return [(direct, True)]
        return [(z.zone, False) for z in self.zones.values() if z.zone_type == "관광지"]

    def zone_emds(self, zone: str) -> list[str]:
        return [e for e, z in self._zone_of_emd.items() if z == zone]

    def theme_of(self, raw: str) -> str:
        return self.theme_map.get(str(raw).strip(), "기타")

    def find_theme(self, text: str) -> str | None:
        t = _norm(text)
        for alias in sorted(self.theme_alias, key=len, reverse=True):
            if alias in t:
                return self.theme_alias[alias]
        return None

    def route_emds(self, route_no: str) -> list[str]:
        return list(self._route_emds.get(route_no, []))

    def routes_through(self, emd_cd: str) -> list[str]:
        return [r for r, emds in self._route_emds.items() if emd_cd in emds]

    @property
    def routes_are_sample(self) -> bool:
        return any(r.source == "sample" for r in self.routes.values())

    def find_nationality(self, text: str) -> str | None:
        t = _norm(text)
        for nat, aliases in self.nationalities.items():
            for name in (nat, *aliases):
                if _norm(name) in t:
                    return nat
        return None

    # ------------------------------------------------------------------ 장소 표준화
    def find_places(self, text: str) -> list[PlaceMatch]:
        """문장에서 읍면동·지구·시군구·거점 표현을 찾아요 (긴 표현 우선, 겹치지 않게)."""
        t = _norm(text)
        taken = [False] * len(t)
        found: list[PlaceMatch] = []
        cities = [c for a, c in _CITY_ALIASES.items() if a in t]
        for alias, kind, key in self._cands:
            if not alias:
                continue
            start = 0
            while True:
                i = t.find(alias, start)
                if i < 0:
                    break
                start = i + 1
                j = i + len(alias)
                if any(taken[i:j]):
                    continue
                bad = _FALSE_FOLLOWERS.get(alias)
                if bad and j < len(t) and t[j] in bad:
                    continue
                if kind == "emd":
                    codes = self._emd_alias[key]
                    ambiguous = len(codes) > 1
                    if ambiguous and cities:
                        narrowed = [c for c in codes if self.emds[c].city in cities]
                        if len(narrowed) == 1:
                            codes, ambiguous = narrowed, False
                    e = self.emds[codes[0]]
                    found.append(PlaceMatch("emd", e.emd_cd, e.emd_nm, alias, i, ambiguous))
                elif kind == "zone":
                    found.append(PlaceMatch("zone", key, key, alias, i))
                elif kind == "hub":
                    found.append(PlaceMatch("hub", key, self.hubs[key].hub_nm, alias, i))
                else:
                    found.append(PlaceMatch("city", key, key, alias, i))
                for k in range(i, j):
                    taken[k] = True
        return sorted(found, key=lambda m: m.pos)

    def resolve_place(self, text: str) -> PlaceMatch | None:
        """문장에서 분석 대상 장소 하나를 골라요: 읍면동 > 지구 > 시군구 순."""
        matches = self.find_places(text)
        for kind in ("emd", "zone", "city"):
            for m in matches:
                if m.kind == kind:
                    return m
        return None
