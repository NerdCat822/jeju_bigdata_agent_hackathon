import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ChartSpec, Progress } from '../api/types'
import type { Turn } from '../state/agent'
import { bootstrap, cardOut, failed, stage1, stage2, stage3 } from '../test/fixtures'
import { AnswerView } from './AnswerView'
import { ConfirmCard } from './ConfirmCard'
import { EvidencePanel } from './EvidencePanel'
import { keyFigures } from './keyFigures'
import { toRows } from './progressRows'
import { explainedBy } from './verification'
import { ChartCard } from './viz/ChartCard'
import { MapCard } from './viz/MapCard'

const noop = (): void => {}
const typeNames = new Map(bootstrap.options.types.map((t) => [t.code, t.label]))
const answerProps = { typeNames, busy: false, needsConsent: false, onAsk: noop, onReport: noop, onPickPlace: noop, onAgreeCloud: noop }

const turn = (patch: Partial<Turn> = {}): Turn => ({
  id: 't1',
  question: '성산읍 청년 인구 왜 줄었어?',
  card: cardOut.card,
  dirty: false,
  status: 'confirm',
  progress: [],
  answers: [],
  kind: null,
  reportUrl: null,
  error: null,
  startedAt: null,
  elapsed: null,
  ...patch,
})

describe('답 화면', () => {
  it('한 줄 결론, 해설, 유형 배지, 다음 질문을 보여 줘요', () => {
    render(<AnswerView answer={stage1} stageTitle="청년이 머무는 동네" {...answerProps} />)
    expect(screen.getByRole('heading', { level: 2, name: stage1.headline })).toBeInTheDocument()
    expect(screen.getByText(stage1.explanation)).toBeInTheDocument()
    const meta = screen.getByText('1단계 · 청년이 머무는 동네').parentElement as HTMLElement
    expect(within(meta).getByText('C 방문 의존형')).toBeInTheDocument() // 유형 표식과 이름
    expect(screen.queryByText(/Stage/)).toBeNull() // 처음 보는 사람에게 낯선 'Stage' 대신 '1단계'
    expect(screen.queryByText('샘플 데이터')).toBeNull() // 데이터 배지는 화면 위쪽에만 둬요
    expect(screen.getByText(/검증 통과 · 7개 항목/)).toBeInTheDocument()
    const next = screen.getByRole('navigation', { name: '다음 질문' })
    expect(within(next).getAllByRole('button').map((b) => b.textContent)).toEqual(['이 동네에 누가 올까?', '비슷한 읍면과 비교', '30대만 보기'])
  })

  it('다음 질문을 누르면 그 질문을 묻고, 제안서 단추는 제안서를 만들어요', async () => {
    const onAsk = vi.fn()
    const onReport = vi.fn()
    render(<AnswerView answer={stage3} stageTitle="어떻게 오게 하나" {...answerProps} onAsk={onAsk} onReport={onReport} />)
    await userEvent.click(screen.getByRole('button', { name: '감편 20%면?' }))
    expect(onAsk).toHaveBeenCalledWith('성산읍 감편 20%면?')
    await userEvent.click(screen.getByRole('button', { name: '최종 제안서 받기' }))
    expect(onReport).toHaveBeenCalledOnce()
    expect(screen.queryByText(/→ (Stage|\d단계)/)).toBeNull() // 화살표 글자는 떼고 아이콘으로 보여 줘요
    expect(within(screen.getByRole('list', { name: '표시' })).getByText(/가정: 국내선 공급 -10%/)).toBeInTheDocument() // 가정 배지
  })

  it('Stage 2 의 제안은 규칙 번호와 근거를 함께 보여 줘요', () => {
    render(<AnswerView answer={stage2} stageTitle="빈자리를 누가 채우나" {...answerProps} />)
    const list = screen.getByRole('region', { name: '규칙이 만든 제안' })
    for (const s of stage2.suggestions) {
      expect(within(list).getByText(s.rule_id)).toBeInTheDocument()
      expect(within(list).getByText(s.text)).toBeInTheDocument()
    }
    expect(within(list).getAllByText(/^근거 ·/)).toHaveLength(stage2.suggestions.length)
    // 제목이 먼저 오고 규칙 번호는 근거 줄 끝에 있어요
    const first = within(list).getAllByRole('listitem')[0]
    expect(first.firstElementChild?.textContent).toContain(stage2.suggestions[0].name)
    expect(within(first).getByText(stage2.suggestions[0].rule_id).closest('.suggestion-evidence')).not.toBeNull()
    // 해설은 '규칙 12개 가운데 6개'라 말하는데 화면에는 3개만 있어요. 그 차이를 밝혀요
    expect(within(list).getByText('조건을 충족한 6개 가운데 우선순위가 높은 3개예요')).toBeInTheDocument()
  })

  it('답마다 핵심 숫자 세 개를 큰 숫자 카드로 먼저 보여 줘요', () => {
    render(<AnswerView answer={stage1} stageTitle="청년이 머무는 동네" {...answerProps} />)
    const cards = screen.getByLabelText('핵심 숫자')
    expect(within(cards).getByText('20·30대 거주 변화')).toBeInTheDocument()
    expect(within(cards).getByText('−5.5%')).toBeInTheDocument()
    expect(keyFigures(stage1).map((f) => [f.label, f.value, f.note])).toEqual([
      ['20·30대 거주 변화', '−5.5%', '하루 평균 1,589명'],
      ['20·30대 근무 변화', '−1.3%', '하루 평균 619명'],
      ['방문자 변화', '+7.9%', '하루 평균 16,638명'],
    ])
    expect(keyFigures(stage2).map((f) => [f.label, f.value])).toEqual([
      ['조건을 충족한 제안', '6개'],
      ['가장 빠르게 늘어난 국적', '대만 +38.0%'],
      ['중국인 카드 소비 변화', '+10.7%'],
    ])
    // 큰 인원수는 줄여 적고, 정확한 값은 근거표에 둬요
    expect(keyFigures(stage3)[0]).toMatchObject({ label: '입도객 변화 (가정에 따른 계산)', value: '−11.9만 명', note: '기준선 1,193,769명 대비' })
    expect(keyFigures(failed)).toEqual([])
    // 순위를 물은 질문만 1~3위를 카드로 보여 줘요 (진단 답에도 전체 순위가 실려 와요)
    expect(keyFigures({ ...stage1, intent: 'recommend' }).map((f) => [f.label, f.value])).toEqual([
      ['1위 · 오라동', '+7.9%'],
      ['2위 · 대천동', '+7.4%'],
      ['3위 · 삼양동', '+7.3%'],
    ])
  })

  it('답하지 못한 질문은 이유와 예시 질문을 보여 줘요', async () => {
    const onAsk = vi.fn()
    render(<AnswerView answer={failed} stageTitle={null} {...answerProps} onAsk={onAsk} />)
    expect(screen.getByText('답하지 못했어요')).toBeInTheDocument()
    expect(screen.getByText(failed.message ?? '')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: failed.next_questions[0].label }))
    expect(onAsk).toHaveBeenCalledWith(failed.next_questions[0].question)
  })

  it('클라우드 전송에 동의하기 전에는 보낼 내용을 미리 보여 주고 동의를 받아요', async () => {
    const onAgreeCloud = vi.fn()
    const a = { ...stage1, llm_mode: 'anthropic', llm_payload: '질문: 성산읍 청년 인구 진단\n근거:\n- 20·30대 거주 변화율: -5.5%' }
    render(<AnswerView answer={a} stageTitle="청년이 머무는 동네" {...answerProps} needsConsent onAgreeCloud={onAgreeCloud} />)
    expect(screen.getByText(/20·30대 거주 변화율: -5.5%/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '이 내용을 보내는 데 동의하고 다시 실행' }))
    expect(onAgreeCloud).toHaveBeenCalledOnce()
  })

  it('해설을 누가 썼는지 밝혀요', () => {
    expect(explainedBy(stage1)).toBe('해설: 규칙 문장')
    expect(explainedBy({ ...stage1, explained_by: 'llm', llm_mode: 'anthropic', llm_model: 'claude-opus-5-5', verification: { ...stage1.verification, retries: 1 } })).toBe(
      '해설: Claude Opus 5.5 (검증 통과, 다시 쓰기 1회)',
    )
    expect(explainedBy({ ...stage1, verification: { ...stage1.verification, fallback: true } })).toContain('대체')
  })
})

describe('근거표', () => {
  it('종류에 맞춰 숫자를 적고, 긴 표는 접어 둬요', async () => {
    const summary = stage1.evidence.find((e) => e.id === 's1_summary')!
    const ranking = stage1.evidence.find((e) => e.id === 's1_ranking')!
    render(<EvidencePanel tables={[summary, ranking]} />)
    const table = screen.getAllByRole('table')[0]
    expect(within(table).getByText('-5.5%')).toBeInTheDocument()
    expect(within(table).getAllByRole('row')).toHaveLength(summary.rows.length + 1)
    const more = screen.getByRole('button', { name: /나머지 \d+행 더 보기/ })
    expect(within(screen.getAllByRole('table')[1]).getAllByRole('row')).toHaveLength(9)
    await userEvent.click(more)
    expect(within(screen.getAllByRole('table')[1]).getAllByRole('row')).toHaveLength(ranking.rows.length + 1)
    expect(screen.getAllByText('SQL').length).toBe(2)
  })

  it('지금 보는 읍면동의 행과 충족한 판정 행을 눈에 띄게 하고, 유형은 표식으로 적어요', () => {
    const rule = stage1.evidence.find((e) => e.id === 's1_type_rule')!
    const peers = stage1.evidence.find((e) => e.id === 's1_peers')!
    render(<EvidencePanel tables={[rule, peers]} place="성산읍" />)
    const [ruleTable, peerTable] = screen.getAllByRole('table')
    const met = within(ruleTable).getByText('예').closest('tr') as HTMLElement
    expect(met).toHaveClass('is-current')
    expect(within(met).getByText('방문 의존형')).toBeInTheDocument()
    expect(met.querySelector('.type-mark')).toHaveTextContent('C')
    expect(ruleTable.querySelectorAll('tr.is-current')).toHaveLength(1)
    const mine = within(peerTable).getByText('성산읍 (대상)').closest('tr') as HTMLElement
    expect(mine).toHaveClass('is-current')
    expect(peerTable.querySelectorAll('tr.is-current')).toHaveLength(1)
    expect(peerTable.querySelectorAll('.type-mark')).toHaveLength(peers.rows.length)
  })
})

describe('차트', () => {
  const line = stage1.charts.find((c) => c.kind === 'line')!
  const bar = stage1.charts.find((c) => c.kind === 'bar')!

  it('선 차트는 계열마다 선과 범례를 그리고, 화살표 키로 값을 읽을 수 있어요', async () => {
    const { container } = render(<ChartCard spec={line} />)
    expect(container.querySelectorAll('path.viz-line')).toHaveLength(line.series.length)
    const legend = screen.getByRole('list', { name: '범례' })
    expect(within(legend).getAllByRole('listitem').map((li) => li.textContent)).toEqual(line.series.map((s) => s.name))
    const plot = screen.getByRole('group', { name: new RegExp(line.title) })
    plot.focus()
    await userEvent.keyboard('{Home}')
    expect(container.querySelector('.viz-tip-title')?.textContent).toBe(line.x[0])
    expect(container.querySelectorAll('.viz-tip-row strong')[0].textContent).toBe('100.0')
    await userEvent.keyboard('{ArrowRight}')
    expect(container.querySelector('.viz-tip-title')?.textContent).toBe(line.x[1])
    await userEvent.keyboard('{Escape}')
    expect(container.querySelector('.viz-tip')).toBeNull()
  })

  it('항목 비교는 막대 목록으로 보여 주고, 주인공 한 줄만 강조해요', () => {
    const { container } = render(<ChartCard spec={bar} />)
    const rows = [...container.querySelectorAll('.bar-row')]
    expect(rows).toHaveLength(bar.x.length)
    expect(rows.filter((r) => r.classList.contains('is-lead')).map((r) => r.querySelector('.bar-name')?.textContent)).toEqual(['성산읍'])
    expect(rows.map((r) => r.querySelector('.bar-value')?.textContent)).toContain('-5.5%') // 값은 줄마다 적혀 있어요
    expect(screen.getByLabelText('성산읍: -5.5% (지금 보는 항목)')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '범례' })).toBeNull()
    expect(container.querySelectorAll('.bar-fill')).toHaveLength(bar.x.length)
  })

  it('막대 목록은 0 에서 자라고, 음수와 양수가 섞이면 0 자리를 표시해요', () => {
    const mixed: ChartSpec = { ...bar, x: ['가', '나', '다'], highlight: '나', series: [{ name: '변화율', y: [-0.02, 0.04, null] }] }
    const { container } = render(<ChartCard spec={mixed} />)
    const fills = [...container.querySelectorAll<HTMLElement>('.bar-fill')]
    expect(fills).toHaveLength(2) // 값이 없는 줄은 막대를 그리지 않아요
    expect(fills[0].style.left).toBe('0%')
    expect(parseFloat(fills[0].style.width)).toBeCloseTo(33.33, 1)
    expect(parseFloat(fills[1].style.left)).toBeCloseTo(33.33, 1)
    expect(container.querySelectorAll('.bar-zero')).toHaveLength(3)
    expect(container.querySelector('.bar-row.is-lead .bar-name')?.textContent).toBe('나')
  })

  it('계열이 둘 이상인 막대는 세로 막대로 그리고, 막대가 많으면 값을 다 적지 않아요', () => {
    const two: ChartSpec = { ...bar, x: ['가', '나'], series: [{ name: '올해', y: [0.1, 0.2] }, { name: '작년', y: [0.05, 0.1] }] }
    const few = render(<ChartCard spec={two} />)
    expect(few.container.querySelectorAll('path.viz-bar')).toHaveLength(4)
    expect(few.container.querySelectorAll('.viz-value')).toHaveLength(4)
    expect(screen.getByRole('list', { name: '범례' })).toBeInTheDocument()
    few.unmount()
    const many: ChartSpec = { ...two, x: ['가', '나', '다', '라'] , series: two.series.map((s) => ({ ...s, y: [0.1, 0.2, 0.3, 0.4] })) }
    const { container } = render(<ChartCard spec={many} />)
    expect(container.querySelectorAll('path.viz-bar')).toHaveLength(8)
    expect(container.querySelectorAll('.viz-value')).toHaveLength(0)
  })

  it('표로 보기를 누르면 같은 값을 표로 보여 줘요', async () => {
    render(<ChartCard spec={line} />)
    await userEvent.click(screen.getByRole('button', { name: '표로 보기' }))
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(line.x.length + 1)
    expect(within(table).getAllByText('100.0').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '차트로 보기' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('선 차트는 기획서 예시처럼 첫 계열은 파랑, 둘째는 귤색이에요', () => {
    const { container } = render(<ChartCard spec={line} />)
    const strokes = [...container.querySelectorAll('path.viz-line')].map((p) => p.getAttribute('stroke'))
    expect(strokes).toEqual(['var(--series-1)', 'var(--series-2)'])
  })

  it('값이 빈 달은 선을 끊어 그려요', () => {
    const gap: ChartSpec = { ...line, x: ['2025-01', '2025-02', '2025-03', '2025-04'], series: [{ name: '거주', y: [100, null, 98, 97] }] }
    const { container } = render(<ChartCard spec={gap} />)
    expect(container.querySelector('path.viz-line')?.getAttribute('d')?.match(/M/g)).toHaveLength(2)
  })
})

describe('지도', () => {
  const typeMap = stage1.maps[0]
  const courseMap = stage3.maps[0]

  it('유형 지도는 읍면동 43곳을 찍고, 유형 글자와 범례를 함께 보여 줘요', () => {
    const { container } = render(<MapCard spec={typeMap} />)
    expect(container.querySelectorAll('g.map-dot')).toHaveLength(43)
    expect(container.querySelector('g.map-dot.role-target')?.getAttribute('aria-label')).toContain('성산읍')
    expect(container.querySelectorAll('g.map-dot.role-peer')).toHaveLength(3)
    const lettered = [...container.querySelectorAll('.map-letter')].map((t) => t.textContent)
    expect(lettered.length).toBe(typeMap.points.filter((p) => p.category !== '유지').length) // 색만으로 구분하지 않아요
    const legend = screen.getByRole('list', { name: '유형 범례' })
    expect(within(legend).getByText(/C 방문 의존형/)).toBeInTheDocument()
    expect(within(legend).getByText('18')).toBeInTheDocument()
  })

  it('점을 누르면 그 동네를 고르고, 키보드로도 고를 수 있어요', async () => {
    const onPick = vi.fn()
    render(<MapCard spec={typeMap} onPickPlace={onPick} />)
    const dot = screen.getByRole('button', { name: /^구좌읍/ })
    await userEvent.click(dot)
    expect(onPick).toHaveBeenCalledWith('구좌읍')
    dot.focus()
    await userEvent.keyboard('{Enter}')
    expect(onPick).toHaveBeenCalledTimes(2)
  })

  it('코스 지도는 거점과 대상 읍면동을 잇는 선을 그려요', () => {
    const { container } = render(<MapCard spec={courseMap} />)
    expect(container.querySelectorAll('polyline.map-course')).toHaveLength(courseMap.lines.length)
    expect(container.querySelectorAll('g.map-dot.role-hub')).toHaveLength(3)
    expect(screen.getByText('출발 거점')).toBeInTheDocument()
  })
})

describe('확인 카드', () => {
  const base = { options: bootstrap.options, places: bootstrap.places, latestYear: 2026, busy: false }

  it('해석을 칩으로 보여 주고, 실행을 누르면 실행해요', async () => {
    const onRun = vi.fn()
    render(<ConfirmCard turn={turn()} {...base} onRun={onRun} onEdit={noop} />)
    expect(screen.getByRole('heading', { name: '이렇게 이해했어요' })).toBeInTheDocument()
    const chips = within(screen.getByRole('list', { name: '질문 해석' })).getAllByRole('listitem')
    expect(chips.map((c) => c.textContent?.replace(/\s+/g, ' ').trim())).toEqual(cardOut.card.chips.map((c) => `${c.label} ${c.value}`))
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    expect(onRun).toHaveBeenCalledOnce()
  })

  it('고치기를 열어 장소와 연령을 바꾸면 바꾼 값만 알려요', async () => {
    const onEdit = vi.fn()
    render(<ConfirmCard turn={turn()} {...base} onRun={noop} onEdit={onEdit} />)
    await userEvent.click(screen.getByRole('button', { name: '고치기' }))
    await userEvent.selectOptions(screen.getByLabelText('장소'), '구좌읍')
    expect(onEdit).toHaveBeenLastCalledWith({ place_name: '구좌읍', place_key: null, place_kind: null })
    await userEvent.click(screen.getByRole('button', { name: '20대' }))
    expect(onEdit).toHaveBeenLastCalledWith({ ages: [30] })
    await userEvent.selectOptions(screen.getByLabelText('기간'), '2026년 vs 2025년')
    expect(onEdit).toHaveBeenLastCalledWith({ year: 2026, last_n_months: null })
  })

  it('마지막 남은 연령은 끌 수 없어요', async () => {
    const onEdit = vi.fn()
    const one = { ...cardOut.card, query: { ...cardOut.card.query, ages: [30] } }
    render(<ConfirmCard turn={turn({ card: one })} {...base} onRun={noop} onEdit={onEdit} />)
    await userEvent.click(screen.getByRole('button', { name: '고치기' }))
    await userEvent.click(screen.getByRole('button', { name: '30대' }))
    expect(onEdit).not.toHaveBeenCalled()
  })

  it('읍면동이 빠져 실행할 수 없으면 이유를 알리고 바로 고를 수 있게 해요', () => {
    const blocked = { ...cardOut.card, runnable: false, warnings: ['읍면동을 하나 골라 주세요. (예: 성산읍, 구좌읍, 노형동)'], query: { ...cardOut.card.query, place_kind: null, place_key: null, place_name: null } }
    render(<ConfirmCard turn={turn({ card: blocked })} {...base} onRun={noop} onEdit={noop} />)
    expect(screen.getByRole('button', { name: '실행' })).toBeDisabled()
    expect(screen.getByText(/읍면동을 하나 골라 주세요/)).toBeInTheDocument()
    expect(screen.getByLabelText('장소')).toBeInTheDocument() // 고치기를 누르지 않아도 열려 있어요
  })

  it('Stage 3 해석에는 가정값을 고치는 칸이 나와요', async () => {
    const onEdit = vi.fn()
    const s3 = { ...cardOut.card, query: { ...stage3.query, intent: 'plan' as const } }
    render(<ConfirmCard turn={turn({ card: s3 })} {...base} onRun={noop} onEdit={onEdit} />)
    await userEvent.click(screen.getByRole('button', { name: '고치기' }))
    await userEvent.selectOptions(screen.getByLabelText('국내선 공급 (가정)'), '-20% 감편')
    expect(onEdit).toHaveBeenLastCalledWith({ supply_change: -0.2 })
    await userEvent.click(screen.getByRole('button', { name: '1.5' }))
    expect(onEdit).toHaveBeenLastCalledWith({ elasticity: 1.5 })
    expect(screen.queryByLabelText('테마')).toBeNull()
  })

  it('실행한 뒤에는 카드 제목이 계산까지 했다고 알려요', () => {
    const { rerender } = render(<ConfirmCard turn={turn()} {...base} onRun={noop} onEdit={noop} />)
    expect(screen.getByRole('heading', { name: '이렇게 이해했어요' })).toBeInTheDocument()
    rerender(<ConfirmCard turn={turn({ status: 'running' })} {...base} onRun={noop} onEdit={noop} />)
    expect(screen.getByRole('heading', { name: '이렇게 이해하고 계산하고 있어요' })).toBeInTheDocument()
    rerender(<ConfirmCard turn={turn({ status: 'done' })} {...base} onRun={noop} onEdit={noop} />)
    expect(screen.getByRole('heading', { name: '이렇게 이해하고 계산했어요' })).toBeInTheDocument()
  })

  it('고친 뒤에는 다시 실행하라고 알려요', () => {
    render(<ConfirmCard turn={turn({ dirty: true, status: 'done' })} {...base} onRun={noop} onEdit={noop} />)
    expect(screen.getByRole('button', { name: '다시 실행' })).toBeEnabled()
    expect(screen.getByText(/해석을 고쳤어요/)).toBeInTheDocument()
  })
})

describe('진행 상황', () => {
  const items: Progress[] = [
    { kind: 'start' },
    { kind: 'stage', stage: 1, title: '청년이 머무는 동네', place: '성산읍' },
    { kind: 'tool', tool: 's1_trend', label: '청년 인구 추이 계산', ok: true, seconds: 0.03 },
    { kind: 'llm', purpose: 'explain', label: '쉬운 해설 쓰기', attempt: 1 },
    { kind: 'llm_result', purpose: 'explain', attempt: 1, ok: false, note: '검증을 통과하지 못해 다시 써요' },
    { kind: 'llm', purpose: 'explain', label: '쉬운 해설 쓰기', attempt: 2 },
  ]

  it('LLM 호출은 결과와 합쳐 한 줄로 보여 주고, 진행 중인 줄을 표시해요', () => {
    const rows = toRows(items, true)
    expect(rows.map((r) => [r.label, r.state])).toEqual([
      ['1단계 · 청년이 머무는 동네', 'ok'],
      ['청년 인구 추이 계산', 'ok'],
      ['쉬운 해설 쓰기', 'fail'],
      ['쉬운 해설 쓰기 (2번째)', 'wait'],
    ])
    expect(rows[2].note).toContain('다시 써요')
  })

  it('끝나면 기다리는 줄이 남지 않아요', () => {
    expect(toRows(items, false).some((r) => r.state === 'wait')).toBe(false)
  })

  it('앞 사람의 분석을 기다리는 동안 그렇다고 알려 주고, 차례가 오면 기다렸다고 바꿔 적어요', () => {
    const queued: Progress[] = [{ kind: 'start' }, { kind: 'queue' }]
    expect(toRows(queued, true).map((r) => [r.label, r.state])).toEqual([['앞 사람의 분석이 끝나기를 기다리고 있어요', 'wait']])
    const after = toRows([...queued, items[1], items[2]], true)
    expect(after[0]).toMatchObject({ label: '앞 사람의 분석을 기다렸어요', state: 'ok' })
  })
})
