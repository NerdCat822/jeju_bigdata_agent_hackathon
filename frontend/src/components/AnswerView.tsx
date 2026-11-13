import type { ReactNode } from 'react'
import type { Answer, Badge, NextQuestion, Suggestion } from '../api/types'
import { EvidencePanel } from './EvidencePanel'
import { Icon } from './Icon'
import { VerificationPanel } from './VerificationPanel'
import { ChartCard } from './viz/ChartCard'
import { MapCard } from './viz/MapCard'

interface Props {
  answer: Answer
  stageTitle: string | null
  busy: boolean
  /** 클라우드 전송에 아직 동의하지 않았으면 미리보기 아래에 동의 단추를 보여 줘요. */
  needsConsent: boolean
  onAsk: (question: string) => void
  onReport: () => void
  onPickPlace: (name: string) => void
  onAgreeCloud: () => void
}

/** 답 하나: 한 줄 결론 → 쉬운 해설 → 차트·지도 → 제안 → 근거표 → 한계 → 다음 질문. */
export function AnswerView({ answer: a, stageTitle, busy, needsConsent, onAsk, onReport, onPickPlace, onAgreeCloud }: Props): ReactNode {
  if (!a.ok) return <FailedAnswer answer={a} busy={busy} onAsk={onAsk} />
  const typeBadge = a.badges.find((b) => b.tone === 'type')
  const others = a.badges.filter((b) => b !== typeBadge)
  const visuals = a.charts.length + a.maps.length
  return (
    <article className="answer" id={a.stage ? `stage-${a.stage}` : undefined} aria-labelledby={`headline-${a.id}`}>
      <header className="answer-head">
        <span className="answer-stage">{a.stage && stageTitle ? `Stage ${a.stage} · ${stageTitle}` : '자유 질문'}</span>
        <BadgeRow badges={others} />
      </header>

      <div className="headline">
        <div>
          <p className="headline-label">한 줄 결론</p>
          <h2 id={`headline-${a.id}`} className="headline-text">
            {a.headline}
          </h2>
        </div>
        {typeBadge && <span className="badge badge-type">{typeBadge.label}</span>}
      </div>

      {a.explanation && <p className="explanation">{a.explanation}</p>}

      {a.notices.length > 0 && (
        <ul className="notices">
          {a.notices.map((n) => (
            <li key={n}>
              <Icon name="info" size={14} /> {n}
            </li>
          ))}
        </ul>
      )}

      {a.suggestions.length > 0 && <Suggestions items={a.suggestions} />}

      {visuals > 0 && (
        <div className={`viz-grid${visuals === 1 ? ' is-single' : ''}`}>
          {a.charts.map((c) => (
            <ChartCard key={c.id} spec={c} />
          ))}
          {a.maps.map((m) => (
            <MapCard key={m.id} spec={m} onPickPlace={busy ? undefined : onPickPlace} />
          ))}
        </div>
      )}

      <div className="folds">
        <EvidencePanel tables={a.evidence} />
        {a.limits.length > 0 && (
          <details className="fold">
            <summary>
              <Icon name="chevron" size={14} /> 한계 <span className="fold-peek">{a.limits[0]}</span>
            </summary>
            <ul className="fold-body limits">
              {a.limits.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
        )}
        <VerificationPanel answer={a} />
        {a.llm_payload && (a.llm_mode === 'anthropic' || needsConsent) && (
          <details className="fold" open={needsConsent}>
            <summary>
              <Icon name="chevron" size={14} /> 전송 미리보기 <span className="muted">클라우드 LLM에 보내는 내용 (집계 지표만)</span>
            </summary>
            <div className="fold-body">
              <pre className="payload">{a.llm_payload}</pre>
              {needsConsent && (
                <button type="button" className="btn btn-dark" disabled={busy} onClick={onAgreeCloud}>
                  이 내용을 보내는 데 동의하고 다시 실행
                </button>
              )}
            </div>
          </details>
        )}
      </div>

      <NextQuestions items={a.next_questions} busy={busy} onAsk={onAsk} onReport={onReport} />
    </article>
  )
}

function BadgeRow({ badges }: { badges: Badge[] }): ReactNode {
  if (!badges.length) return null
  return (
    <ul className="badge-row" aria-label="표시">
      {badges.map((b) => (
        <li key={b.label} className={`badge badge-${b.tone}`}>
          {b.tone === 'warn' && <Icon name="alert" size={12} />}
          {b.label}
        </li>
      ))}
    </ul>
  )
}

function Suggestions({ items }: { items: Suggestion[] }): ReactNode {
  return (
    <section className="suggestions" aria-label="규칙이 만든 제안">
      <h3 className="section-title">제안 후보</h3>
      <ol>
        {items.map((s) => (
          <li key={s.rule_id} className="suggestion">
            <div className="suggestion-head">
              <span className="rule-id">{s.rule_id}</span>
              <strong>{s.name}</strong>
              {s.target && <span className="muted">대상 · {s.target}</span>}
            </div>
            <p>{s.text}</p>
            {s.evidence_text.length > 0 && <p className="suggestion-evidence">근거 · {s.evidence_text.join(' · ')}</p>}
          </li>
        ))}
      </ol>
      <p className="muted small">제안은 설정 파일의 규칙만 만들어요. 규칙 번호와 근거 지표를 함께 보여 줘요.</p>
    </section>
  )
}

interface NextProps {
  items: NextQuestion[]
  busy: boolean
  onAsk: (question: string) => void
  onReport: () => void
}

function NextQuestions({ items, busy, onAsk, onReport }: NextProps): ReactNode {
  if (!items.length) return null
  return (
    <nav className="next" aria-label="다음 질문">
      {items.map((n) => {
        const primary = n.kind === 'next_stage' || n.kind === 'report'
        return (
          <button
            key={n.question}
            type="button"
            className={`btn ${primary ? 'btn-accent' : 'btn-outline'}`}
            disabled={busy}
            onClick={() => (n.kind === 'report' ? onReport() : onAsk(n.question))}
          >
            {n.kind === 'report' && <Icon name="doc" />}
            {n.label}
          </button>
        )
      })}
    </nav>
  )
}

function FailedAnswer({ answer: a, busy, onAsk }: { answer: Answer; busy: boolean; onAsk: (q: string) => void }): ReactNode {
  return (
    <article className="answer answer-failed" role="status">
      <div className="headline is-warn">
        <div>
          <p className="headline-label">답하지 못했어요</p>
          <h2 className="headline-text">{a.message ?? a.headline}</h2>
        </div>
      </div>
      {a.next_questions.length > 0 && (
        <>
          <p className="muted">이렇게 물어볼 수 있어요.</p>
          <nav className="next" aria-label="예시 질문">
            {a.next_questions.map((n) => (
              <button key={n.question} type="button" className="btn btn-outline" disabled={busy} onClick={() => onAsk(n.question)}>
                {n.label}
              </button>
            ))}
          </nav>
        </>
      )}
    </article>
  )
}
