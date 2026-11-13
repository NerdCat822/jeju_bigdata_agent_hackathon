import { useMemo, useState } from 'react'
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react'
import type { ChartSpec } from '../../api/types'
import { axisTick, isNum, shortMonth, valueLabel } from '../../lib/format'
import { linear, niceAxis, thin } from '../../lib/scale'
import { useWidth } from '../../lib/useSize'
import { seriesColor } from './palette'
import { Tooltip } from './Tooltip'

const H = 236
const M = { top: 14, right: 54, bottom: 30, left: 46 }

/** 선 차트. 포인터나 화살표 키로 가로축 위치를 고르면 그 달의 모든 계열 값을 보여 줘요. */
export function LineChart({ spec }: { spec: ChartSpec }): ReactNode {
  const [ref, width] = useWidth<HTMLDivElement>(520)
  const [active, setActive] = useState<number | null>(null)
  const n = spec.x.length
  const plotW = Math.max(60, width - M.left - M.right)
  const plotH = H - M.top - M.bottom

  const { axis, maxAbs } = useMemo(() => {
    const values = spec.series.flatMap((s) => s.y.filter(isNum))
    return { axis: niceAxis(values, false), maxAbs: Math.max(...values.map(Math.abs), 0) }
  }, [spec])
  const x = (i: number): number => M.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW)
  const y = linear(axis.lo, axis.hi, M.top + plotH, M.top)

  const paths = spec.series.map((s) => {
    let d = ''
    let pen = false
    s.y.forEach((v, i) => {
      if (!isNum(v)) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return d
  })
  // 선 끝의 값. 끝이 서로 붙으면(13px 미만) 겹치니까 적지 않고 범례와 툴팁에 맡겨요.
  const ends = spec.series.map((s) => {
    for (let i = s.y.length - 1; i >= 0; i--) {
      const v = s.y[i]
      if (isNum(v)) return { i, v, y: y(v) }
    }
    return null
  })
  const endYs = ends.filter((e): e is NonNullable<typeof e> => e !== null).map((e) => e.y).sort((a, b) => a - b)
  const endLabelsFit = endYs.every((v, i) => i === 0 || v - endYs[i - 1] >= 13)
  const xLabels = thin(n, Math.max(2, Math.floor(plotW / 58)))

  const pick = (e: PointerEvent<SVGRectElement>): void => {
    const box = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - box.left) / (box.width || 1)
    setActive(Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1)))))
  }
  const onKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    const cur = active ?? n - 1
    const next =
      e.key === 'ArrowLeft' ? cur - 1 : e.key === 'ArrowRight' ? cur + 1 : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : null
    if (e.key === 'Escape') setActive(null)
    if (next === null) return
    e.preventDefault()
    setActive(Math.max(0, Math.min(n - 1, next)))
  }
  const rows =
    active === null
      ? []
      : spec.series.map((s, k) => ({
          key: s.name,
          name: s.name,
          value: valueLabel(s.y[active], spec.y_format),
          color: seriesColor(k),
        }))

  return (
    <div
      ref={ref}
      className="viz-plot"
      tabIndex={0}
      role="group"
      aria-label={`${spec.title}. ${spec.x[0]}부터 ${spec.x[n - 1]}까지 ${spec.series.map((s) => s.name).join(', ')}. 왼쪽·오른쪽 화살표 키로 달마다 값을 읽을 수 있어요.`}
      onKeyDown={onKey}
      onFocus={() => setActive((a) => a ?? n - 1)}
      onBlur={() => setActive(null)}
    >
      <svg width={width} height={H} aria-hidden="true">
        {axis.ticks.map((t) => (
          <g key={t}>
            <line className="viz-grid" x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} />
            <text className="viz-tick" x={M.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
              {axisTick(t, spec.y_format, maxAbs)}
            </text>
          </g>
        ))}
        <line className="viz-axis" x1={M.left} x2={M.left + plotW} y1={M.top + plotH} y2={M.top + plotH} />
        {xLabels.map((i) => (
          <text key={i} className="viz-tick" x={x(i)} y={H - 10} textAnchor="middle">
            {shortMonth(spec.x[i])}
          </text>
        ))}
        {active !== null && <line className="viz-cross" x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + plotH} />}
        {paths.map((d, k) => (
          <path key={spec.series[k].name} className="viz-line" d={d} stroke={seriesColor(k)} />
        ))}
        {ends.map((e, k) =>
          e ? (
            <g key={spec.series[k].name}>
              <circle className="viz-dot" cx={x(e.i)} cy={e.y} r={4} fill={seriesColor(k)} />
              {endLabelsFit && (
                <text className="viz-end" x={x(e.i) + 9} y={e.y} dominantBaseline="middle">
                  {valueLabel(e.v, spec.y_format)}
                </text>
              )}
            </g>
          ) : null,
        )}
        {active !== null &&
          spec.series.map((s, k) => {
            const v = s.y[active]
            return isNum(v) ? <circle key={s.name} className="viz-dot" cx={x(active)} cy={y(v)} r={4.5} fill={seriesColor(k)} /> : null
          })}
        <rect
          x={M.left}
          y={M.top}
          width={plotW}
          height={plotH}
          fill="transparent"
          onPointerMove={pick}
          onPointerDown={pick}
          onPointerLeave={() => setActive(null)}
        />
      </svg>
      {active !== null && <Tooltip x={x(active)} y={M.top + 8} boundWidth={width} title={spec.x[active]} rows={rows} />}
      <span className="sr-only" aria-live="polite">
        {active !== null ? `${spec.x[active]}: ${rows.map((r) => `${r.name} ${r.value}`).join(', ')}` : ''}
      </span>
    </div>
  )
}
