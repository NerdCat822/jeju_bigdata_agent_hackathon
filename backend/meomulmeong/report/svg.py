"""제안서용 정적 차트·지도 (인라인 SVG). 자바스크립트 없이 열리고 인쇄돼요."""

from __future__ import annotations

from html import escape

from ..schemas import ChartSpec, MapSpec

PALETTE = ["#2f7de1", "#f7941d", "#3aa76d", "#d6453d", "#8e6bbf", "#6b7280"]
TYPE_COLOR = {"A": "#3aa76d", "B": "#2f7de1", "C": "#e4572e", "D": "#f2b134", "유지": "#b8bec9"}
W, H = 680, 300
ML, MR, MT, MB = 62, 16, 14, 46


def _fmt(v: float, kind: str) -> str:
    if kind == "pct":
        return f"{v * 100:.0f}%" if abs(v * 100 - round(v * 100)) < 1e-6 else f"{v * 100:.1f}%"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.1f}억"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.0f}만"
    return f"{v:,.0f}"


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """보기 좋은 눈금 (1·2·2.5·5 × 10^k 간격)."""
    import math

    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.ceil(lo / step - 1e-9) * step
    out, v = [], start
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def chart_svg(c: ChartSpec) -> str:
    vals = [v for s in c.series for v in s.y if v is not None]
    if not vals or not c.x:
        return ""
    lo, hi = min(vals), max(vals)
    if c.kind != "line" or c.y_format == "pct":
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = (lo - pad if lo < 0 or c.kind == "line" else lo), hi + pad
    pw, ph = W - ML - MR, H - MT - MB
    n = len(c.x)

    def y(v: float) -> float:
        return MT + ph * (1 - (v - lo) / (hi - lo))

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(c.title)}" class="chart">']
    for t in _ticks(lo, hi):
        out.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#e6e8ee"/>')
        out.append(f'<text x="{ML - 8}" y="{y(t) + 4:.1f}" text-anchor="end" class="tick">{_fmt(t, c.y_format)}</text>')
    step = max(1, n // 8)
    if c.kind == "line":
        xs = [ML + pw * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
        for k, s in enumerate(c.series):
            pts = " ".join(f"{xs[i]:.1f},{y(v):.1f}" for i, v in enumerate(s.y) if v is not None)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{PALETTE[k % 6]}" stroke-width="2.5"/>')
    else:
        band = pw / n
        bw = band * 0.7 / max(len(c.series), 1)
        xs = [ML + band * (i + 0.5) for i in range(n)]
        zero = y(0.0) if lo <= 0 <= hi else y(lo)
        for k, s in enumerate(c.series):
            for i, v in enumerate(s.y):
                if v is None:
                    continue
                x0 = xs[i] - band * 0.35 + bw * k
                top, bot = min(y(v), zero), max(y(v), zero)
                out.append(f'<rect x="{x0:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(bot - top, 0.5):.1f}" fill="{PALETTE[k % 6]}"/>')
        step = 1 if n <= 10 else step
    for i in range(0, n, step):
        out.append(f'<text x="{xs[i]:.1f}" y="{H - MB + 16}" text-anchor="middle" class="tick">{escape(str(c.x[i]))}</text>')
    lx = ML
    for k, s in enumerate(c.series):
        out.append(f'<rect x="{lx}" y="{H - 14}" width="10" height="10" fill="{PALETTE[k % 6]}"/>')
        out.append(f'<text x="{lx + 14}" y="{H - 5}" class="tick">{escape(s.name)}</text>')
        lx += 24 + 12 * len(s.name)
    out.append("</svg>")
    return "".join(out)


def map_svg(m: MapSpec) -> str:
    pts = [p for p in m.points if not (p.lat > 33.8)]  # 추자면은 멀어서 본도 지도에서 빼고 따로 적어요
    if not pts:
        return ""
    w, h, pad_x, pad_y = 680, 340, 70, 36
    lon0, lon1 = min(p.lon for p in pts), max(p.lon for p in pts)
    lat0, lat1 = min(p.lat for p in pts), max(p.lat for p in pts)

    def xy(lat: float, lon: float) -> tuple[float, float]:
        x = pad_x + (w - 2 * pad_x) * (lon - lon0) / ((lon1 - lon0) or 1)
        yy = pad_y + (h - 2 * pad_y - 16) * (1 - (lat - lat0) / ((lat1 - lat0) or 1))
        return x, yy

    pos = {p.key: xy(p.lat, p.lon) for p in pts}
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(m.title)}" class="chart">']
    for k, line in enumerate(m.lines):
        coords = [pos[key] for key in line.keys if key in pos]
        if len(coords) >= 2:
            d = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            out.append(f'<polyline points="{d}" fill="none" stroke="{PALETTE[k % 6]}" stroke-width="2.5" stroke-dasharray="6 4"/>')
    labels: list[tuple[float, float, float, float]] = []  # 이미 놓은 이름표 (x0, y0, x1, y1)
    for p in sorted(pts, key=lambda p: p.role in ("target", "hub")):
        x, y = pos[p.key]
        color = TYPE_COLOR.get(p.category or "", "#9aa3b2")
        if p.role == "hub":
            out.append(f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" fill="#22262e"/>')
        else:
            r = 9 if p.role == "target" else (7 if p.role in ("peer", "via") else 5)
            stroke = ' stroke="#22262e" stroke-width="2.5"' if p.role == "target" else (' stroke="#22262e" stroke-width="1.2"' if p.role == "peer" else "")
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"{stroke}/>')
        if p.role in ("target", "peer", "hub", "via"):
            tw = 11.5 * len(p.name)
            left = x + 11 + tw > w - 4  # 오른쪽 끝이면 이름을 점의 왼쪽에
            lx = x - 11 - tw if left else x + 11
            # 다른 이름표와 겹치면 위·아래로 옮겨요
            for dy in (4, -12, 20, -26, 36):
                box = (lx, y + dy - 12, lx + tw, y + dy + 3)
                if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in labels):
                    break
            labels.append(box)
            weight = ' font-weight="700"' if p.role == "target" else ""
            out.append(f'<text x="{lx:.1f}" y="{box[3] - 3:.1f}" class="tick lbl"{weight}>{escape(p.name)}</text>')
    lx = pad_x - 40
    for key, label in m.legend.items():
        out.append(f'<circle cx="{lx + 5}" cy="{h - 10}" r="5" fill="{TYPE_COLOR.get(key, "#9aa3b2")}"/>')
        out.append(f'<text x="{lx + 14}" y="{h - 6}" class="tick">{escape(label)}</text>')
        lx += 30 + 12 * len(label)
    out.append("</svg>")
    return "".join(out)
