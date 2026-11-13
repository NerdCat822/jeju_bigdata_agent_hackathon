import { useState } from 'react'
import type { ReactNode } from 'react'
import type { EvidenceTable } from '../api/types'
import { caption, formatCell, isNum } from '../lib/format'
import { Icon } from './Icon'
import { TypeMark } from './TypeMark'
import { isTypeCode } from './viz/palette'

const PREVIEW_ROWS = 8

/** "A 정착 성장형"처럼 유형 기호로 시작하는 값에서 기호와 이름을 갈라요. */
const TYPE_CELL = /^([A-D])\s+(.+)$/

/**
 * 근거표와 SQL. 평소에는 접어 두고, 펼치면 표와 실행한 SQL을 그대로 보여 줘요.
 * 지금 보고 있는 읍면동의 행과 판정에서 충족한 행은 바탕을 한 단계 올려 눈에 띄게 해요.
 */
export function EvidencePanel({ tables, place = null }: { tables: EvidenceTable[]; place?: string | null }): ReactNode {
  if (!tables.length) return null
  return (
    <details className="fold">
      <summary>
        <Icon name="chevron" /> 근거표와 SQL <span className="muted">표 {tables.length}개</span>
      </summary>
      <div className="fold-body">
        {tables.map((t) => (
          <EvidenceItem key={t.id} table={t} place={place} />
        ))}
      </div>
    </details>
  )
}

function EvidenceItem({ table: t, place }: { table: EvidenceTable; place: string | null }): ReactNode {
  const [all, setAll] = useState(false)
  const [copied, setCopied] = useState(false)
  const rows = all ? t.rows : t.rows.slice(0, PREVIEW_ROWS)
  const numeric = t.columns.map((c, i) => c in t.formats || t.rows.every((r) => r[i] === null || isNum(r[i])))
  const placeCol = t.columns.indexOf('읍면동')
  const metCol = t.columns.indexOf('충족')
  // 비슷한 읍면 표는 대상을 "성산읍 (대상)"처럼 적어서, 이름으로 시작하는 칸도 같은 곳으로 봐요.
  const isPlace = (v: unknown): boolean => !!place && typeof v === 'string' && (v === place || v.startsWith(`${place} `))
  const inUse = (r: unknown[]): boolean => (placeCol >= 0 && isPlace(r[placeCol])) || (metCol >= 0 && r[metCol] === '예')
  const copy = (): void => {
    if (!t.sql || !navigator.clipboard) return
    void navigator.clipboard.writeText(t.sql).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <section className="evidence">
      <h4 className="evidence-title">
        {t.title}
        {t.period && <span className="muted"> · {t.period}</span>}
      </h4>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {t.columns.map((c, i) => (
                <th key={c} scope="col" className={numeric[i] ? 'num' : undefined}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri} className={inUse(r) ? 'is-current' : undefined}>
                {t.columns.map((c, i) => (
                  <td key={c} className={numeric[i] ? 'num' : undefined}>
                    {c === '유형' ? <TypeCell value={r[i]} /> : formatCell(r[i], t.formats[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {t.rows.length > PREVIEW_ROWS && (
        <button type="button" className="link-button" onClick={() => setAll((v) => !v)}>
          {all ? '줄이기' : `나머지 ${t.rows.length - PREVIEW_ROWS}행 더 보기`}
        </button>
      )}
      {t.note && <p className="evidence-note">{caption(t.note)}</p>}
      {t.sql && (
        <details className="sql">
          <summary>
            <Icon name="chevron" /> SQL
          </summary>
          <button type="button" className="link-button sql-copy" onClick={copy}>
            <Icon name={copied ? 'check' : 'copy'} /> {copied ? '복사했어요' : '복사'}
          </button>
          <pre>
            <code>{t.sql}</code>
          </pre>
        </details>
      )}
    </section>
  )
}

/** 유형 칸: 유형 표식을 앞에 두고, 이름이 있으면 이름을 붙여요. 표식 안에 기호가 있어서 기호를 한 번 더 쓰지 않아요. */
function TypeCell({ value }: { value: unknown }): ReactNode {
  if (isTypeCode(value)) {
    return (
      <span className="cell-type">
        <TypeMark code={value} size={16} />
        {value === '유지' ? '유지' : <span className="sr-only">{value}</span>}
      </span>
    )
  }
  const m = typeof value === 'string' ? TYPE_CELL.exec(value) : null
  if (!m) return formatCell(value)
  return (
    <span className="cell-type">
      <TypeMark code={m[1]} size={16} />
      <span className="sr-only">{m[1]}</span>
      {m[2]}
    </span>
  )
}
