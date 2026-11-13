import type { ReactNode } from 'react'
import { TYPE_COLORS, TYPE_INK } from './viz/palette'

/**
 * 유형 표식: 읍면동 활력 유형(A~D)을 나타내는 작은 동그라미.
 * 지도, 한 줄 결론, 순위표, 사이드바에서 똑같이 써서 어디서 봐도 같은 유형임을 알 수 있어요.
 * 변화가 작은 '유지'는 글자 없이 회색 점이에요.
 */
export function TypeMark({ code, size = 18 }: { code: string; size?: number }): ReactNode {
  const known = code in TYPE_COLORS
  return (
    <span
      className="type-mark"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.58),
        background: known ? TYPE_COLORS[code] : 'var(--type-keep)',
        color: TYPE_INK[code] ?? '#ffffff',
      }}
      aria-hidden="true"
    >
      {known && code !== '유지' ? code : ''}
    </span>
  )
}
