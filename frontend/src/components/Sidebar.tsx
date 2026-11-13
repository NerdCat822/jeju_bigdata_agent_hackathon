import type { ReactNode } from 'react'
import type { Bootstrap } from '../api/types'
import mascot from '../assets/mascot-hello.png'
import { josa } from '../lib/format'
import type { AgentActions, AgentState } from '../state/agent'
import { currentPlace, findStageTurn } from '../state/agent'
import { Icon } from './Icon'

interface Props {
  state: AgentState
  boot: Bootstrap
  actions: AgentActions
  onDataInfo: () => void
}

const CIRCLED = ['', '①', '②', '③']

export function Sidebar({ state, boot, actions, onDataInfo }: Props): ReactNode {
  const { status, options } = boot
  const place = currentPlace(state)
  const active = state.turns.find((t) => t.id === state.activeId) ?? null
  const activeStages = new Set(active?.answers.map((a) => a.stage) ?? [])
  const report = active?.reportUrl ?? null
  const history = [...state.turns].reverse().slice(0, 6)

  return (
    <aside className="side" aria-label="머물멍 메뉴">
      <button type="button" className="brand" onClick={() => actions.selectTurn(null)} aria-label="머물멍 첫 화면으로">
        <img src={mascot} alt="" width={44} height={44} />
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
          <Icon name="info" size={14} /> 수록 기간과 출처 보기
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
          onChange={(e) => void actions.setModes({ llm_mode: e.target.value as 'template' | 'ollama' | 'anthropic' })}
        >
          {status.modes.llm.map((m) => (
            <option key={m.mode} value={m.mode} disabled={m.available === false}>
              {m.label}
              {m.available === false ? ' (API 키 없음)' : ''}
            </option>
          ))}
        </select>
        <p className="side-hint">
          {status.llm_mode === 'template'
            ? '숫자는 SQL, 문장은 규칙이 만들어요. 밖으로 보내는 것이 없어요.'
            : status.llm_mode === 'ollama'
              ? '이 PC 안의 모델이 쉬운 해설을 쓰고, 검증을 통과한 것만 보여 줘요.'
              : '집계된 지표만 클라우드로 보내요. 보내기 전에 미리보기로 확인해요.'}
        </p>
      </section>

      <nav className="side-block" aria-labelledby="side-stage">
        <h2 id="side-stage" className="side-label">
          단계
        </h2>
        {place && (
          <p className="place-now">
            <Icon name="pin" size={14} /> {place}
          </p>
        )}
        <ul className="stage-nav">
          {options.stages.map((s) => {
            const here = activeStages.has(s.stage)
            const done = !!place && !!findStageTurn(state, place, s.stage)
            return (
              <li key={s.stage}>
                <button
                  type="button"
                  className={`stage-item${here ? ' is-on' : ''}`}
                  aria-current={here ? 'step' : undefined}
                  disabled={state.busy}
                  onClick={() => actions.openStage(s.stage)}
                >
                  <span aria-hidden="true">{CIRCLED[s.stage]}</span>
                  <span className="stage-title">{s.title}</span>
                  {done && !here && <Icon name="check" size={14} />}
                </button>
              </li>
            )
          })}
          <li>
            {report ? (
              <a className="stage-item" href={report} target="_blank" rel="noreferrer">
                <Icon name="doc" /> <span className="stage-title">최종 제안서 열기</span> <Icon name="external" size={14} />
              </a>
            ) : (
              <button type="button" className="stage-item" disabled={state.busy} onClick={() => void actions.makeReport()}>
                <Icon name="doc" /> <span className="stage-title">최종 제안서</span>
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
          <ul>
            {history.map((t) => (
              <li key={t.id}>
                <button type="button" className={`history-item${t.id === state.activeId ? ' is-on' : ''}`} onClick={() => actions.selectTurn(t.id)}>
                  {t.question}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="side-foot">
        <button type="button" className="btn btn-dark btn-wide" disabled={state.busy} onClick={() => actions.runChain()}>
          처음부터 끝까지 <Icon name="play" size={14} />
        </button>
        <p className="side-hint">{place ? `${josa(place, '을를')} 세 단계로 한 번에 봐요.` : '읍면동 하나를 세 단계로 한 번에 봐요.'}</p>
      </div>
    </aside>
  )
}
