/** 테스트용 예시 응답. 실제 API(샘플 데이터, 템플릿 모드)에서 뽑은 값이에요. */
import { vi } from 'vitest'
import type { Api } from '../api/client'
import type { Answer, Bootstrap, CardOut, ChainOut, ConfirmCard, Progress, StreamHandlers } from '../api/types'
import bootstrapJson from './fixtures/bootstrap.json'
import cardJson from './fixtures/card.json'
import chainJson from './fixtures/chain.json'
import failedJson from './fixtures/failed.json'

export const bootstrap = bootstrapJson as unknown as Bootstrap
export const chain = chainJson as unknown as ChainOut
export const cardOut = cardJson as unknown as CardOut
export const failed = failedJson as unknown as Answer
export const [stage1, stage2, stage3] = chain.chain.answers

export function cardFor(question: string): ConfirmCard {
  const base = cardOut.card
  if (question.includes('처음부터 끝까지')) {
    return { ...base, query: { ...base.query, question, intent: 'chain', wants_cause: false }, warnings: [], chips: [...base.chips.slice(0, 3), { label: '질문', value: '처음부터 끝까지' }] }
  }
  if (question.includes('날씨')) {
    return { ...base, runnable: false, warnings: ['읍면동을 하나 골라 주세요. (예: 성산읍, 구좌읍, 노형동)'], query: { ...base.query, question, place_kind: null, place_key: null, place_name: null } }
  }
  if (question.includes('누가 올까')) {
    return { ...base, query: { ...base.query, question, stage: 2, intent: 'shift', wants_cause: false }, warnings: [] }
  }
  return { ...base, query: { ...base.query, question } }
}

const tool = (name: string, label: string): Progress => ({ kind: 'tool', tool: name, label, ok: true, seconds: 0.02 })

/** 서버 없이 화면을 시험하는 가짜 API. 필요한 함수만 바꿔 끼울 수 있어요. */
export function fakeApi(overrides: Partial<Api> = {}): Api {
  const base: Api = {
    health: vi.fn(async () => ({ ok: true, ready: true, message: null })),
    bootstrap: vi.fn(async () => bootstrap),
    status: vi.fn(async () => bootstrap.status),
    setModes: vi.fn(async (body) => ({
      ...bootstrap.status,
      llm_mode: body.llm_mode ?? bootstrap.status.llm_mode,
      data_mode: body.data_mode ?? bootstrap.status.data_mode,
    })),
    understand: vi.fn(async (question: string, sid: string | null) => ({ session_id: sid ?? 'sess-1', card: cardFor(question) })),
    confirm: vi.fn(async (query, sid: string | null) => {
      const merged = { ...cardOut.card.query, ...query }
      const place = merged.place_name ?? null
      return {
        session_id: sid ?? 'sess-1',
        card: {
          ...cardOut.card,
          query: { ...merged, place_kind: place ? 'emd' : null, place_key: place ? 'x' : null },
          chips: [{ label: '장소', value: place ?? '-' }, ...cardOut.card.chips.slice(1)],
        } as ConfirmCard,
      }
    }),
    run: vi.fn(async (_q, sid: string | null) => ({ session_id: sid ?? 'sess-1', answer: stage1 })),
    ask: vi.fn(async (_q: string, sid: string | null) => ({ session_id: sid ?? 'sess-1', kind: 'answer' as const, answer: stage1, chain: null, report_url: null })),
    chain: vi.fn(async () => chain),
    runStream: vi.fn(async (query, sid: string | null, on: StreamHandlers) => {
      on.onProgress?.({ kind: 'start' })
      on.onProgress?.(tool('s1_trend', '청년 인구 추이 계산'))
      const answer = query.intent === 'shift' ? stage2 : query.question?.includes('날씨') ? failed : stage1
      on.onAnswer?.(answer)
      return { session_id: sid ?? 'sess-1', kind: 'answer' as const, elapsed: 0.05 }
    }),
    askStream: vi.fn(async (_q: string, sid: string | null, on: StreamHandlers) => {
      on.onAnswer?.(stage1)
      return { session_id: sid ?? 'sess-1', kind: 'answer' as const, elapsed: 0.05 }
    }),
    chainStream: vi.fn(async (place: string, sid: string | null, on: StreamHandlers) => {
      on.onProgress?.({ kind: 'start' })
      for (const a of chain.chain.answers) {
        on.onProgress?.({ kind: 'stage', stage: a.stage ?? 0, title: `단계 ${a.stage}`, place })
        on.onAnswer?.(a)
      }
      return { session_id: sid ?? 'sess-1', kind: 'chain' as const, elapsed: 0.1, place_name: place, report_url: '/api/reports/sample.html' }
    }),
    report: vi.fn(async () => ({ filename: 'sample.html', url: '/api/reports/sample.html' })),
    consent: vi.fn(async (sid: string, consent: boolean) => ({ session_id: sid, consent })),
  }
  return { ...base, ...overrides }
}
