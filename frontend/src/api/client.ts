/** 백엔드 웹 API 호출. 화면은 이 파일의 함수만 써요. */
import { SseParser } from '../lib/sse'
import type {
  Answer,
  AnswerOut,
  AskOut,
  Bootstrap,
  CardOut,
  ChainOut,
  Health,
  ModesIn,
  Progress,
  QueryInput,
  ReportOut,
  Status,
  StreamDone,
  StreamHandlers,
} from './types'

/** 서버가 알려 준 오류. message 는 화면에 그대로 보여 줄 수 있는 문장이에요. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

const OFFLINE = '백엔드 서버에 연결하지 못했어요. `python -m meomulmeong serve` 가 켜져 있는지 확인해 주세요.'

// 화면이 놓인 자리. 주소 맨 위에 있으면 '' 이고, 상대 경로로 빌드한 배포본에서는 '.' 이에요.
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

/**
 * 서버 경로(/api/...)를 화면이 놓인 자리 기준 주소로 바꿔요.
 * 화면이 게이트웨이 뒤 하위 경로(예: /meomulmeong/)에 걸려 있어도 API 를 그 아래에서 찾아요.
 */
export const apiUrl = (path: string): string => `${BASE}${path}`

/** 서버가 준 제안서 주소도 같은 기준으로 바꿔요. 화면은 받은 주소를 그대로 링크에 써요. */
function located<T extends { report_url?: string | null }>(out: T): T {
  return out.report_url ? { ...out, report_url: apiUrl(out.report_url) } : out
}

async function toError(res: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `요청을 처리하지 못했어요. (HTTP ${res.status})`
  try {
    const body = (await res.json()) as { detail?: unknown }
    const d = body.detail
    if (d && typeof d === 'object' && !Array.isArray(d)) {
      const o = d as { code?: string; message?: string }
      code = o.code ?? code
      message = o.message ?? message
    } else if (Array.isArray(d)) {
      code = 'invalid_input'
      message = '입력 값을 확인해 주세요.'
    } else if (typeof d === 'string') {
      message = d
    }
  } catch {
    // JSON 이 아닌 응답(프록시 오류 등)은 기본 문장을 써요.
  }
  return new ApiError(message, code, res.status)
}

async function call<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(OFFLINE, 'offline', 0)
  }
  if (!res.ok) throw await toError(res)
  return (await res.json()) as T
}

/** 스트리밍 경로를 불러 진행 알림과 답을 차례로 넘겨주고, 끝나면 요약을 돌려줘요. */
async function stream(path: string, body: unknown, on: StreamHandlers, signal?: AbortSignal): Promise<StreamDone> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(OFFLINE, 'offline', 0)
  }
  if (!res.ok || !res.body) throw await toError(res)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  let done: StreamDone | null = null
  for (;;) {
    const chunk = await reader.read()
    if (chunk.done) break
    for (const ev of parser.push(decoder.decode(chunk.value, { stream: true }))) {
      if (ev.event === 'progress') on.onProgress?.(ev.data as Progress)
      else if (ev.event === 'answer') on.onAnswer?.(ev.data as Answer)
      else if (ev.event === 'done') done = ev.data as StreamDone
      else if (ev.event === 'error') {
        const d = ev.data as { code?: string; message?: string }
        throw new ApiError(d.message ?? '처리하다 오류가 났어요.', d.code ?? 'error', 200)
      }
    }
  }
  if (!done) throw new ApiError('응답이 중간에 끊겼어요. 다시 시도해 주세요.', 'stream_closed', 200)
  return located(done)
}

export const api = {
  health: (): Promise<Health> => call('/api/health'),
  bootstrap: (): Promise<Bootstrap> => call('/api/bootstrap'),
  status: (): Promise<Status> => call('/api/status'),
  setModes: (body: ModesIn): Promise<Status> => call('/api/modes', body),
  understand: (question: string, session_id: string | null): Promise<CardOut> =>
    call('/api/understand', { question, session_id }),
  confirm: (query: QueryInput, session_id: string | null): Promise<CardOut> =>
    call('/api/confirm', { query, session_id }),
  run: (query: QueryInput, session_id: string | null): Promise<AnswerOut> => call('/api/run', { query, session_id }),
  ask: (question: string, session_id: string | null): Promise<AskOut> =>
    call<AskOut>('/api/ask', { question, session_id }).then(located),
  chain: (place: string, session_id: string | null, with_report = true): Promise<ChainOut> =>
    call<ChainOut>('/api/chain', { place, session_id, with_report }).then(located),
  runStream: (query: QueryInput, session_id: string | null, on: StreamHandlers, signal?: AbortSignal) =>
    stream('/api/run/stream', { query, session_id }, on, signal),
  askStream: (question: string, session_id: string | null, on: StreamHandlers, signal?: AbortSignal) =>
    stream('/api/ask/stream', { question, session_id }, on, signal),
  chainStream: (place: string, session_id: string | null, on: StreamHandlers, signal?: AbortSignal) =>
    stream('/api/chain/stream', { place, session_id, with_report: true }, on, signal),
  report: (session_id: string, place: string | null): Promise<ReportOut> =>
    call<ReportOut>('/api/reports', { session_id, place }).then((out) => ({ ...out, url: apiUrl(out.url) })),
  consent: (session_id: string, consent: boolean): Promise<{ session_id: string; consent: boolean }> =>
    call(`/api/sessions/${encodeURIComponent(session_id)}/cloud-consent`, { consent }),
}

export type Api = typeof api
