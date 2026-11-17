import { useState } from 'react'
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
  template: '숫자는 SQL이, 문장은 정해진 규칙이 만들어요',
  anthropic: '숫자는 SQL이 만들고 Claude가 문장을 다듬어요. 집계한 지표만 보내요',
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
  // 좁은 화면에서는 메뉴를 접어 두고 질문창과 본문을 먼저 보여 줘요 (넓은 화면에서는 늘 펼쳐져 있어요)
  const [open, setOpen] = useState(false)
  const place = currentPlace(state)
  const type = place ? placeType(state, place) : null
  const active = state.turns.find((t) => t.id === state.activeId) ?? null
  const activeStages = new Set(active?.answers.map((a) => a.stage) ?? [])
  const report = active?.reportUrl ?? null
  const history = [...state.turns].reverse().slice(0, 6)
  // 실데이터나 센터 데이터가 있으면 샘플 단추는 감춰요. 샘플만 있거나 지금 샘플을 보고 있을 때만 보여 줘요.
  const hasReal = status.modes.data.some((m) => m.mode !== 'synthetic' && m.available)
  const dataModes = status.modes.data.filter((m) => m.mode !== 'synthetic' || m.current || !hasReal)
  // 배포본처럼 모드가 정해져 있으면 고르는 단추 대신 지금 모드만 글로 보여 줘요 (모드는 서버 전체에 걸려요)
  const locked = status.modes.locked
  // 센터 데이터는 센터 PC에만 있어요. 회색 단추만 두면 '데이터가 없나?' 싶어서 글로 알려 줘요
  const centerElsewhere = status.modes.data.some((m) => m.mode === 'center' && !m.available && !m.current)

  return (
    <aside className={`side${open ? ' is-open' : ''}`} aria-label="머물멍 메뉴">
      <div className="side-top">
        <button type="button" className="brand" onClick={() => actions.selectTurn(null)} aria-label="머물멍 첫 화면으로">
          <img src={mascot} alt="" width={28} height={28} />
          <span>머물멍</span>
        </button>
        <button type="button" className="side-toggle btn btn-outline" aria-expanded={open} aria-controls="side-menu" onClick={() => setOpen((v) => !v)}>
          {open ? '메뉴 닫기' : '메뉴'}
        </button>
      </div>
      <div className="side-menu" id="side-menu">
        <section className="side-block" aria-labelledby="side-data">
          <h2 id="side-data" className="side-label">
            데이터
          </h2>
          {locked ? (
            <p className="side-value">{status.data_badge}</p>
          ) : (
            <div className="seg" role="group" aria-labelledby="side-data">
              {dataModes.map((m) => (
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
          )}
          {centerElsewhere && <p className="side-hint">센터 데이터는 센터 PC에서만 열 수 있어요</p>}
          <button type="button" className="link-button" onClick={onDataInfo}>
            수록 기간과 출처
          </button>
        </section>

        <section className="side-block" aria-labelledby="side-llm">
          <h2 id="side-llm" className="side-label">
            AI 설명
          </h2>
          {locked ? (
            <p className="side-value">{status.llm_label}</p>
          ) : (
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
          )}
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
          <p className="side-hint">{place ? `${josa(place, '을를')} 세 단계로 한 번에 봐요` : '먼저 지도나 목록에서 읍면동을 골라 주세요'}</p>
        </div>
      </div>
    </aside>
  )
}
