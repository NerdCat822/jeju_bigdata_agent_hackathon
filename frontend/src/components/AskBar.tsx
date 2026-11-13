import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Spinner } from './Icon'

interface Props {
  busy: boolean
  busyLabel: string | null
  chips: { label: string; question: string }[]
  /** 직접 쓴 질문은 확인 카드를 먼저 보여 주고, 칩은 바로 실행해요. */
  onAsk: (question: string, autoRun: boolean) => void
}

export function AskBar({ busy, busyLabel, chips, onAsk }: Props): ReactNode {
  const [text, setText] = useState('')
  const submit = (e: FormEvent): void => {
    e.preventDefault()
    if (!text.trim() || busy) return
    onAsk(text, false)
    setText('')
  }
  return (
    <div className="ask">
      <form className="ask-form" onSubmit={submit} role="search">
        <label className="sr-only" htmlFor="ask-input">
          질문
        </label>
        <input
          id="ask-input"
          className="ask-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="예: 성산읍 청년 인구 왜 줄었어?"
          maxLength={500}
          autoComplete="off"
        />
        <button className="btn btn-accent ask-button" type="submit" disabled={busy || !text.trim()}>
          {busy ? (
            <>
              <Spinner /> {busyLabel ?? '처리 중'}
            </>
          ) : (
            '묻기'
          )}
        </button>
      </form>
      {chips.length > 0 && (
        <div className="chip-row" aria-label="이어서 물어볼 질문">
          {chips.map((c) => (
            <button key={c.question} type="button" className="chip chip-button" disabled={busy} onClick={() => onAsk(c.question, true)}>
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
