import type { Answer } from '../api/types'
import { modelName } from '../lib/format'

/** 검증 항목 이름. 백엔드 제안서(report/builder.py)와 같은 이름을 써요. */
export const CHECK_LABEL: Record<string, string> = {
  numbers: '숫자 대조',
  pairing: '숫자-지표 짝',
  fidelity: '초안 충실도',
  causal: '인과 표현 가드',
  prediction: '예측·추측 가드',
  references: '참조 대조',
  suggestions: '제안 근거',
  assumption: '가정치 표시',
  periods: '기간 확인',
  export: '반출 게이트',
}

export function explainedBy(a: Answer): string {
  if (a.explained_by === 'llm') {
    const who = a.llm_model ? modelName(a.llm_model) : 'AI'
    const retry = a.verification.retries ? `, 다시 쓰기 ${a.verification.retries}회` : ''
    return `해설: ${who} (검증 통과${retry})`
  }
  if (a.verification.fallback) return '해설: 규칙 문장 (AI 설명이 검증을 통과하지 못해 대체)'
  return '해설: 규칙 문장'
}
