import { useState } from 'react'
import type { ReactNode } from 'react'
import type { ChartSpec } from '../../api/types'
import { valueLabel } from '../../lib/format'
import { BarChart } from './BarChart'
import { HBarChart } from './HBarChart'
import { LineChart } from './LineChart'
import { seriesColor } from './palette'

/** 차트 한 장: 제목, 범례(계열이 둘 이상일 때), 그림, 설명. '표' 단추로 같은 값을 표로 볼 수 있어요. */
export function ChartCard({ spec }: { spec: ChartSpec }): ReactNode {
  const [asTable, setAsTable] = useState(false)
  const line = spec.kind === 'line'
  return (
    <figure className="viz-card">
      <div className="viz-head">
        <figcaption className="viz-title">{spec.title}</figcaption>
        <button type="button" className="viz-toggle" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? '차트로 보기' : '표로 보기'}
        </button>
      </div>
      {spec.series.length >= 2 && (
        <ul className="viz-legend" aria-label="범례">
          {spec.series.map((s, k) => (
            <li key={s.name}>
              <span className={line ? 'viz-key-line' : 'viz-key-box'} style={{ background: seriesColor(k) }} aria-hidden="true" />
              {s.name}
            </li>
          ))}
        </ul>
      )}
      {asTable ? (
        <ChartTable spec={spec} />
      ) : line ? (
        <LineChart spec={spec} />
      ) : spec.kind === 'hbar' ? (
        <HBarChart spec={spec} />
      ) : (
        <BarChart spec={spec} />
      )}
      {(spec.y_title || spec.note) && (
        <p className="viz-note">
          {spec.y_title && <span>세로축: {spec.y_title}</span>}
          {spec.y_title && spec.note && ' · '}
          {spec.note}
        </p>
      )}
    </figure>
  )
}

function ChartTable({ spec }: { spec: ChartSpec }): ReactNode {
  return (
    <div className="table-scroll viz-table">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">구분</th>
            {spec.series.map((s) => (
              <th scope="col" key={s.name} className="num">
                {s.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.x.map((label, i) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              {spec.series.map((s) => (
                <td key={s.name} className="num">
                  {valueLabel(s.y[i], spec.y_format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
