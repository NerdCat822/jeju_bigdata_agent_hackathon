import type { ReactNode } from 'react'

export interface TipRow {
  key: string
  name: string
  value: string
  color?: string
}

interface Props {
  x: number
  y: number
  /** 툴팁을 가둘 영역의 너비. 오른쪽 끝에서는 왼쪽으로 뒤집어요. */
  boundWidth: number
  title: ReactNode
  rows: TipRow[]
}

/** 값이 앞, 이름이 뒤. 계열은 짧은 선 조각으로 표시해요. */
export function Tooltip({ x, y, boundWidth, title, rows }: Props): ReactNode {
  const flip = x > boundWidth * 0.6
  return (
    <div
      className="viz-tip"
      role="presentation"
      style={{ left: flip ? undefined : x + 12, right: flip ? boundWidth - x + 12 : undefined, top: Math.max(0, y - 12) }}
    >
      <div className="viz-tip-title">{title}</div>
      {rows.map((r) => (
        <div className="viz-tip-row" key={r.key}>
          {r.color && <span className="viz-key-line" style={{ background: r.color }} aria-hidden="true" />}
          <strong>{r.value}</strong>
          <span>{r.name}</span>
        </div>
      ))}
    </div>
  )
}
