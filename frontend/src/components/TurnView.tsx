import type { ReactNode } from 'react'
import type { Bootstrap, QueryPatch } from '../api/types'
import hello from '../assets/mascot-hello.png'
import type { Turn } from '../state/agent'
import { AnswerView } from './AnswerView'
import { ConfirmCard } from './ConfirmCard'
import { Icon } from './Icon'
import { ProgressList } from './ProgressList'

interface Props {
  turn: Turn
  boot: Bootstrap
  latestYear: number | null
  busy: boolean
  cloudConsent: boolean
  onRun: () => void
  onEdit: (patch: QueryPatch) => void
  onAsk: (question: string) => void
  onReport: () => void
  onPickPlace: (name: string) => void
  onAgreeCloud: () => void
  onStop?: () => void
}

/** 질문 하나의 화면: 확인 카드 → 진행 상황 → 답(연계 실행은 단계마다 하나) → 제안서. */
export function TurnView({ turn, boot, latestYear, busy, cloudConsent, onRun, onEdit, onAsk, onReport, onPickPlace, onAgreeCloud, onStop }: Props): ReactNode {
  const running = turn.status === 'running'
  const titles = new Map(boot.options.stages.map((s) => [s.stage, s.title]))
  const typeNames = new Map(boot.options.types.map((t) => [t.code, t.label]))
  const cloud = boot.status.llm_mode === 'anthropic'
  const isChain = turn.card?.query.intent === 'chain'
  return (
    <div className="turn">
      <h1 className="turn-question">질문 · {turn.question}</h1>
      <ConfirmCard turn={turn} options={boot.options} places={boot.places} latestYear={latestYear} busy={busy} onRun={onRun} onEdit={onEdit} />

      {turn.status === 'error' && (
        <div className="callout is-warn" role="alert">
          <Icon name="alert" /> <span>{turn.error}</span>
          <button type="button" className="btn btn-outline" disabled={busy} onClick={onRun}>
            다시 시도
          </button>
        </div>
      )}

      {/* 멈추기는 Claude 모드에서만 보여 줘요 (기본 설명은 1초 안에 끝나요) */}
      {running && <ProgressList items={turn.progress} running startedAt={turn.startedAt} onStop={cloud ? onStop : undefined} />}

      {isChain && turn.answers.length > 0 && (
        <nav className="jump" aria-label="단계로 이동">
          {turn.answers.map((a) =>
            a.stage ? (
              <a key={a.id} className="jump-item" href={`#stage-${a.stage}`}>
                <span className="step-no" aria-hidden="true">
                  {a.stage}
                </span>
                <span>
                  <span className="sr-only">{a.stage}단계 </span>
                  {titles.get(a.stage)}
                </span>
              </a>
            ) : null,
          )}
          {turn.reportUrl && (
            <a className="jump-item" href="#report">
              <Icon name="doc" /> 최종 제안서
            </a>
          )}
        </nav>
      )}

      {turn.answers.map((a) => (
        <AnswerView
          key={a.id}
          answer={a}
          stageTitle={a.stage ? (titles.get(a.stage) ?? null) : null}
          typeNames={typeNames}
          busy={busy}
          needsConsent={cloud && !cloudConsent && a.explained_by === 'template'}
          onAsk={onAsk}
          onReport={onReport}
          onPickPlace={onPickPlace}
          onAgreeCloud={onAgreeCloud}
        />
      ))}

      {turn.reportUrl && !running && (
        <aside className="report" id="report" aria-label="최종 제안서">
          <img src={hello} alt="" width={40} height={40} />
          <div className="report-text">
            <strong>최종 제안서가 준비됐어요</strong>
            <p className="muted small">세 단계의 결과와 근거표, SQL, 한계를 한 문서로 묶었어요. 열어서 인쇄하면 PDF로 저장할 수 있어요</p>
          </div>
          <a className="btn btn-dark" href={turn.reportUrl} target="_blank" rel="noreferrer">
            제안서 열기 <Icon name="external" />
          </a>
          <a className="btn btn-outline" href={`${turn.reportUrl}?download=true`}>
            <Icon name="download" /> HTML로 내려받기
          </a>
        </aside>
      )}
    </div>
  )
}
