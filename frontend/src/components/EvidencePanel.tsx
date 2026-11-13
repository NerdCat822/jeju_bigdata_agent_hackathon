import { useState } from 'react'
import type { ReactNode } from 'react'
import type { EvidenceTable } from '../api/types'
import { formatCell, isNum } from '../lib/format'
import { Icon } from './Icon'

const PREVIEW_ROWS = 8

/** 근거표와 SQL. 평소에는 접어 두고, 펼치면 표와 실행한 SQL을 그대로 보여 줘요. */
export function EvidencePanel({ tables }: { tables: EvidenceTable[] }): ReactNode {
  if (!tables.length) return null
  return (
    <details className="fold">
      <summary>
        <Icon name="chevron" size={14} /> 근거표 · SQL 보기 <span className="muted">표 {tables.length}개</span>
      </summary>
      <div className="fold-body">
        {tables.map((t) => (
          <EvidenceItem key={t.id} table={t} />
        ))}
      </div>
    </details>
  )
}

function EvidenceItem({ table: t }: { table: EvidenceTable }): ReactNode {
  const [all, setAll] = useState(false)
  const [copied, setCopied] = useState(false)
  const rows = all ? t.rows : t.rows.slice(0, PREVIEW_ROWS)
  const numeric = t.columns.map((c, i) => c in t.formats || t.rows.every((r) => r[i] === null || isNum(r[i])))
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
              <tr key={ri}>
                {t.columns.map((c, i) => (
                  <td key={c} className={numeric[i] ? 'num' : undefined}>
                    {formatCell(r[i], t.formats[c])}
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
      {t.note && <p className="evidence-note">{t.note}</p>}
      {t.sql && (
        <details className="sql">
          <summary>
            <Icon name="chevron" size={12} /> SQL
          </summary>
          <button type="button" className="link-button sql-copy" onClick={copy}>
            <Icon name={copied ? 'check' : 'copy'} size={14} /> {copied ? '복사했어요' : '복사'}
          </button>
          <pre>
            <code>{t.sql}</code>
          </pre>
        </details>
      )}
    </section>
  )
}
