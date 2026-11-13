import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { ChartSpec } from '../../api/types'
import { axisTick, isNum, valueLabel } from '../../lib/format'
import { linear, niceAxis } from '../../lib/scale'
import { useWidth } from '../../lib/useSize'
import { seriesColor } from './palette'
import { Tooltip } from './Tooltip'

const H = 260
const M = { top: 24, right: 12, bottom: 32, left: 48 }
const MAX_BAR = 24
const GAP = 2

/** 값 쪽 끝만 둥글고 기준선 쪽은 각진 막대. */
function barPath(x: number, w: number, y0: number, y1: number): string {
  const r = Math.min(4, w / 2, Math.abs(y1 - y0))
  const up = y1 < y0
  const s = up ? 1 : -1
  return `M${x},${y0}L${x},${y1 + s * r}Q${x},${y1} ${x + r},${y1}L${x + w - r},${y1}Q${x + w},${y1} ${x + w},${y1 + s * r}L${x + w},${y0}Z`
}

const CHAR_W = 12
function fitLabel(text: string, room: number): string {
  if (text.length * CHAR_W <= room) return text
  const keep = Math.max(2, Math.floor(room / CHAR_W) - 1)
  return `${text.slice(0, keep)}…`
}

/** 세로 막대 차트. 계열이 둘 이상인 비교에 써요 (계열이 하나면 막대 목록을 써요). 막대는 0 에서 자라요. */
export function BarChart({ spec }: { spec: ChartSpec }): ReactNode {
  const [ref, width] = useWidth<HTMLDivElement>(520)
  const [active, setActive] = useState<number | null>(null)
  const n = spec.x.length
  const m = spec.series.length
  const plotW = Math.max(60, width - M.left - M.right)
  const plotH = H - M.top - M.bottom

  const { axis, maxAbs } = useMemo(() => {
    const values = spec.series.flatMap((s) => s.y.filter(isNum))
    return { axis: niceAxis(values, true), maxAbs: Math.max(...values.map(Math.abs), 0) }
  }, [spec])
  const y = linear(axis.lo, axis.hi, M.top + plotH, M.top)
  const band = plotW / Math.max(1, n)
  const barW = Math.max(3, Math.min(MAX_BAR, (band * 0.62 - GAP * (m - 1)) / m))
  const groupW = barW * m + GAP * (m - 1)
  const zero = y(0)
  const labelAll = n * m <= 6 // 막대가 적을 때만 값마다 적어요. 많으면 눈금과 툴팁에 맡겨요.
  const unit = spec.y_format === 'num' && spec.y_title.length <= 2 ? spec.y_title : ''

  return (
    <div ref={ref} className="viz-plot">
      <svg width={width} height={H} role="img" aria-label={`${spec.title}. 막대마다 Tab 키로 값을 읽을 수 있어요.`}>
        {axis.ticks.map((t) => (
          <g key={t} aria-hidden="true">
            <line className={t === 0 ? 'viz-axis' : 'viz-grid-line'} x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} />
            <text className="viz-tick" x={M.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
              {axisTick(t, spec.y_format, maxAbs)}
            </text>
          </g>
        ))}
        {spec.x.map((name, i) => {
          const cx = M.left + band * (i + 0.5)
          const x0 = cx - groupW / 2
          const values = spec.series.map((s) => s.y[i])
          const label = spec.series.map((s, k) => `${m > 1 ? `${s.name} ` : ''}${valueLabel(values[k], spec.y_format, unit)}`).join(', ')
          return (
            <g
              key={name}
              className={`viz-band${active === i ? ' is-active' : ''}`}
              tabIndex={0}
              role="img"
              aria-label={`${name}: ${label}`}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            >
              <rect x={cx - band / 2} y={M.top - 8} width={band} height={plotH + 8 + M.bottom} fill="transparent" />
              {values.map((v, k) => {
                if (!isNum(v)) return null
                const bx = x0 + k * (barW + GAP)
                const tip = y(v)
                return (
                  <g key={spec.series[k].name}>
                    <path className="viz-bar" d={barPath(bx, barW, zero, tip)} fill={seriesColor(k)} />
                    {labelAll && (
                      <text className="viz-value" x={bx + barW / 2} y={v >= 0 ? tip - 6 : tip + 14} textAnchor="middle">
                        {valueLabel(v, spec.y_format)}
                      </text>
                    )}
                  </g>
                )
              })}
              <text className="viz-tick viz-cat" x={cx} y={H - 12} textAnchor="middle">
                {fitLabel(name, band - 6)}
              </text>
            </g>
          )
        })}
      </svg>
      {active !== null && (
        <Tooltip
          x={M.left + band * (active + 0.5)}
          y={M.top}
          boundWidth={width}
          title={spec.x[active]}
          rows={spec.series.map((s, k) => ({
            key: s.name,
            name: s.name,
            value: valueLabel(s.y[active], spec.y_format, unit),
            color: m > 1 ? seriesColor(k) : undefined,
          }))}
        />
      )}
    </div>
  )
}
