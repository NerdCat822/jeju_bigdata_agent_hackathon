import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { ChartSpec } from '../../api/types'
import { axisTick, isNum, valueLabel } from '../../lib/format'
import { linear, niceAxis } from '../../lib/scale'
import { useWidth } from '../../lib/useSize'
import { seriesColor } from './palette'
import { Tooltip } from './Tooltip'

const ROW = 30
const M = { top: 8, right: 64, bottom: 26, left: 96 }

function barPath(y: number, h: number, x0: number, x1: number): string {
  const r = Math.min(4, h / 2, Math.abs(x1 - x0))
  const s = x1 >= x0 ? 1 : -1
  return `M${x0},${y}L${x1 - s * r},${y}Q${x1},${y} ${x1},${y + r}L${x1},${y + h - r}Q${x1},${y + h} ${x1 - s * r},${y + h}L${x0},${y + h}Z`
}

/** 가로 막대 차트. 이름이 긴 항목을 비교할 때 써요. 계열이 여럿이어도 첫 계열만 그려요 (나머지는 표로 봐요). */
export function HBarChart({ spec }: { spec: ChartSpec }): ReactNode {
  const [ref, width] = useWidth<HTMLDivElement>(520)
  const [active, setActive] = useState<number | null>(null)
  const s = spec.series[0]
  const n = spec.x.length
  const plotW = Math.max(60, width - M.left - M.right)
  const height = M.top + n * ROW + M.bottom
  const { axis, maxAbs } = useMemo(() => {
    const values = (s?.y ?? []).filter(isNum)
    return { axis: niceAxis(values, true), maxAbs: Math.max(...values.map(Math.abs), 0) }
  }, [s])
  if (!s) return null
  const x = linear(axis.lo, axis.hi, M.left, M.left + plotW)
  const zero = x(0)
  const barH = Math.min(18, ROW - 10)

  return (
    <div ref={ref} className="viz-plot">
      <svg width={width} height={height} role="img" aria-label={`${spec.title}. 막대마다 Tab 키로 값을 읽을 수 있어요.`}>
        {axis.ticks.map((t) => (
          <g key={t} aria-hidden="true">
            <line className={t === 0 ? 'viz-axis' : 'viz-grid'} x1={x(t)} x2={x(t)} y1={M.top} y2={M.top + n * ROW} />
            <text className="viz-tick" x={x(t)} y={height - 8} textAnchor="middle">
              {axisTick(t, spec.y_format, maxAbs)}
            </text>
          </g>
        ))}
        {spec.x.map((name, i) => {
          const v = s.y[i]
          const top = M.top + i * ROW + (ROW - barH) / 2
          return (
            <g
              key={name}
              className={`viz-band${active === i ? ' is-active' : ''}`}
              tabIndex={0}
              role="img"
              aria-label={`${name}: ${valueLabel(v, spec.y_format)}`}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            >
              <rect x={0} y={M.top + i * ROW} width={width} height={ROW} fill="transparent" />
              <text className="viz-tick viz-cat" x={M.left - 8} y={top + barH / 2} textAnchor="end" dominantBaseline="middle">
                {name.length > 8 ? `${name.slice(0, 7)}…` : name}
              </text>
              {isNum(v) && (
                <>
                  <path className="viz-bar" d={barPath(top, barH, zero, x(v))} fill={seriesColor(0)} />
                  <text className="viz-value" x={v >= 0 ? x(v) + 6 : x(v) - 6} y={top + barH / 2} textAnchor={v >= 0 ? 'start' : 'end'} dominantBaseline="middle">
                    {valueLabel(v, spec.y_format)}
                  </text>
                </>
              )}
            </g>
          )
        })}
      </svg>
      {active !== null && (
        <Tooltip
          x={M.left + plotW / 2}
          y={M.top + active * ROW}
          boundWidth={width}
          title={spec.x[active]}
          rows={[{ key: s.name, name: s.name, value: valueLabel(s.y[active], spec.y_format) }]}
        />
      )}
    </div>
  )
}
