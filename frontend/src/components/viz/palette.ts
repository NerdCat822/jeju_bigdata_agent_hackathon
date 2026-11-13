/**
 * 차트 색. 계열(무엇인지)을 구분하는 색은 정해진 순서대로만 써요 (돌려 쓰지 않아요).
 * 값은 styles.css 의 --series-* 에 있고, 색각 이상 구분 검사를 통과한 순서예요.
 */
export const SERIES_COLORS = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
] as const

export const seriesColor = (i: number): string => SERIES_COLORS[Math.min(i, SERIES_COLORS.length - 1)]

/** 읍면동 활력 유형의 색. 지도에서는 글자(A~D)를 함께 써서 색만으로 구분하지 않게 해요. */
export const TYPE_COLORS: Record<string, string> = {
  A: 'var(--type-a)',
  B: 'var(--type-b)',
  C: 'var(--type-c)',
  D: 'var(--type-d)',
  유지: 'var(--type-keep)',
}
/** 색 위에 올리는 글자색. 노란 바탕(D)만 어두운 글자를 써요. */
export const TYPE_INK: Record<string, string> = { A: '#ffffff', B: '#ffffff', C: '#ffffff', D: '#0b0b0b', 유지: '#ffffff' }
