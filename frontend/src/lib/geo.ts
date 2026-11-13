/** 지도 그리기 도구: 경위도 → 화면 좌표, 본섬 윤곽, 겹친 점 벌리기. */

/**
 * 제주 본섬 해안선의 대략 윤곽 (경도, 위도). 서쪽 끝에서 시계 방향.
 * 위치를 가늠하기 위한 밑그림이에요. 행정 경계나 측량 자료가 아니에요.
 */
export const JEJU_OUTLINE: ReadonlyArray<readonly [number, number]> = [
  [126.163, 33.3], [126.172, 33.338], [126.2, 33.372], [126.236, 33.394], [126.262, 33.414], [126.296, 33.444],
  [126.33, 33.466], [126.382, 33.486], [126.438, 33.498], [126.488, 33.514], [126.522, 33.521], [126.568, 33.527],
  [126.61, 33.537], [126.642, 33.547], [126.68, 33.554], [126.73, 33.56], [126.78, 33.562], [126.83, 33.557],
  [126.878, 33.538], [126.914, 33.512], [126.93, 33.482], [126.942, 33.46], [126.928, 33.43], [126.902, 33.396],
  [126.872, 33.356], [126.842, 33.326], [126.792, 33.3], [126.722, 33.274], [126.662, 33.258], [126.602, 33.24],
  [126.56, 33.236], [126.51, 33.23], [126.46, 33.233], [126.41, 33.238], [126.36, 33.233], [126.322, 33.228],
  [126.292, 33.198], [126.254, 33.206], [126.214, 33.232], [126.18, 33.264],
]

/** 본섬과 우도를 담는 범위. 추자면은 훨씬 북쪽이라 따로 표시해요. */
const BOUNDS = { lon0: 126.14, lon1: 126.985, lat0: 33.185, lat1: 33.575 }
const COS_LAT = Math.cos((33.38 * Math.PI) / 180)
/** 이 위도보다 북쪽(추자면)은 본도 지도 밖이에요. */
export const OFF_MAP_LAT = 33.8

export interface XY {
  x: number
  y: number
}

export interface Projection {
  project: (lon: number, lat: number) => XY
  outline: string
  width: number
  height: number
}

/** 가로세로 비율을 지키면서 지도 영역 가운데에 본섬을 맞춰요. */
export function makeProjection(width: number, height: number, pad = 16): Projection {
  const spanX = (BOUNDS.lon1 - BOUNDS.lon0) * COS_LAT
  const spanY = BOUNDS.lat1 - BOUNDS.lat0
  const k = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY)
  const ox = (width - spanX * k) / 2
  const oy = (height - spanY * k) / 2
  const project = (lon: number, lat: number): XY => ({
    x: ox + (lon - BOUNDS.lon0) * COS_LAT * k,
    y: oy + (BOUNDS.lat1 - lat) * k,
  })
  const outline = smoothClosedPath(JEJU_OUTLINE.map(([lon, lat]) => project(lon, lat)))
  return { project, outline, width, height }
}

/** 점들을 부드럽게 잇는 닫힌 경로 (Catmull-Rom 을 3차 베지어로). */
export function smoothClosedPath(pts: XY[]): string {
  const n = pts.length
  if (n < 3) return ''
  const at = (i: number): XY => pts[(i + n) % n]
  let d = `M${at(0).x.toFixed(1)},${at(0).y.toFixed(1)}`
  for (let i = 0; i < n; i++) {
    const p0 = at(i - 1)
    const p1 = at(i)
    const p2 = at(i + 1)
    const p3 = at(i + 2)
    const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 }
    const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 }
    d += `C${c1.x.toFixed(1)},${c1.y.toFixed(1)} ${c2.x.toFixed(1)},${c2.y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`
  }
  return `${d}Z`
}

export interface Dot extends XY {
  r: number
  /** true 면 제자리를 지켜요 (대상 읍면동, 거점). */
  fixed?: boolean
}

/**
 * 겹친 점을 조금씩 벌려요. 도심의 동은 좌표가 몰려 있어서 그대로 찍으면 서로 가려져요.
 * 원래 자리에서 멀어지지 않게 약하게 당기고, 같은 입력에는 항상 같은 결과를 내요.
 */
export function declutter(dots: Dot[], gap = 1.5, iterations = 80): XY[] {
  const pos = dots.map((d) => ({ x: d.x, y: d.y }))
  for (let it = 0; it < iterations; it++) {
    let moved = false
    for (let i = 0; i < dots.length; i++) {
      for (let j = i + 1; j < dots.length; j++) {
        const min = dots[i].r + dots[j].r + gap
        let dx = pos[j].x - pos[i].x
        let dy = pos[j].y - pos[i].y
        let dist = Math.hypot(dx, dy)
        if (dist >= min) continue
        if (dist < 1e-6) {
          // 완전히 같은 자리면 순서로 방향을 정해요 (난수 없이)
          const angle = ((i * 37 + j * 17) % 360) * (Math.PI / 180)
          dx = Math.cos(angle)
          dy = Math.sin(angle)
          dist = 1
        }
        const push = (min - dist) / 2
        const ux = dx / dist
        const uy = dy / dist
        const wi = dots[i].fixed ? 0 : dots[j].fixed ? 2 : 1
        const wj = dots[j].fixed ? 0 : dots[i].fixed ? 2 : 1
        pos[i].x -= ux * push * wi
        pos[i].y -= uy * push * wi
        pos[j].x += ux * push * wj
        pos[j].y += uy * push * wj
        moved = true
      }
    }
    for (let i = 0; i < dots.length; i++) {
      if (dots[i].fixed) continue
      pos[i].x += (dots[i].x - pos[i].x) * 0.04
      pos[i].y += (dots[i].y - pos[i].y) * 0.04
    }
    if (!moved) break
  }
  return pos
}
