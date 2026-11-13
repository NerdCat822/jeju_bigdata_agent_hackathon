import { afterEach, describe, expect, it, vi } from 'vitest'
import { stage1 } from '../test/fixtures'
import { ApiError, api } from './client'
import type { Progress } from './types'

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** 조각 단위로 흘려보내는 SSE 응답. 조각 경계는 일부러 이벤트 중간에 둬요. */
function sse(chunks: string[]): Response {
  const enc = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

const ev = (event: string, data: unknown): string => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

afterEach(() => vi.unstubAllGlobals())

describe('API 호출', () => {
  it('질문과 세션을 JSON 으로 보내고 응답을 그대로 돌려줘요', async () => {
    const fetchMock = vi.fn(async () => json({ session_id: 's1', card: { runnable: true } }))
    vi.stubGlobal('fetch', fetchMock)
    const out = await api.understand('성산읍 청년 인구 진단', null)
    expect(out.session_id).toBe('s1')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/understand')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ question: '성산읍 청년 인구 진단', session_id: null })
  })

  it('서버가 알려 준 오류 문장과 코드를 전해요', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: { code: 'unknown_place', message: "'없는동네'에 맞는 읍면동을 찾지 못했어요." } }, 404)))
    const err = await api.chain('없는동네', null).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe('unknown_place')
    expect((err as ApiError).status).toBe(404)
    expect((err as ApiError).message).toContain('없는동네')
  })

  it('입력 형식 오류와 연결 실패도 읽을 수 있는 문장으로 바꿔요', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: [{ loc: ['body', 'question'], msg: 'too short' }] }, 422)))
    const bad = (await api.ask('', null).catch((e: unknown) => e)) as ApiError
    expect(bad.code).toBe('invalid_input')
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const off = (await api.bootstrap().catch((e: unknown) => e)) as ApiError
    expect(off.code).toBe('offline')
    expect(off.message).toContain('serve')
  })
})

describe('스트리밍', () => {
  it('진행 알림과 답을 순서대로 넘기고, 끝 요약을 돌려줘요', async () => {
    const whole = ev('progress', { kind: 'start' }) + ev('progress', { kind: 'tool', tool: 's1_trend', label: '청년 인구 추이 계산', ok: true, seconds: 0.03 }) + ev('answer', stage1) + ev('done', { session_id: 's1', kind: 'answer', elapsed: 0.07 })
    const cut = Math.floor(whole.length / 3)
    vi.stubGlobal('fetch', vi.fn(async () => sse([whole.slice(0, cut), whole.slice(cut, cut * 2), whole.slice(cut * 2)])))
    const seen: string[] = []
    const done = await api.runStream(stage1.query, 's1', {
      onProgress: (p: Progress) => seen.push(`progress:${p.kind}`),
      onAnswer: (a) => seen.push(`answer:${a.stage}`),
    })
    expect(seen).toEqual(['progress:start', 'progress:tool', 'answer:1'])
    expect(done).toEqual({ session_id: 's1', kind: 'answer', elapsed: 0.07 })
  })

  it('한글이 조각 경계에서 잘려도 깨지지 않아요', async () => {
    const bytes = new TextEncoder().encode(ev('progress', { kind: 'llm', purpose: 'explain', label: '쉬운 해설 쓰기', attempt: 1 }) + ev('done', { session_id: 's', kind: 'answer', elapsed: 1 }))
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        for (let i = 0; i < bytes.length; i += 7) c.enqueue(bytes.slice(i, i + 7)) // 3바이트 글자가 조각 사이에 걸려요
        c.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))
    const labels: string[] = []
    await api.askStream('q', null, { onProgress: (p) => p.kind === 'llm' && labels.push(p.label) })
    expect(labels).toEqual(['쉬운 해설 쓰기'])
  })

  it('오류 이벤트는 오류로, 끝 요약 없이 끊기면 끊겼다고 알려요', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sse([ev('progress', { kind: 'start' }), ev('error', { code: 'unknown_place', message: '읍면동을 찾지 못했어요.' })])))
    const e1 = (await api.chainStream('없는동네', null, {}).catch((e: unknown) => e)) as ApiError
    expect(e1.code).toBe('unknown_place')
    vi.stubGlobal('fetch', vi.fn(async () => sse([ev('progress', { kind: 'start' })])))
    const e2 = (await api.chainStream('성산읍', null, {}).catch((e: unknown) => e)) as ApiError
    expect(e2.code).toBe('stream_closed')
  })

  it('스트리밍 요청이 거절되면 서버의 오류를 전해요', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: { code: 'warehouse_missing', message: '데이터 창고가 없어요.' } }, 503)))
    const e = (await api.askStream('q', null, {}).catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('warehouse_missing')
    expect(e.status).toBe(503)
  })
})
