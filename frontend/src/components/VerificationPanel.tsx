import type { ReactNode } from 'react'
import type { Answer } from '../api/types'
import { seconds } from '../lib/format'
import { Icon } from './Icon'
import { CHECK_LABEL, explainedBy } from './verification'

/** 검증 결과와 실행 기록. 답이 어떻게 만들어졌는지 그대로 보여 줘요. */
export function VerificationPanel({ answer: a }: { answer: Answer }): ReactNode {
  const v = a.verification
  const failed = v.checks.filter((c) => !c.passed)
  return (
    <details className="fold">
      <summary>
        <Icon name="chevron" />
        <span className={`verify-state${v.passed ? ' is-ok' : ' is-fail'}`}>
          <Icon name={v.passed ? 'check' : 'alert'} />
          {v.passed ? `검증 통과 · ${v.checks.length}개 항목` : `검증 실패 · ${failed.length}개 항목`}
        </span>
        <span className="muted">
          {explainedBy(a)} · {seconds(a.elapsed)}
        </span>
      </summary>
      <div className="fold-body verify-body">
        <ul className="check-list">
          {v.checks.map((c) => (
            <li key={c.name} className={c.passed ? 'is-ok' : 'is-fail'}>
              <Icon name={c.passed ? 'check' : 'x'} />
              <strong>{CHECK_LABEL[c.name] ?? c.name}</strong>
              <span>{c.detail}</span>
            </li>
          ))}
        </ul>
        {a.steps.length > 0 && (
          <>
            <h4 className="evidence-title">실행 기록</h4>
            <ol className="step-list">
              {a.steps.map((s, i) => (
                <li key={i} className={s.ok ? undefined : 'is-fail'}>
                  <code>{s.tool}</code>
                  <span className="muted">{seconds(s.seconds)}</span>
                  {s.note && <span>{s.note}</span>}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </details>
  )
}
