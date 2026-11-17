import type { ReactNode } from 'react'
import type { Answer } from '../api/types'
import { keyFigures } from './keyFigures'

/** 핵심 숫자 카드. 두 개 이상 있을 때만 보여 줘요. */
export function KeyFigures({ answer }: { answer: Answer }): ReactNode {
  const figures = keyFigures(answer)
  if (figures.length < 2) return null
  return (
    <dl className="figures" aria-label="핵심 숫자">
      {figures.map((f) => (
        <div key={f.key} className="figure">
          <dt className="figure-label">{f.label}</dt>
          <dd className="figure-value">{f.value}</dd>
          {f.note && <dd className="figure-note">{f.note}</dd>}
        </div>
      ))}
    </dl>
  )
}
