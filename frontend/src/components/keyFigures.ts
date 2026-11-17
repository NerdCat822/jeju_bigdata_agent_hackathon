import type { Answer } from '../api/types'
import { shortPeriod } from '../lib/format'

type FactOf = Answer['facts'][number]

export interface Figure {
  key: string
  label: string
  value: string
  note?: string
}

/** 큰 인원수는 '−21.8만 명'처럼 줄여 적어요. 정확한 값은 근거표에 있어요. */
function compactPeople(f: FactOf): string {
  const v = typeof f.value === 'number' ? f.value : Number.NaN
  if (!Number.isFinite(v) || Math.abs(v) < 10_000) return f.text
  const sign = v < 0 ? '−' : ''
  return `${sign}${(Math.abs(v) / 10_000).toFixed(1)}만 명`
}

/** '+5.5%' · '-5.5%' 의 빼기표를 읽기 쉬운 '−'로 바꿔요. */
const signed = (text: string): string => text.replace(/^-/, '−')

/** '20·30대 거주 변화율' → '20·30대 거주 변화'. */
const changeLabel = (label: string): string => label.replace(/\s*변화율$/, ' 변화')

/** '하루 평균 2,537명'. */
const perDay = (f: FactOf | undefined): string | undefined => (f ? `하루 평균 ${f.text}` : undefined)

/**
 * 답마다 먼저 볼 숫자 세 개. 해설 문단은 그대로 두고, 그 위에 큰 숫자로 따로 보여 줘요.
 * 값과 문구는 모두 답의 근거(facts)에서 가져와요. 근거에 없는 숫자는 만들지 않아요.
 */
export function keyFigures(a: Answer): Figure[] {
  if (!a.ok) return []
  const fact = (key: string): FactOf | undefined => a.facts.find((f) => f.key === key)
  const out: Figure[] = []
  const add = (fig: Figure | null | undefined): void => {
    if (fig && out.length < 3) out.push(fig)
  }

  if (a.stage === 1) {
    // 진단 답에도 전체 순위(rank1…)가 함께 실려 와서, 순위 카드는 순위를 물은 질문에만 써요
    const ranks = a.intent === 'recommend' ? [1, 2, 3].map((i) => fact(`rank${i}`)).filter((f): f is FactOf => !!f) : []
    if (ranks.length) {
      // 순위 질문: 1~3위 (값의 앞은 읍면동 이름, 뒤는 변화율)
      for (const [i, f] of ranks.entries()) {
        const [name, ...rest] = f.text.split(' ')
        add({ key: f.key, label: `${i + 1}위 · ${name}`, value: signed(rest.join(' ') || f.text) })
      }
      return out
    }
    // 진단: 유형을 가르는 세 지표 (거주 · 근무 · 방문)
    for (const [chg, base] of [
      ['youth_resd_chg', 'youth_resd_p1'],
      ['youth_work_chg', 'youth_work_p1'],
      ['visit_chg', 'visit_p1'],
    ] as const) {
      const f = fact(chg)
      if (f) add({ key: f.key, label: changeLabel(f.label), value: signed(f.text), note: perDay(fact(base)) })
    }
    return out
  }

  if (a.stage === 2) {
    const fired = fact('n_fired')
    const rules = fact('n_rules')
    if (fired) add({ key: fired.key, label: '조건을 충족한 제안', value: fired.text, note: rules ? `규칙 ${rules.text} 가운데` : undefined })
    const nat = fact('nat_top')
    const natGrowth = fact('nat_growth_top')
    if (nat && natGrowth) add({ key: nat.key, label: '가장 빠르게 늘어난 국적', value: `${nat.text} ${signed(natGrowth.text)}`, note: natGrowth.period ? shortPeriod(natGrowth.period) : undefined })
    const cn = fact('cn_growth:전체')
    if (cn) add({ key: cn.key, label: '중국인 카드 소비 변화', value: signed(cn.text), note: cn.period ? shortPeriod(cn.period) : undefined })
    return out
  }

  if (a.stage === 3) {
    const delta = fact('scenario_delta')
    const base = fact('baseline_total')
    if (delta) add({ key: delta.key, label: '입도객 변화 (가정에 따른 계산)', value: compactPeople(delta), note: base ? `기준선 ${base.text} 대비` : undefined })
    const courses = fact('n_courses')
    const gap = fact('access_gap')
    if (courses) add({ key: courses.key, label: '거점에서 오는 버스 코스', value: courses.text, note: gap ? `닿지 않는 거점: ${gap.text}` : undefined })
    const sensitive = fact('n_sensitive')
    const routes = fact('n_routes')
    if (sensitive) add({ key: sensitive.key, label: '관광 수요에 민감한 노선', value: sensitive.text, note: routes ? `지나는 노선 ${routes.text} 가운데` : undefined })
    return out
  }
  return out
}
