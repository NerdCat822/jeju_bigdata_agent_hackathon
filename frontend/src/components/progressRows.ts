import type { Progress } from '../api/types'
import { seconds } from '../lib/format'

export interface Row {
  key: string
  kind: 'stage' | 'step'
  label: string
  state: 'ok' | 'fail' | 'wait'
  note?: string
}

/** 진행 알림을 화면 줄로 바꿔요. LLM 호출은 시작 알림에 결과 알림을 합쳐 한 줄로 보여 줘요. */
export function toRows(items: Progress[], running: boolean): Row[] {
  const rows: Row[] = []
  items.forEach((p, i) => {
    if (p.kind === 'queue') rows.push({ key: `q${i}`, kind: 'step', label: '앞 사람의 분석이 끝나기를 기다리고 있어요', state: 'wait' })
    else if (p.kind === 'stage') rows.push({ key: `s${i}`, kind: 'stage', label: `${p.stage}단계 · ${p.title}`, state: 'ok' })
    else if (p.kind === 'tool') rows.push({ key: `t${i}`, kind: 'step', label: p.label, state: p.ok ? 'ok' : 'fail', note: p.seconds >= 0.1 ? seconds(p.seconds) : undefined })
    else if (p.kind === 'llm') rows.push({ key: `l${i}`, kind: 'step', label: p.attempt > 1 ? `${p.label} (${p.attempt}번째)` : p.label, state: 'wait' })
    else if (p.kind === 'llm_result') {
      const open = [...rows].reverse().find((r) => r.state === 'wait')
      if (open) {
        open.state = p.ok ? 'ok' : 'fail'
        open.note = p.note
      }
    }
  })
  // 결과 알림이 따로 없는 LLM 호출(질문 해석, 조회문 쓰기)은 다음 단계가 시작되면 끝난 것으로 봐요.
  rows.forEach((r, i) => {
    if (r.state === 'wait' && (i < rows.length - 1 || !running)) r.state = 'ok'
  })
  // 기다림이 끝나면 '기다렸어요'로 바꿔 적어요 (분석은 서버에서 한 번에 하나씩 돌아요)
  rows.forEach((r) => {
    if (r.key.startsWith('q') && r.state === 'ok') r.label = '앞 사람의 분석을 기다렸어요'
  })
  return rows
}
