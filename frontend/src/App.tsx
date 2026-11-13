import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import hello from './assets/mascot-hello.png'
import { AskBar } from './components/AskBar'
import { DataInfo } from './components/DataInfo'
import { Home } from './components/Home'
import { Icon, Spinner } from './components/Icon'
import { Sidebar } from './components/Sidebar'
import { Toast } from './components/Toast'
import { TurnView } from './components/TurnView'
import type { Api } from './api/client'
import { STAGE_QUESTION, useAgent } from './state/agent'

/** 머물멍 화면. 왼쪽은 모드와 단계, 가운데는 질문 → 확인 카드 → 답. */
export default function App({ api }: { api?: Api }): ReactNode {
  const { state, actions } = useAgent(api)
  const [showData, setShowData] = useState(false)
  const mainRef = useRef<HTMLElement | null>(null)
  const { boot } = state
  const active = state.turns.find((t) => t.id === state.activeId) ?? null

  useEffect(() => {
    mainRef.current?.scrollTo?.({ top: 0 })
  }, [state.activeId])

  const latestYear = useMemo(() => {
    const years = (boot?.status.tables ?? []).flatMap((t) => [...t.period.matchAll(/(\d{4})-\d{2}/g)].map((m) => Number(m[1])))
    return years.length ? Math.max(...years) : null
  }, [boot])

  const chips = useMemo(() => {
    const last = active?.answers[active.answers.length - 1]
    const follow = (last?.next_questions ?? []).filter((n) => n.kind === 'follow_up').map((n) => ({ label: n.label, question: n.question }))
    return follow.slice(0, 3)
  }, [active])

  if (!boot) {
    return (
      <div className="boot">
        <img src={hello} alt="" width={72} height={72} />
        <h1>머물멍</h1>
        {state.bootError ? (
          <>
            <p className="callout is-warn" role="alert">
              <Icon name="alert" /> <span className="pre-line">{state.bootError}</span>
            </p>
            <button type="button" className="btn btn-dark" onClick={() => void actions.reload()}>
              다시 연결
            </button>
          </>
        ) : (
          <p className="muted">
            <Spinner /> 데이터를 불러오고 있어요
          </p>
        )}
      </div>
    )
  }

  const ask = (question: string, autoRun: boolean): void => void actions.ask(question, { autoRun })

  return (
    <div className="app">
      <Sidebar state={state} boot={boot} actions={actions} onDataInfo={() => setShowData(true)} />
      <main className="main" ref={mainRef}>
        <div className="main-inner">
          <div className="topline">
            {active ? (
              <button type="button" className="link-button" onClick={() => actions.selectTurn(null)}>
                <Icon name="home" /> 첫 화면
              </button>
            ) : (
              <span />
            )}
            <ul className="status-line" aria-label="지금 쓰는 데이터와 LLM 모드">
              <li className="tag">{boot.status.data_badge}</li>
              <li>{boot.status.llm_label}</li>
            </ul>
          </div>
          <AskBar busy={state.busy} busyLabel={state.busyLabel} chips={chips} onAsk={ask} />
          {active ? (
            <TurnView
              key={active.id}
              turn={active}
              boot={boot}
              latestYear={latestYear}
              busy={state.busy}
              cloudConsent={state.cloudConsent}
              onRun={() => void actions.runTurn(active.id)}
              onEdit={(patch) => void actions.editCard(active.id, patch)}
              onAsk={(q) => ask(q, true)}
              onReport={() => void actions.makeReport()}
              onPickPlace={(name) => ask(STAGE_QUESTION[1](name), true)}
              onAgreeCloud={() => void actions.agreeCloud()}
            />
          ) : (
            <Home
              boot={boot}
              picked={state.pickedPlace}
              busy={state.busy}
              onAsk={(q) => ask(q, true)}
              onPick={actions.pickPlace}
              onDiagnose={(place) => ask(STAGE_QUESTION[1](place), true)}
              onChain={(place) => actions.runChain(place)}
            />
          )}
        </div>
      </main>
      {showData && <DataInfo status={boot.status} onClose={() => setShowData(false)} />}
      <Toast notice={state.notice} onClose={actions.dismissNotice} />
    </div>
  )
}
