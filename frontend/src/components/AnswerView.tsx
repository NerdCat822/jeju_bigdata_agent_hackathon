import type { ReactNode } from 'react'
import type { Answer, NextQuestion, Suggestion } from '../api/types'
import { caption } from '../lib/format'
import { EvidencePanel } from './EvidencePanel'
import { Icon } from './Icon'
import { TypeMark } from './TypeMark'
import { VerificationPanel } from './VerificationPanel'
import { ChartCard } from './viz/ChartCard'
import { MapCard } from './viz/MapCard'
import { isTypeCode } from './viz/palette'

interface Props {
  answer: Answer
  stageTitle: string | null
  /** 유형 코드 → 이름 (예: C → 방문 의존형). */
  typeNames: Map<string, string>
  busy: boolean
  /** 클라우드 전송에 아직 동의하지 않았으면 미리보기 아래에 동의 단추를 보여 줘요. */
  needsConsent: boolean
  onAsk: (question: string) => void
  onReport: () => void
  onPickPlace: (name: string) => void
  onAgreeCloud: () => void
}

/** 답 하나: 한 줄 결론 → 쉬운 해설 → 제안 → 차트·지도 → 근거표 · 한계 · 검증 → 다음 질문. */
export function AnswerView({ answer: a, stageTitle, typeNames, busy, needsConsent, onAsk, onReport, onPickPlace, onAgreeCloud }: Props): ReactNode {
  if (!a.ok) return <FailedAnswer answer={a} busy={busy} onAsk={onAsk} />
  const type = a.badges.find((b) => b.tone === 'type')?.label.replace('유형 ', '') ?? null
  // 데이터 배지는 화면 위쪽에 늘 있어서 답마다 되풀이하지 않아요.
  const tags = a.badges.filter((b) => b.tone !== 'type' && b.tone !== 'data')

  return (
    <article className="answer" id={a.stage ? `stage-${a.stage}` : undefined} aria-labelledby={`headline-${a.id}`}>
      <header className="headline">
        <div className="headline-meta">
          <span>{a.stage && stageTitle ? `Stage ${a.stage} · ${stageTitle}` : '자유 질문'}</span>
          {tags.length > 0 && (
            <ul className="tag-row" aria-label="표시">
              {tags.map((b) => (
                <li key={b.label} className={`tag${b.tone === 'warn' ? ' tag-warn' : ''}`}>
                  {b.tone === 'warn' && <Icon name="alert" />}
                  {b.label}
                </li>
              ))}
            </ul>
          )}
          <span className="spacer" />
          {type && isTypeCode(type) && (
            <span className="type-name">
              <TypeMark code={type} />
              {type === '유지' ? '유지형' : `${type} ${typeNames.get(type) ?? ''}`}
            </span>
          )}
        </div>
        <h2 id={`headline-${a.id}`} className="headline-text">
          {a.headline}
        </h2>
      </header>

      {a.explanation && <p className="explanation">{a.explanation}</p>}

      {a.notices.length > 0 && (
        <ul className="notices">
          {a.notices.map((n) => (
            <li key={n}>
              <Icon name="info" /> {n}
            </li>
          ))}
        </ul>
      )}

      {a.suggestions.length > 0 && <Suggestions items={a.suggestions} />}

      <Visuals answer={a} onPickPlace={busy ? undefined : onPickPlace} />

      <div className="folds">
        <EvidencePanel tables={a.evidence} place={a.query.place_kind === 'emd' ? a.query.place_name : null} />
        {a.limits.length > 0 && (
          <details className="fold">
            <summary>
              <Icon name="chevron" /> 한계 <span className="fold-peek">{caption(a.limits[0])}</span>
            </summary>
            <ul className="limits">
              {a.limits.map((l) => (
                <li key={l}>{caption(l)}</li>
              ))}
            </ul>
          </details>
        )}
        <VerificationPanel answer={a} />
        {a.llm_payload && (a.llm_mode === 'anthropic' || needsConsent) && (
          <details className="fold" open={needsConsent}>
            <summary>
              <Icon name="chevron" /> 전송 미리보기 <span className="muted">클라우드 LLM에 보내는 내용 (집계 지표만)</span>
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

/**
 * 차트와 지도의 자리.
 * 주인공 하나(추이 선, 없으면 지도)를 넓게 두고, 항목 비교는 옆의 좁은 목록으로 둬요. 유형 지도는 한 줄을 다 써요.
 */
function Visuals({ answer: a, onPickPlace }: { answer: Answer; onPickPlace?: (name: string) => void }): ReactNode {
  const line = a.charts.find((c) => c.kind === 'line') ?? null
  const others = a.charts.filter((c) => c !== line)
  const maps = [...a.maps]
  if (!line && !others.length && !maps.length) return null

  if (line) {
    const [side, ...rest] = others
    return (
      <div className="viz-grid">
        <ChartCard spec={line} wide={!side} />
        {side && <ChartCard spec={side} />}
        {maps.map((m) => (
          <MapCard key={m.id} spec={m} wide onPickPlace={onPickPlace} />
        ))}
        {rest.map((c) => (
          <ChartCard key={c.id} spec={c} wide />
        ))}
      </div>
    )
  }
  if (maps.length && others.length) {
    const [map, ...moreMaps] = maps
    const [side, ...rest] = others
    return (
      <div className="viz-grid">
        <MapCard spec={map} onPickPlace={onPickPlace} />
        <ChartCard spec={side} />
        {moreMaps.map((m) => (
          <MapCard key={m.id} spec={m} wide onPickPlace={onPickPlace} />
        ))}
        {rest.map((c) => (
          <ChartCard key={c.id} spec={c} wide />
        ))}
      </div>
    )
  }
  return (
    <div className={`viz-grid${maps.length ? '' : ' is-single'}`}>
      {others.map((c) => (
        <ChartCard key={c.id} spec={c} wide={maps.length > 0} />
      ))}
      {maps.map((m) => (
        <MapCard key={m.id} spec={m} wide onPickPlace={onPickPlace} />
      ))}
    </div>
  )
}

function Suggestions({ items }: { items: Suggestion[] }): ReactNode {
  return (
    <section className="suggestions" aria-label="규칙이 만든 제안">
      <h3 className="section-title">제안 후보</h3>
      <ol>
        {items.map((s) => (
          <li key={s.rule_id} className="suggestion">
            <span className="rule-id">{s.rule_id}</span>
            <div className="suggestion-head">
              <span>{s.name}</span>
              {s.target && <span className="muted">대상 {s.target}</span>}
            </div>
            <p>{s.text}</p>
            {s.evidence_text.length > 0 && <p className="suggestion-evidence">근거 · {s.evidence_text.join(' · ')}</p>}
          </li>
        ))}
      </ol>
      <p className="muted small">제안은 설정 파일의 규칙만 만들고, 규칙 번호와 근거 지표를 함께 보여 줘요</p>
    </section>
  )
}

interface NextProps {
  items: NextQuestion[]
  busy: boolean
  onAsk: (question: string) => void
  onReport: () => void
}

/** "이 동네에 누가 올까? → Stage 2" 같은 이름에서 화살표 뒤는 떼고, 다음 단계로 간다는 뜻은 아이콘으로 보여 줘요. */
const plainLabel = (label: string): string => label.replace(/\s*→\s*Stage\s*\d+\s*$/, '')

function NextQuestions({ items, busy, onAsk, onReport }: NextProps): ReactNode {
  if (!items.length) return null
  return (
    <nav className="next" aria-label="다음 질문">
      {items.map((n) => {
        const forward = n.kind === 'next_stage' || n.kind === 'report'
        return (
          <button
            key={n.question}
            type="button"
            className={`btn ${forward ? 'btn-accent' : 'btn-outline'}`}
            disabled={busy}
            onClick={() => (n.kind === 'report' ? onReport() : onAsk(n.question))}
          >
            {plainLabel(n.label)}
            {n.kind === 'next_stage' && <Icon name="arrow" />}
          </button>
        )
      })}
    </nav>
  )
}

function FailedAnswer({ answer: a, busy, onAsk }: { answer: Answer; busy: boolean; onAsk: (q: string) => void }): ReactNode {
  return (
    <article className="answer" role="status">
      <header className="headline">
        <div className="headline-meta">
          <span>답하지 못했어요</span>
        </div>
        <h2 className="headline-text">{a.message ?? a.headline}</h2>
      </header>
      {a.next_questions.length > 0 && (
        <>
          <p className="muted">이렇게 물어볼 수 있어요</p>
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
