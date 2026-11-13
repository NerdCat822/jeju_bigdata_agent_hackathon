import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Progress } from '../api/types'
import { seconds } from '../lib/format'
import { Icon, Spinner } from './Icon'
import { toRows } from './progressRows'

function useElapsed(startedAt: number | null, running: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(id)
  }, [running])
  return startedAt ? Math.max(0, (now - startedAt) / 1000) : 0
}

interface Props {
  items: Progress[]
  running: boolean
  startedAt: number | null
}

/** 답을 만드는 동안 지금 무엇을 하는지 보여 줘요. */
export function ProgressList({ items, running, startedAt }: Props): ReactNode {
  const elapsed = useElapsed(startedAt, running)
  const rows = toRows(items, running)
  const waiting = rows.some((r) => r.state === 'wait')
  return (
    <section className="progress" aria-label="진행 상황" aria-live="polite">
      <div className="progress-head">
        <span>
          {running ? (
            <>
              <Spinner /> 답을 만들고 있어요
            </>
          ) : (
            '이렇게 만들었어요'
          )}
        </span>
        {running && <span className="muted mono small">{seconds(elapsed)}</span>}
      </div>
      <ol className="progress-list">
        {rows.map((r) =>
          r.kind === 'stage' ? (
            <li key={r.key} className="progress-stage">
              {r.label}
            </li>
          ) : (
            <li key={r.key} className={`progress-step is-${r.state}`}>
              {r.state === 'wait' ? <Spinner /> : <Icon name={r.state === 'ok' ? 'check' : 'x'} />}
              <span>{r.label}</span>
              {r.note && <span className="muted">{r.note}</span>}
            </li>
          ),
        )}
        {running && !waiting && (
          <li className="progress-step is-wait">
            <Spinner /> <span>계산하는 중</span>
          </li>
        )}
      </ol>
    </section>
  )
}
