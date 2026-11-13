import type { ReactNode } from 'react'
import type { Bootstrap } from '../api/types'
import mascot from '../assets/mascot-hello.png'
import { josa } from '../lib/format'
import type { AgentActions, AgentState } from '../state/agent'
import { currentPlace, findStageTurn } from '../state/agent'
import { Icon } from './Icon'
import { TypeMark } from './TypeMark'
import { isTypeCode } from './viz/palette'

interface Props {
  state: AgentState
  boot: Bootstrap
  actions: AgentActions
  onDataInfo: () => void
}

const LLM_HINT: Record<string, string> = {
  template: '숫자는 SQL, 문장은 규칙이 만들어요',
  anthropic: '집계한 지표만 보내고, 보내기 전에 미리 보여 줘요',
}

/** 그 읍면동의 활력 유형 (이미 진단한 적이 있을 때만 알아요). */
function placeType(state: AgentState, place: string): string | null {
  for (let i = state.turns.length - 1; i >= 0; i--) {
    for (const a of state.turns[i].answers) {
      const t = a.stage_output.type
      if (a.ok && a.query.place_name === place && isTypeCode(t)) return t
    }
  }
  return null
}

export function Sidebar({ state, boot, actions, onDataInfo }: Props): ReactNode {
  const { status, options } = boot
  const place = currentPlace(state)
  const type = place ? placeType(state, place) : null
  const active = state.turns.find((t) => t.id === state.activeId) ?? null
  const activeStages = new Set(active?.answers.map((a) => a.stage) ?? [])
  const report = active?.reportUrl ?? null
  const history = [...state.turns].reverse().slice(0, 6)

  return (
    <aside className="side" aria-label="머물멍 메뉴">
      <button type="button" className="brand" onClick={() => actions.selectTurn(null)} aria-label="머물멍 첫 화면으로">
        <img src={mascot} alt="" width={28} height={28} />
        <span>머물멍</span>
      </button>

      <section className="side-block" aria-labelledby="side-data">
        <h2 id="side-data" className="side-label">
          데이터
        </h2>
        <div className="seg" role="group" aria-labelledby="side-data">
          {status.modes.data.map((m) => (
            <button
              key={m.mode}
              type="button"
              className={`seg-item${m.current ? ' is-on' : ''}`}
              aria-pressed={m.current}
              disabled={state.busy || (!m.available && !m.current)}
              title={m.available ? undefined : '이 데이터의 창고가 아직 없어요 (build-data 로 만들어요)'}
              onClick={() => !m.current && void actions.setModes({ data_mode: m.mode as 'synthetic' | 'hub' | 'center' })}
            >
              {m.label.replace(' 데이터', '')}
            </button>
          ))}
        </div>
        <button type="button" className="link-button" onClick={onDataInfo}>
          수록 기간과 출처
        </button>
      </section>

      <section className="side-block" aria-labelledby="side-llm">
        <h2 id="side-llm" className="side-label">
          LLM 모드
        </h2>
        <select
          className="select"
          aria-labelledby="side-llm"
          value={status.llm_mode}
          disabled={state.busy}
          onChange={(e) => void actions.setModes({ llm_mode: e.target.value as 'template' | 'anthropic' })}
        >
          {status.modes.llm.map((m) => (
            <option key={m.mode} value={m.mode} disabled={m.available === false}>
              {m.label}
              {m.available === false ? ' (API 키 없음)' : ''}
            </option>
          ))}
        </select>
        <p className="side-hint">{LLM_HINT[status.llm_mode] ?? ''}</p>
      </section>

      <nav className="side-block" aria-labelledby="side-stage">
        <h2 id="side-stage" className="side-label">
          단계
        </h2>
        {place && (
          <p className="place-now">
            {type ? <TypeMark code={type} size={16} /> : <Icon name="pin" />}
            {place}
          </p>
        )}
        <ul className="nav-list">
          {options.stages.map((s) => {
            const here = activeStages.has(s.stage)
            const done = !!place && !!findStageTurn(state, place, s.stage)
            return (
              <li key={s.stage}>
                <button
                  type="button"
                  className={`nav-row${here ? ' is-on' : ''}`}
                  aria-current={here ? 'step' : undefined}
                  disabled={state.busy}
                  onClick={() => actions.openStage(s.stage)}
                >
                  <span className="step-no" aria-hidden="true">
                    {s.stage}
                  </span>
                  <span className="nav-label">{s.title}</span>
                  {done && !here && <Icon name="check" />}
                </button>
              </li>
            )
          })}
          <li>
            {report ? (
              <a className="nav-row" href={report} target="_blank" rel="noreferrer">
                <Icon name="doc" /> <span className="nav-label">최종 제안서 열기</span> <Icon name="external" />
              </a>
            ) : (
              <button type="button" className="nav-row" disabled={state.busy} onClick={() => void actions.makeReport()}>
                <Icon name="doc" /> <span className="nav-label">최종 제안서</span>
              </button>
            )}
          </li>
        </ul>
      </nav>

      {history.length > 0 && (
        <section className="side-block side-history" aria-labelledby="side-history">
          <h2 id="side-history" className="side-label">
            지난 질문
          </h2>
          <ul className="nav-list">
            {history.map((t) => (
              <li key={t.id}>
                <button type="button" className={`nav-row is-small${t.id === state.activeId ? ' is-on' : ''}`} onClick={() => actions.selectTurn(t.id)}>
                  <span className="nav-label">{t.question}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="side-foot">
        <button type="button" className="btn btn-dark btn-wide" disabled={state.busy} onClick={() => actions.runChain()}>
          처음부터 끝까지
        </button>
        <p className="side-hint">{place ? `${josa(place, '을를')} 세 단계로 한 번에 봐요` : '읍면동 하나를 세 단계로 한 번에 봐요'}</p>
      </div>
    </aside>
  )
}
