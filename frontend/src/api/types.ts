/** 백엔드 API의 모양. schema.d.ts 는 `npm run gen:api` 로 OpenAPI 명세에서 만들어요 (직접 고치지 않아요). */
import type { components } from './schema'

type S = components['schemas']

export type Answer = S['Answer']
export type Badge = S['Badge']
export type ChartSpec = S['ChartSpec']
export type Series = S['Series']
export type MapSpec = S['MapSpec']
export type MapPoint = S['MapPoint']
export type EvidenceTable = S['EvidenceTable']
export type Suggestion = S['Suggestion']
export type NextQuestion = S['NextQuestion']
export type Verification = S['Verification']
export type Check = S['Check']
export type StepLog = S['StepLog']
export type ChainResult = S['ChainResult']
export type ConfirmCard = S['ConfirmCard']
export type Chip = S['Chip']
/** 서버가 돌려주는 해석 (모든 값이 있어요). */
export type ParsedQuery = S['ParsedQuery-Output']
/** 서버로 보내는 해석. */
export type QueryInput = S['ParsedQuery-Input']
/** 확인 카드에서 고친 값 (바꿀 것만 담아요). */
export type QueryPatch = Partial<QueryInput>

export type Bootstrap = S['BootstrapOut']
export type Status = S['StatusOut']
export type ModeOption = S['ModeOption']
export type Place = S['PlaceOut']
export type Options = S['OptionsOut']
export type SuggestedGroup = S['SuggestedGroup']
export type Health = S['HealthOut']
export type CardOut = S['CardOut']
export type AnswerOut = S['AnswerOut']
export type AskOut = S['AskOut']
export type ChainOut = S['ChainOut']
export type ReportOut = S['ReportOut']
export type ModesIn = S['ModesIn']

/** 스트리밍 응답(SSE)의 진행 알림. */
export type Progress =
  | { kind: 'start' }
  | { kind: 'stage'; stage: number; title: string; place: string | null }
  | { kind: 'tool'; tool: string; label: string; ok: boolean; seconds: number }
  | { kind: 'llm'; purpose: string; label: string; attempt: number }
  | { kind: 'llm_result'; purpose: string; attempt: number; ok: boolean; note: string }

/** 스트리밍이 끝날 때 오는 요약. */
export interface StreamDone {
  session_id: string
  kind: 'answer' | 'chain'
  elapsed: number
  place_name?: string
  report_url?: string | null
}

export interface StreamHandlers {
  onProgress?: (p: Progress) => void
  onAnswer?: (a: Answer) => void
}
