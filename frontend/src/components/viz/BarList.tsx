import type { ReactNode } from 'react'
import type { ChartSpec } from '../../api/types'
import { isNum, valueLabel } from '../../lib/format'

/**
 * 막대 목록. 항목이 몇 개 안 되는 비교(비슷한 읍면, 테마, 시나리오)를 한 줄씩 보여 줘요.
 * 막대는 0 에서 자라고, 값은 줄마다 적혀 있어서 툴팁 없이 읽을 수 있어요. 강조한 항목 하나만 강조색이에요.
 */
export function BarList({ spec }: { spec: ChartSpec }): ReactNode {
  const series = spec.series[0]
  if (!series) return null
  const nums = series.y.filter(isNum)
  const lo = Math.min(0, ...nums)
  const hi = Math.max(0, ...nums)
  const span = hi - lo || 1
  const zero = ((0 - lo) / span) * 100
  const unit = spec.y_format === 'num' && spec.y_title.length <= 2 ? spec.y_title : ''
  return (
    <ul className="bar-list" aria-label={`${spec.title}. 줄마다 Tab 키로 값을 읽을 수 있어요.`}>
      {spec.x.map((name, i) => {
        const v = series.y[i]
        const label = valueLabel(v, spec.y_format, unit)
        const lead = spec.highlight === name
        return (
          <li key={name} className={`bar-row${lead ? ' is-lead' : ''}`} tabIndex={0} aria-label={`${name}: ${label}${lead ? ' (지금 보는 항목)' : ''}`}>
            <span className="bar-name">{name}</span>
            <span className="bar-track" aria-hidden="true">
              {lo < 0 && <span className="bar-zero" style={{ left: `${zero}%` }} />}
              {isNum(v) && (
                <span
                  className="bar-fill"
                  style={{
                    left: `${((Math.min(v, 0) - lo) / span) * 100}%`,
                    width: `${(Math.abs(v) / span) * 100}%`,
                    borderRadius: v >= 0 ? '0 4px 4px 0' : '4px 0 0 4px',
                  }}
                />
              )}
            </span>
            <span className="bar-value">{label}</span>
          </li>
        )
      })}
    </ul>
  )
}
