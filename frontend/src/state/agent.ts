/** 화면 상태와 동작. 질문 하나가 Turn 하나예요: 확인 카드 → 진행 → 답(연계 실행은 세 개). */
import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from 'react'
import { ApiError, api as realApi } from '../api/client'
import type { Api } from '../api/client'
import type { Answer, Bootstrap, ConfirmCard, ModesIn, Progress, QueryPatch, Status } from '../api/types'

export type TurnStatus = 'understanding' | 'confirm' | 'running' | 'done' | 'error'

export interface Turn {
  id: string
  question: string
  card: ConfirmCard | null
  /** 카드를 고친 뒤 아직 다시 실행하지 않았어요. */
  dirty: boolean
  status: TurnStatus
  progress: Progress[]
  answers: Answer[]
  kind: 'answer' | 'chain' | null
  reportUrl: string | null
  error: string | null
  startedAt: number | null
  elapsed: number | null
}

export interface Notice {
  tone: 'info' | 'warn'
  text: string
}

export interface AgentState {
  boot: Bootstrap | null
  bootError: string | null
  sessionId: string | null
  turns: Turn[]
  activeId: string | null
  /** 서버는 분석을 한 번에 하나씩 해요. 실행 중에는 새 질문을 막아요. */
  busy: boolean
  busyLabel: string | null
  /** 홈 지도에서 고른 읍면동. */
  pickedPlace: string | null
  notice: Notice | null
  cloudConsent: boolean
}

type Action =
  | { type: 'boot'; boot: Bootstrap }
  | { type: 'bootError'; message: string }
  | { type: 'status'; status: Status; reset: boolean }
  | { type: 'session'; id: string }
  | { type: 'add'; turn: Turn }
  | { type: 'patch'; id: string; patch: Partial<Turn> }
  | { type: 'progress'; id: string; item: Progress }
  | { type: 'answer'; id: string; answer: Answer }
  | { type: 'active'; id: string | null }
  | { type: 'busy'; busy: boolean; label?: string | null }
  | { type: 'pick'; place: string | null }
  | { type: 'notice'; notice: Notice | null }
  | { type: 'consent'; consent: boolean }

export const initialState: AgentState = {
  boot: null,
  bootError: null,
  sessionId: null,
  turns: [],
  activeId: null,
  busy: false,
  busyLabel: null,
  pickedPlace: null,
  notice: null,
  cloudConsent: false,
}

const mapTurn = (s: AgentState, id: string, f: (t: Turn) => Turn): AgentState => ({
  ...s,
  turns: s.turns.map((t) => (t.id === id ? f(t) : t)),
})

export function reducer(s: AgentState, a: Action): AgentState {
  switch (a.type) {
    case 'boot':
      return { ...s, boot: a.boot, bootError: null }
    case 'bootError':
      return { ...s, bootError: a.message }
    case 'status':
      if (!s.boot) return s
      return a.reset
        ? { ...initialState, boot: { ...s.boot, status: a.status }, notice: s.notice }
        : { ...s, boot: { ...s.boot, status: a.status } }
    case 'session':
      return s.sessionId === a.id ? s : { ...s, sessionId: a.id }
    case 'add':
      return { ...s, turns: [...s.turns, a.turn], activeId: a.turn.id }
    case 'patch':
      return mapTurn(s, a.id, (t) => ({ ...t, ...a.patch }))
    case 'progress':
      return mapTurn(s, a.id, (t) => ({ ...t, progress: [...t.progress, a.item] }))
    case 'answer':
      return mapTurn(s, a.id, (t) => ({ ...t, answers: [...t.answers, a.answer] }))
    case 'active':
      return { ...s, activeId: a.id }
    case 'busy':
      return { ...s, busy: a.busy, busyLabel: a.busy ? (a.label ?? null) : null }
    case 'pick':
      return { ...s, pickedPlace: a.place }
    case 'notice':
      return { ...s, notice: a.notice }
    case 'consent':
      return { ...s, cloudConsent: a.consent }
  }
}

/** 단계마다 대표 질문. 사이드바의 단계 버튼과 지도에서 쓰는 질문이에요. */
export const STAGE_QUESTION: Record<number, (place: string) => string> = {
  1: (p) => `${p} 청년 인구 진단`,
  2: (p) => `${p}에 누가 올까?`,
  3: (p) => `${p} 어떻게 데려올까?`,
}
export const chainQuestion = (place: string): string => `${place} 처음부터 끝까지`

/** 지금 보고 있는 읍면동 이름 (없으면 null). */
export function currentPlace(s: AgentState): string | null {
  const t = s.turns.find((x) => x.id === s.activeId)
  if (t) {
    for (let i = t.answers.length - 1; i >= 0; i--) {
      const q = t.answers[i].query
      if (q.place_kind === 'emd' && q.place_name) return q.place_name
    }
    const q = t.card?.query
    if (q?.place_kind === 'emd' && q.place_name) return q.place_name
  }
  return s.pickedPlace
}

/** 그 읍면동·단계의 답이 이미 있는 Turn. 있으면 다시 실행하지 않고 그 화면으로 가요. */
export function findStageTurn(s: AgentState, place: string, stage: number): Turn | null {
  for (let i = s.turns.length - 1; i >= 0; i--) {
    const t = s.turns[i]
    if (t.answers.some((a) => a.ok && a.stage === stage && a.query.place_name === place)) return t
  }
  return null
}

const errorText = (e: unknown): string =>
  e instanceof ApiError ? e.message : e instanceof Error ? e.message : '알 수 없는 오류가 났어요.'

let seq = 0
const newId = (): string => `t${Date.now().toString(36)}${(seq++).toString(36)}`

export interface AgentActions {
  reload: () => Promise<void>
  ask: (question: string, opts?: { autoRun?: boolean }) => Promise<void>
  runTurn: (id: string) => Promise<void>
  editCard: (id: string, patch: QueryPatch) => Promise<void>
  openStage: (stage: number) => void
  runChain: (place?: string | null) => void
  makeReport: (place?: string | null) => Promise<void>
  setModes: (patch: ModesIn) => Promise<void>
  agreeCloud: () => Promise<void>
  selectTurn: (id: string | null) => void
  pickPlace: (place: string | null) => void
  dismissNotice: () => void
}

export function useAgent(api: Api = realApi): { state: AgentState; actions: AgentActions } {
  const [state, dispatch] = useReducer(reducer, initialState)
  // 비동기 동작이 가장 최근 상태를 읽을 수 있게 둬요 (그리기가 끝난 직후에 맞춰요).
  const ref = useRef(state)
  useLayoutEffect(() => {
    ref.current = state
  }, [state])
  const editSeq = useRef(0)
  // 세션 번호는 화면이 다시 그려지기 전에도 다음 요청에 바로 써야 해요 (해석 → 실행이 한 흐름으로 이어져요).
  const session = useRef<string | null>(null)
  const keepSession = useCallback((id: string) => {
    session.current = id
    dispatch({ type: 'session', id })
  }, [])

  const reload = useCallback(async () => {
    try {
      const health = await api.health()
      if (!health.ready) {
        dispatch({ type: 'bootError', message: health.message ?? '데이터가 아직 준비되지 않았어요.' })
        return
      }
      dispatch({ type: 'boot', boot: await api.bootstrap() })
    } catch (e) {
      dispatch({ type: 'bootError', message: errorText(e) })
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const execute = useCallback(
    async (id: string, card: ConfirmCard) => {
      dispatch({
        type: 'patch',
        id,
        patch: { status: 'running', progress: [], answers: [], error: null, dirty: false, kind: null, reportUrl: null, startedAt: Date.now(), elapsed: null },
      })
      dispatch({ type: 'busy', busy: true, label: '분석하는 중' })
      const on = {
        onProgress: (item: Progress) => dispatch({ type: 'progress', id, item }),
        onAnswer: (answer: Answer) => dispatch({ type: 'answer', id, answer }),
      }
      try {
        const q = card.query
        const sid = session.current
        const done =
          q.intent === 'chain'
            ? q.place_name
              ? await api.chainStream(q.place_name, sid, on)
              : await api.askStream(q.question, sid, on) // 장소를 에이전트가 고르는 연계 실행
            : await api.runStream(q, sid, on)
        keepSession(done.session_id)
        dispatch({ type: 'patch', id, patch: { status: 'done', kind: done.kind, elapsed: done.elapsed, reportUrl: done.report_url ?? null } })
      } catch (e) {
        dispatch({ type: 'patch', id, patch: { status: 'error', error: errorText(e) } })
      } finally {
        dispatch({ type: 'busy', busy: false })
      }
    },
    [api, keepSession],
  )

  const ask = useCallback(
    async (question: string, opts: { autoRun?: boolean } = {}) => {
      const text = question.trim()
      if (!text || ref.current.busy) return
      const id = newId()
      dispatch({
        type: 'add',
        turn: { id, question: text, card: null, dirty: false, status: 'understanding', progress: [], answers: [], kind: null, reportUrl: null, error: null, startedAt: null, elapsed: null },
      })
      dispatch({ type: 'busy', busy: true, label: '질문을 읽는 중' })
      let card: ConfirmCard | null = null
      try {
        const out = await api.understand(text, session.current)
        keepSession(out.session_id)
        card = out.card
        dispatch({ type: 'patch', id, patch: { card, status: 'confirm' } })
      } catch (e) {
        dispatch({ type: 'patch', id, patch: { status: 'error', error: errorText(e) } })
      } finally {
        dispatch({ type: 'busy', busy: false })
      }
      if (card && opts.autoRun && card.runnable) await execute(id, card)
    },
    [api, execute, keepSession],
  )

  const runTurn = useCallback(
    async (id: string) => {
      const t = ref.current.turns.find((x) => x.id === id)
      if (!t?.card || ref.current.busy) return
      await execute(id, t.card)
    },
    [execute],
  )

  const editCard = useCallback(
    async (id: string, patch: QueryPatch) => {
      const t = ref.current.turns.find((x) => x.id === id)
      if (!t?.card) return
      const mine = ++editSeq.current
      try {
        const out = await api.confirm({ ...t.card.query, ...patch }, session.current)
        if (mine !== editSeq.current) return // 더 나중에 고친 값이 있으면 그쪽을 써요
        keepSession(out.session_id)
        dispatch({ type: 'patch', id, patch: { card: out.card, dirty: true } })
      } catch (e) {
        dispatch({ type: 'notice', notice: { tone: 'warn', text: errorText(e) } })
      }
    },
    [api, keepSession],
  )

  const selectTurn = useCallback((id: string | null) => dispatch({ type: 'active', id }), [])
  const pickPlace = useCallback((place: string | null) => dispatch({ type: 'pick', place }), [])
  const dismissNotice = useCallback(() => dispatch({ type: 'notice', notice: null }), [])

  const needPlace = useCallback(() => {
    dispatch({ type: 'active', id: null })
    dispatch({ type: 'notice', notice: { tone: 'info', text: '먼저 지도에서 읍면동을 하나 골라 주세요.' } })
  }, [])

  const openStage = useCallback(
    (stage: number) => {
      const s = ref.current
      const place = currentPlace(s)
      if (!place) return needPlace()
      const existing = findStageTurn(s, place, stage)
      if (existing) {
        dispatch({ type: 'active', id: existing.id })
        return
      }
      void ask(STAGE_QUESTION[stage](place), { autoRun: true })
    },
    [ask, needPlace],
  )

  const runChain = useCallback(
    (place?: string | null) => {
      const target = place ?? currentPlace(ref.current)
      if (!target) return needPlace()
      void ask(chainQuestion(target), { autoRun: true })
    },
    [ask, needPlace],
  )

  const makeReport = useCallback(
    async (place?: string | null) => {
      const s = ref.current
      if (s.busy) return
      const target = place ?? currentPlace(s)
      if (!session.current || !target) return needPlace()
      dispatch({ type: 'busy', busy: true, label: '제안서를 만드는 중' })
      try {
        const out = await api.report(session.current, target)
        const active = ref.current.activeId
        if (active) dispatch({ type: 'patch', id: active, patch: { reportUrl: out.url } })
        dispatch({ type: 'notice', notice: { tone: 'info', text: `${target} 최종 제안서를 만들었어요. 답 아래의 제안서 열기를 눌러 보세요.` } })
      } catch (e) {
        dispatch({ type: 'notice', notice: { tone: 'warn', text: errorText(e) } })
      } finally {
        dispatch({ type: 'busy', busy: false })
      }
    },
    [api, needPlace],
  )

  const setModes = useCallback(
    async (patch: ModesIn) => {
      if (ref.current.busy) return
      dispatch({ type: 'busy', busy: true, label: '모드를 바꾸는 중' })
      try {
        const before = ref.current.boot?.status
        const status = await api.setModes(patch)
        const dataChanged = !!before && before.data_mode !== status.data_mode
        if (dataChanged) session.current = null // 데이터가 바뀌면 서버도 대화를 새로 시작해요
        dispatch({ type: 'status', status, reset: dataChanged })
        if (patch.llm_mode && status.llm_mode !== patch.llm_mode) {
          dispatch({ type: 'notice', notice: { tone: 'warn', text: status.llm_note || 'LLM을 쓸 수 없어 템플릿 모드로 실행해요.' } })
        } else if (dataChanged) {
          dispatch({ type: 'notice', notice: { tone: 'info', text: `${status.data_badge}로 바꿨어요. 대화는 새로 시작해요.` } })
        }
      } catch (e) {
        dispatch({ type: 'notice', notice: { tone: 'warn', text: errorText(e) } })
      } finally {
        dispatch({ type: 'busy', busy: false })
      }
    },
    [api],
  )

  const agreeCloud = useCallback(async () => {
    const s = ref.current
    if (!session.current) return
    try {
      await api.consent(session.current, true)
      dispatch({ type: 'consent', consent: true })
      if (s.activeId) await runTurn(s.activeId)
    } catch (e) {
      dispatch({ type: 'notice', notice: { tone: 'warn', text: errorText(e) } })
    }
  }, [api, runTurn])

  const actions = useMemo<AgentActions>(
    () => ({ reload, ask, runTurn, editCard, openStage, runChain, makeReport, setModes, agreeCloud, selectTurn, pickPlace, dismissNotice }),
    [reload, ask, runTurn, editCard, openStage, runChain, makeReport, setModes, agreeCloud, selectTurn, pickPlace, dismissNotice],
  )
  return { state, actions }
}
