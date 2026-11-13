/** 축 눈금과 선형 변환. 차트가 함께 써요. */

export interface Axis {
  lo: number
  hi: number
  ticks: number[]
}

/** 부동소수 잡음과 -0 을 없애요 (-0 은 눈금에 "-0" 으로 찍혀요). */
function clean(v: number): number {
  const x = Number(v.toPrecision(12))
  return x === 0 ? 0 : x
}

function niceStep(raw: number): number {
  const pow = 10 ** Math.floor(Math.log10(raw))
  const f = raw / pow
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10
  return nice * pow
}

/**
 * 값의 범위를 감싸는 깔끔한 눈금.
 * includeZero 가 true 면 0 을 꼭 넣어요 (막대는 기준선이 0 이어야 길이를 비교할 수 있어요).
 */
export function niceAxis(values: number[], includeZero: boolean, target = 4): Axis {
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { lo: 0, hi: 1, ticks: [0, 1] }
  if (includeZero) {
    min = Math.min(0, min)
    max = Math.max(0, max)
  }
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1
    min -= pad
    max += pad
  }
  const step = niceStep((max - min) / target)
  const lo = clean(Math.floor(min / step + 1e-9) * step)
  const hi = clean(Math.ceil(max / step - 1e-9) * step)
  const ticks: number[] = []
  for (let i = 0; lo + i * step <= hi + step * 1e-6; i++) ticks.push(clean(lo + i * step))
  return { lo, hi, ticks }
}

export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0 || 1
  return (v) => r0 + ((v - d0) / span) * (r1 - r0)
}

/** 가로축 이름표를 겹치지 않게 솎아요. 마지막 항목은 꼭 보여 줘요. */
export function thin(count: number, maxLabels: number): number[] {
  if (count <= maxLabels) return Array.from({ length: count }, (_, i) => i)
  const step = Math.ceil((count - 1) / (maxLabels - 1))
  const out: number[] = []
  for (let i = count - 1; i >= 0; i -= step) out.unshift(i)
  return out
}
