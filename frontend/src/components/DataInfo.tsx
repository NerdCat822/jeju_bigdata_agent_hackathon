import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type { Status } from '../api/types'
import { Icon } from './Icon'

/** 데이터 정보: 테이블마다 수록 기간과 출처, 적재할 때 생긴 문제를 보여 줘요. */
export function DataInfo({ status, onClose }: { status: Status; onClose: () => void }): ReactNode {
  const ref = useRef<HTMLDialogElement | null>(null)
  useEffect(() => {
    const el = ref.current
    if (el && !el.open) el.showModal?.()
  }, [])
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="data-info-title" onClose={onClose} onClick={(e) => e.target === ref.current && onClose()}>
      <div className="dialog-inner">
        <header className="dialog-head">
          <h2 id="data-info-title">
            데이터 정보 <span className="tag">{status.data_badge}</span>
          </h2>
          <button type="button" className="icon-button" aria-label="닫기" onClick={onClose}>
            <Icon name="x" />
          </button>
        </header>
        {status.data_mode === 'synthetic' && (
          <p className="callout">
            <Icon name="info" /> 샘플 데이터는 화면과 계산을 확인하려고 만든 합성 자료예요. 실제 통계가 아니에요.
          </p>
        )}
        {status.route_ref === 'sample' && (
          <p className="callout">
            <Icon name="info" /> 버스 노선과 경유 읍면동은 샘플 참조표를 쓰고 있어요
          </p>
        )}
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">자료</th>
                <th scope="col">수록 기간</th>
                <th scope="col" className="num">
                  행 수
                </th>
              </tr>
            </thead>
            <tbody>
              {status.tables.map((t) => (
                <tr key={t.table}>
                  <th scope="row">{t.title}</th>
                  <td>{t.period}</td>
                  <td className="num">{t.rows.toLocaleString('ko-KR')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {status.issues.length > 0 && (
          <>
            <h3 className="section-title">적재할 때 확인된 문제</h3>
            <ul className="limits">
              {status.issues.map((i, k) => (
                <li key={k}>
                  {i.table_name} · {i.issue}
                  {i.detail ? ` · ${i.detail}` : ''}
                  {i.n ? ` (${i.n.toLocaleString('ko-KR')}건)` : ''}
                </li>
              ))}
            </ul>
          </>
        )}
        <p className="muted small">출처 제주특별자치도, 제주데이터허브{status.built_at ? ` · 적재 ${status.built_at.replace('T', ' ')}` : ''}</p>
      </div>
    </dialog>
  )
}
