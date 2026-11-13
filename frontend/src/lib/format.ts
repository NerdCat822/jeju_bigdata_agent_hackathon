/** 숫자 표기. 백엔드(fmt.py, report/builder.py)와 같은 규칙이에요. */

export type CellFormat = 'pct' | 'share' | 'int' | 'num1' | 'num2' | 'won'
export type AxisFormat = 'num' | 'pct' | 'index' | 'won'

export function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function fixed(v: number, digits: number): string {
  return v.toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** 0.068 → "+6.8%". 비중처럼 부호가 필요 없으면 signed=false. */
export function pct(v: number | null | undefined, digits = 1, signed = true): string {
  if (!isNum(v)) return '-'
  let x = Number((v * 100).toFixed(digits))
  if (x === 0) x = 0
  const sign = signed && x > 0 ? '+' : ''
  return `${sign}${x.toFixed(digits)}%`
}

/** 금액: 1억 이상은 "12.30억", 1만 이상은 "1,234만". */
export function won(v: number): string {
  const a = Math.abs(v)
  if (a >= 1e8) return `${fixed(v / 1e8, 2)}억`
  if (a >= 1e4) return `${fixed(v / 1e4, 0)}만`
  return fixed(Math.round(v), 0)
}

/** 근거표 칸 하나. formats 에 적힌 종류대로 표기해요. */
export function formatCell(v: unknown, kind?: string | null): string {
  if (v === null || v === undefined) return '-'
  if (!isNum(v)) return String(v)
  switch (kind) {
    case 'pct':
      return pct(v)
    case 'share':
      return pct(v, 1, false)
    case 'int':
      return fixed(Math.round(v), 0)
    case 'num1':
      return fixed(v, 1)
    case 'num2':
      return fixed(v, 2)
    case 'won':
      return won(v)
    default:
      return Number.isInteger(v) ? fixed(v, 0) : fixed(v, 2)
  }
}

/** 큰 수를 짧게: 1,193,769 → "119만", 120,000,000 → "1.2억". 축 눈금용. */
export function compact(v: number): string {
  const a = Math.abs(v)
  if (a >= 1e8) return `${trim(v / 1e8)}억`
  if (a >= 1e4) return `${trim(v / 1e4)}만`
  return fixed(v, Number.isInteger(v) ? 0 : 1)
}

function trim(x: number): string {
  const digits = Math.abs(x) >= 100 || Number.isInteger(Number(x.toFixed(1))) ? 0 : 1
  return fixed(x, digits)
}

/** 축 눈금. 한 축에서는 한 가지 표기만 써요. */
export function axisTick(v: number, format: AxisFormat, maxAbs: number): string {
  if (format === 'pct') return pct(v, maxAbs < 0.1 ? 1 : 0)
  if (format === 'index') return fixed(v, 0)
  if (maxAbs >= 1e4) return compact(v)
  return fixed(v, Number.isInteger(v) ? 0 : 1)
}

/** 툴팁과 막대 끝에 쓰는 값. 눈금보다 자세해요. */
export function valueLabel(v: number | null | undefined, format: AxisFormat, unit = ''): string {
  if (!isNum(v)) return '-'
  if (format === 'pct') return pct(v)
  if (format === 'index') return fixed(v, 1)
  if (format === 'won') return `${won(v)} 원`
  return `${fixed(Math.round(v), 0)}${unit}`
}

/** "2024-11" → "24.11" (축에 쓰는 짧은 달 표기). 달이 아니면 그대로 돌려줘요. */
export function shortMonth(label: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(label)
  return m ? `${m[1].slice(2)}.${m[2]}` : label
}

/** 걸린 시간: 0.07 → "0.1초", 21.8 → "22초", 75 → "1분 15초". */
export function seconds(s: number): string {
  if (s < 0.1) return '0.1초 미만'
  if (s < 10) return `${s.toFixed(1)}초`
  if (s < 60) return `${Math.round(s)}초`
  return `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초`
}

/** 받침이 있는지 (조사를 고를 때 써요). 한글이 아니면 받침이 없는 것으로 봐요. */
export function hasBatchim(word: string): boolean {
  const c = word.charCodeAt(word.length - 1)
  return c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 !== 0
}

/** 낱말에 맞는 조사를 붙여요: josa("성산읍", "을를") → "성산읍을". */
export function josa(word: string, pair: '을를' | '은는' | '이가' | '과와'): string {
  return word + (hasBatchim(word) ? pair[0] : pair[1])
}
