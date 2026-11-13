import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Options, ParsedQuery, Place, QueryPatch } from '../api/types'
import { pct } from '../lib/format'
import type { Turn } from '../state/agent'
import { Icon, Spinner } from './Icon'

interface Props {
  turn: Turn
  options: Options
  places: Place[]
  /** 자료의 마지막 해 (기간 선택지에 써요). */
  latestYear: number | null
  busy: boolean
  onRun: () => void
  onEdit: (patch: QueryPatch) => void
}

const SUPPLY_PRESETS = [-0.3, -0.2, -0.1, -0.05, 0.05, 0.1]

/** "이렇게 이해했어요" 카드. 실행 전에 해석을 보여 주고, 고친 값으로 바로 다시 실행할 수 있어요. */
export function ConfirmCard({ turn, options, places, latestYear, busy, onRun, onEdit }: Props): ReactNode {
  const [editing, setEditing] = useState(false)
  const card = turn.card
  if (!card) {
    return (
      <section className="confirm" aria-busy="true">
        <h2 className="confirm-title">질문을 읽고 있어요</h2>
        <p className="muted">
          <Spinner /> {turn.question}
        </p>
      </section>
    )
  }
  const running = turn.status === 'running'
  const ran = turn.status === 'done' || turn.status === 'error'
  const runLabel = running ? '실행 중' : turn.dirty || ran ? '다시 실행' : '실행'
  // 아직 실행하지 않았거나 고친 뒤에는 이 단추가 다음 할 일이에요. 이미 본 답을 다시 돌리는 것은 조용한 단추로 둬요.
  const primary = turn.status === 'confirm' || turn.dirty || running

  return (
    <section className={`confirm${card.runnable ? '' : ' is-blocked'}`} aria-labelledby={`confirm-${turn.id}`}>
      <div className="confirm-main">
        <div className="confirm-body">
          <h2 id={`confirm-${turn.id}`} className="confirm-title">
            이렇게 이해했어요
          </h2>
          <ul className="tag-row" aria-label="질문 해석">
            {card.chips.map((c) => (
              <li key={c.label} className="chip">
                <span className="chip-label">{c.label}</span> {c.value}
              </li>
            ))}
          </ul>
        </div>
        <div className="confirm-actions">
          <button type="button" className="btn btn-ghost" aria-expanded={editing} onClick={() => setEditing((v) => !v)}>
            <Icon name="edit" /> {editing ? '닫기' : '고치기'}
          </button>
          <button
            type="button"
            className={`btn ${primary ? 'btn-dark' : 'btn-outline'}`}
            disabled={busy || !card.runnable}
            onClick={onRun}
            autoFocus={turn.status === 'confirm' && card.runnable}
          >
            {running && <Spinner />} {runLabel}
          </button>
        </div>
      </div>
      {card.warnings.length > 0 && (
        <ul className="confirm-warnings">
          {card.warnings.map((w) => (
            <li key={w}>
              <Icon name={card.runnable ? 'info' : 'alert'} /> {w}
            </li>
          ))}
        </ul>
      )}
      {(editing || !card.runnable) && (
        <QueryEditor query={card.query} options={options} places={places} latestYear={latestYear} disabled={running} onEdit={onEdit} />
      )}
      {turn.dirty && !running && <p className="confirm-dirty">해석을 고쳤어요. 다시 실행을 누르면 새 값으로 계산해요.</p>}
    </section>
  )
}

interface EditorProps {
  query: ParsedQuery
  options: Options
  places: Place[]
  latestYear: number | null
  disabled: boolean
  onEdit: (patch: QueryPatch) => void
}

function QueryEditor({ query: q, options, places, latestYear, disabled, onEdit }: EditorProps): ReactNode {
  const chain = q.intent === 'chain'
  const stage = q.stage
  const showAges = stage === 1 || chain
  const showPeriod = stage === 1 || stage === 2 || chain
  const showTheme = stage === 2
  const showAssumption = chain || ['plan', 'forecast', 'routes'].includes(q.intent)
  const showHub = ['plan', 'courses'].includes(q.intent)
  const intents = Object.entries(options.intent_stage).filter(([, s]) => s === stage)
  const period = q.year ? `y${q.year}` : q.last_n_months ? `m${q.last_n_months}` : 'default'
  const years = latestYear ? [latestYear, latestYear - 1] : []
  const supply = q.supply_change ?? options.supply_change_default
  const supplies = SUPPLY_PRESETS.includes(supply) ? SUPPLY_PRESETS : [...SUPPLY_PRESETS, supply].sort((a, b) => a - b)
  const elasticity = q.elasticity ?? options.elasticity_default
  const groups = ['제주시', '서귀포시'].map((city) => ({
    city,
    towns: places.filter((p) => p.city === city).sort((a, b) => (a.area_type === b.area_type ? a.emd_nm.localeCompare(b.emd_nm, 'ko') : a.area_type === '읍면' ? -1 : 1)),
  }))

  const toggleAge = (age: number): void => {
    const next = q.ages.includes(age) ? q.ages.filter((a) => a !== age) : [...q.ages, age]
    if (next.length) onEdit({ ages: next.sort((a, b) => a - b) })
  }
  const setPeriod = (v: string): void => {
    if (v === 'default') onEdit({ last_n_months: null, year: null })
    else if (v.startsWith('m')) onEdit({ last_n_months: Number(v.slice(1)), year: null })
    else onEdit({ year: Number(v.slice(1)), last_n_months: null })
  }

  return (
    <fieldset className="editor" disabled={disabled}>
      <legend className="sr-only">해석 고치기</legend>
      <label className="field">
        <span>장소</span>
        <select className="select" value={q.place_kind === 'emd' ? (q.place_name ?? '') : ''} onChange={(e) => onEdit({ place_name: e.target.value || null, place_key: null, place_kind: null })}>
          <option value="">{q.place_name && q.place_kind !== 'emd' ? q.place_name : '읍면동을 골라 주세요'}</option>
          {groups.map((g) => (
            <optgroup key={g.city} label={g.city}>
              {g.towns.map((p) => (
                <option key={p.emd_cd} value={p.emd_nm}>
                  {p.emd_nm}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {intents.length > 1 && !chain && (
        <label className="field">
          <span>분석</span>
          <select className="select" value={q.intent} onChange={(e) => onEdit({ intent: e.target.value as ParsedQuery['intent'] })}>
            {intents.map(([key]) => (
              <option key={key} value={key}>
                {options.intents[key] ?? key}
              </option>
            ))}
          </select>
        </label>
      )}
      {showAges && (
        <div className="field">
          <span id="age-label">연령</span>
          <div className="toggle-row" role="group" aria-labelledby="age-label">
            {options.age_bands.map((age) => (
              <button key={age} type="button" className={`toggle${q.ages.includes(age) ? ' is-on' : ''}`} aria-pressed={q.ages.includes(age)} onClick={() => toggleAge(age)}>
                {age}대
              </button>
            ))}
          </div>
        </div>
      )}
      {showPeriod && (
        <label className="field">
          <span>기간</span>
          <select className="select" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="default">최근 {options.period_months}개월 vs 직전</option>
            {[6, 3].map((m) => (
              <option key={m} value={`m${m}`}>
                최근 {m}개월 vs 전년 같은 기간
              </option>
            ))}
            {q.last_n_months && ![3, 6].includes(q.last_n_months) && <option value={`m${q.last_n_months}`}>최근 {q.last_n_months}개월 vs 전년 같은 기간</option>}
            {years.map((y) => (
              <option key={y} value={`y${y}`}>
                {y}년 vs {y - 1}년
              </option>
            ))}
            {q.year && !years.includes(q.year) && (
              <option value={`y${q.year}`}>
                {q.year}년 vs {q.year - 1}년
              </option>
            )}
          </select>
        </label>
      )}
      {showTheme && (
        <label className="field">
          <span>테마</span>
          <select className="select" value={q.theme ?? ''} onChange={(e) => onEdit({ theme: e.target.value || null })}>
            <option value="">전체 테마</option>
            {options.themes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      )}
      {showAssumption && (
        <>
          <label className="field">
            <span>국내선 공급 (가정)</span>
            <select className="select" value={String(supply)} onChange={(e) => onEdit({ supply_change: Number(e.target.value) })}>
              {supplies.map((v) => (
                <option key={v} value={String(v)}>
                  {pct(v, 0)} {v < 0 ? '감편' : '증편'}
                </option>
              ))}
            </select>
          </label>
          <div className="field">
            <span id="eps-label">탄력성 ε (가정)</span>
            <div className="toggle-row" role="group" aria-labelledby="eps-label">
              {options.elasticity_grid.map((e) => (
                <button key={e} type="button" className={`toggle${elasticity === e ? ' is-on' : ''}`} aria-pressed={elasticity === e} onClick={() => onEdit({ elasticity: e })}>
                  {e.toFixed(1)}
                </button>
              ))}
            </div>
          </div>
          <label className="field">
            <span>대상 월</span>
            <select className="select" value={q.target_month ?? ''} onChange={(e) => onEdit({ target_month: e.target.value ? Number(e.target.value) : null })}>
              <option value="">자료 다음 달</option>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>
                  {m}월
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {showHub && (
        <label className="field">
          <span>출발 거점</span>
          <select className="select" value={q.hub_id ?? ''} onChange={(e) => onEdit({ hub_id: e.target.value || null })}>
            <option value="">모든 거점</option>
            {options.hubs.map((h) => (
              <option key={h.hub_id} value={h.hub_id}>
                {h.hub_nm}
              </option>
            ))}
          </select>
        </label>
      )}
    </fieldset>
  )
}
