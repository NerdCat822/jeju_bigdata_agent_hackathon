import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { OFF_MAP_LAT, declutter, makeProjection } from '../../lib/geo'
import type { XY } from '../../lib/geo'
import { useWidth } from '../../lib/useSize'
import { TYPE_COLORS, TYPE_INK } from './palette'
import { Tooltip } from './Tooltip'

export interface MapDot {
  key: string
  name: string
  lat: number
  lon: number
  /** 활력 유형(A~D, 유지) 또는 거점 종류. */
  category?: string | null
  role: 'target' | 'peer' | 'hub' | 'via' | 'other'
  /** 툴팁에 보여 줄 한 줄 (예: "C 방문 의존형 · 20·30대 거주 -5.5%"). */
  detail?: string
  /** 이름표를 항상 보여 줄지. 대상·비교 읍면동·거점은 기본으로 보여 줘요. */
  labeled?: boolean
}

interface Props {
  dots: MapDot[]
  lines?: { label: string; keys: string[] }[]
  selectedKey?: string | null
  onSelect?: (dot: MapDot) => void
  label: string
}

interface Placed extends MapDot, XY {
  r: number
}

const radius = (d: MapDot, typed: boolean): number =>
  d.role === 'target' ? 10 : d.role === 'peer' || d.role === 'via' ? 8 : d.role === 'hub' ? 7 : !typed ? 5.5 : d.category !== '유지' ? 6 : 4.5

const CHAR_W = 11.5
type Box = [number, number, number, number]
const hits = (a: Box, b: Box): boolean => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]

/** 이름표 자리: 오른쪽 → 왼쪽 → 위 → 아래 순서로, 다른 이름표나 강조 점과 겹치지 않는 첫 자리. */
function placeLabels(items: Placed[], width: number, height: number): Map<string, { x: number; y: number; anchor: 'start' | 'end' | 'middle' }> {
  const out = new Map<string, { x: number; y: number; anchor: 'start' | 'end' | 'middle' }>()
  const taken: Box[] = items.map((d) => [d.x - d.r, d.y - d.r, d.x + d.r, d.y + d.r])
  const order = (d: Placed): number => (d.role === 'target' ? 0 : d.role === 'hub' ? 1 : d.role === 'other' ? 3 : 2)
  for (const d of [...items].filter((x) => x.labeled).sort((a, b) => order(a) - order(b))) {
    const w = d.name.length * CHAR_W + 4
    const g = d.r + 5
    const options: { x: number; y: number; anchor: 'start' | 'end' | 'middle'; box: Box }[] = [
      { x: d.x + g, y: d.y + 4, anchor: 'start', box: [d.x + g, d.y - 8, d.x + g + w, d.y + 8] },
      { x: d.x - g, y: d.y + 4, anchor: 'end', box: [d.x - g - w, d.y - 8, d.x - g, d.y + 8] },
      { x: d.x, y: d.y - g - 2, anchor: 'middle', box: [d.x - w / 2, d.y - g - 14, d.x + w / 2, d.y - g + 2] },
      { x: d.x, y: d.y + g + 12, anchor: 'middle', box: [d.x - w / 2, d.y + g, d.x + w / 2, d.y + g + 16] },
    ]
    const fit = options.find((o) => o.box[0] >= 2 && o.box[2] <= width - 2 && o.box[1] >= 2 && o.box[3] <= height - 2 && !taken.some((t) => hits(o.box, t)))
    const use = fit ?? options[0]
    taken.push(use.box)
    out.set(d.key, { x: use.x, y: use.y, anchor: use.anchor })
  }
  return out
}

/**
 * 제주 지도. 본섬의 대략 윤곽 위에 읍면동과 거점을 점으로 찍어요.
 * 좌표가 몰린 도심의 동은 서로 가리지 않게 조금 벌려서 보여 줘요.
 */
export function JejuMap({ dots, lines = [], selectedKey = null, onSelect, label }: Props): ReactNode {
  const [ref, width] = useWidth<HTMLDivElement>(560)
  const [hover, setHover] = useState<string | null>(null)
  const height = Math.round(Math.max(210, Math.min(360, width * 0.52)))
  const typed = dots.some((d) => d.category && d.category in TYPE_COLORS)

  const { proj, placed, labels } = useMemo(() => {
    const proj = makeProjection(width, height, 18)
    const raw = dots.map((d) => {
      // 추자면은 본도에서 북쪽으로 멀리 떨어져 있어 왼쪽 위에 따로 놓아요.
      const xy = d.lat > OFF_MAP_LAT ? { x: 30, y: 26 } : proj.project(d.lon, d.lat)
      return { ...d, ...xy, r: radius(d, typed) }
    })
    const moved = declutter(raw.map((d) => ({ x: d.x, y: d.y, r: d.r, fixed: d.role === 'target' || d.lat > OFF_MAP_LAT })))
    const placed: Placed[] = raw.map((d, i) => ({ ...d, ...moved[i], labeled: d.labeled ?? d.role !== 'other' }))
    return { proj, placed, labels: placeLabels(placed, width, height) }
  }, [dots, width, height, typed])

  const byKey = useMemo(() => new Map(placed.map((d) => [d.key, d])), [placed])
  const order = (d: Placed): number => (d.role === 'target' ? 3 : d.role === 'hub' ? 2 : d.role === 'other' ? 0 : 1)
  const drawn = [...placed].sort((a, b) => order(a) - order(b))
  const tip = hover ? byKey.get(hover) : null
  const hasOffMap = placed.some((d) => d.lat > OFF_MAP_LAT)
  const udo = proj.project(126.953, 33.506)

  return (
    <div ref={ref} className="viz-plot jeju-map">
      <svg width={width} height={height} role="group" aria-label={label}>
        <path className="map-island" d={proj.outline} />
        <ellipse className="map-island" cx={udo.x} cy={udo.y} rx={6} ry={8} />
        {hasOffMap && (
          <text className="map-offnote" x={46} y={46}>
            추자면은 북쪽 약 50km
          </text>
        )}
        {lines.map((ln) => {
          const pts = ln.keys.map((k) => byKey.get(k)).filter((p): p is Placed => !!p)
          return pts.length >= 2 ? (
            <polyline key={ln.label} className="map-course" points={pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}>
              <title>{ln.label}</title>
            </polyline>
          ) : null
        })}
        {drawn.map((d) => {
          const color = d.category && d.category in TYPE_COLORS ? TYPE_COLORS[d.category] : 'var(--map-dot)'
          const letter = typed && d.category && d.category !== '유지' && d.category in TYPE_COLORS && d.r >= 6 ? d.category : null
          const selected = d.key === selectedKey
          const cls = `map-dot role-${d.role}${selected ? ' is-selected' : ''}${hover === d.key ? ' is-hover' : ''}`
          return (
            <g
              key={d.key}
              className={cls}
              tabIndex={onSelect ? 0 : undefined}
              role={onSelect ? 'button' : 'img'}
              aria-label={`${d.name}${d.detail ? `, ${d.detail}` : ''}`}
              aria-pressed={onSelect ? selected : undefined}
              onPointerEnter={() => setHover(d.key)}
              onPointerLeave={() => setHover((h) => (h === d.key ? null : h))}
              onFocus={() => setHover(d.key)}
              onBlur={() => setHover((h) => (h === d.key ? null : h))}
              onClick={onSelect ? () => onSelect(d) : undefined}
              onKeyDown={
                onSelect
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onSelect(d)
                      }
                    }
                  : undefined
              }
            >
              <circle cx={d.x} cy={d.y} r={Math.max(12, d.r + 3)} fill="transparent" />
              {d.role === 'hub' ? (
                <rect className="map-mark" x={d.x - d.r} y={d.y - d.r} width={d.r * 2} height={d.r * 2} rx={2.5} />
              ) : (
                <circle className="map-mark" cx={d.x} cy={d.y} r={d.r} fill={color} />
              )}
              {letter && (
                <text className="map-letter" x={d.x} y={d.y} fill={TYPE_INK[letter]} fontSize={d.r >= 8 ? 10.5 : 8.5} textAnchor="middle" dominantBaseline="central">
                  {letter}
                </text>
              )}
            </g>
          )
        })}
        {placed
          .filter((d) => labels.has(d.key))
          .map((d) => {
            const at = labels.get(d.key)!
            return (
              <text key={d.key} className={`map-label${d.role === 'target' || d.key === selectedKey ? ' is-strong' : ''}`} x={at.x} y={at.y} textAnchor={at.anchor} aria-hidden="true">
                {d.name}
              </text>
            )
          })}
      </svg>
      {tip && <Tooltip x={tip.x} y={tip.y} boundWidth={width} title={tip.name} rows={tip.detail ? [{ key: 'd', name: tip.detail, value: '' }] : []} />}
    </div>
  )
}
