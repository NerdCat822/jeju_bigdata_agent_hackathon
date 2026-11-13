/**
 * 차트 색. 기획서 예시 화면처럼 첫 계열(청년 거주)은 파랑, 둘째(방문자)는 귤색이에요.
 * 범례와 선 끝 값, 표로 보기가 함께 있어서 색만으로 구분하지 않아요.
 */
export const SERIES_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)'] as const

export const seriesColor = (i: number): string => SERIES_COLORS[Math.min(i, SERIES_COLORS.length - 1)]

/** 읍면동 활력 유형의 색. 지도와 유형 표식에서만 써요. 글자(A~D)를 함께 써서 색만으로 구분하지 않아요. */
export const TYPE_COLORS: Record<string, string> = {
  A: 'var(--type-a)',
  B: 'var(--type-b)',
  C: 'var(--type-c)',
  D: 'var(--type-d)',
  유지: 'var(--type-keep)',
}
/** 색 위에 올리는 글자색. 노란 바탕(D)만 어두운 글자를 써요. */
export const TYPE_INK: Record<string, string> = { A: '#ffffff', B: '#ffffff', C: '#ffffff', D: '#2b211b', 유지: '#ffffff' }

/** 값이 유형 코드(A~D, 유지)인지. */
export const isTypeCode = (v: unknown): v is string => typeof v === 'string' && v in TYPE_COLORS
