import type { ReactNode } from 'react'
import type { MapSpec } from '../../api/types'
import { pct } from '../../lib/format'
import { TypeMark } from '../TypeMark'
import { JejuMap } from './JejuMap'
import type { MapDot } from './JejuMap'

interface Props {
  spec: MapSpec
  wide?: boolean
  /** 지도에서 읍면동을 누르면 그 동네를 진단해요. */
  onPickPlace?: (name: string) => void
}

/** 답에 딸린 지도: 유형 지도(43개 읍면동) 또는 거점에서 오는 코스 지도. */
export function MapCard({ spec, wide = false, onPickPlace }: Props): ReactNode {
  const legend = Object.entries(spec.legend)
  const counts = new Map<string, number>()
  for (const p of spec.points) if (p.category) counts.set(p.category, (counts.get(p.category) ?? 0) + 1)
  const hasHub = spec.points.some((p) => p.role === 'hub')

  const dots: MapDot[] = spec.points.map((p) => {
    const typeLabel = p.category ? spec.legend[p.category] : null
    const parts = [
      p.role === 'hub' ? `거점 · ${p.category ?? ''}` : typeLabel,
      p.value !== null && p.value !== undefined ? `청년 거주 ${pct(p.value)}` : null,
      p.role === 'target' ? '지금 보는 곳' : p.role === 'peer' ? '비슷한 곳' : null,
    ].filter(Boolean)
    return { key: p.key, name: p.name, lat: p.lat, lon: p.lon, category: p.category, role: p.role, detail: parts.join(' · ') }
  })
  const target = spec.points.find((p) => p.role === 'target')

  return (
    <figure className={`viz-card${wide ? ' is-wide' : ''}`}>
      <div className="viz-head">
        <figcaption className="viz-title">{spec.title}</figcaption>
      </div>
      <JejuMap
        dots={dots}
        lines={spec.lines}
        selectedKey={target?.key ?? null}
        label={`${spec.title}. 점마다 Tab 키로 이름과 유형을 읽을 수 있어요.`}
        onSelect={onPickPlace ? (d) => d.role !== 'hub' && onPickPlace(d.name) : undefined}
      />
      {legend.length > 0 && (
        <ul className="viz-legend" aria-label="유형 범례">
          {legend.map(([code, label]) => (
            <li key={code}>
              <TypeMark code={code} size={16} />
              {label}
              <span className="muted mono">{counts.get(code) ?? 0}</span>
            </li>
          ))}
        </ul>
      )}
      {hasHub && (
        <ul className="viz-legend" aria-label="지도 범례">
          <li>
            <span className="hub-key" aria-hidden="true" />
            출발 거점
          </li>
          <li>
            <span className="target-key" aria-hidden="true" />
            대상 읍면동
          </li>
          <li>
            <span className="course-key" aria-hidden="true" />
            기존 노선으로 닿는 코스
          </li>
        </ul>
      )}
      <p className="viz-note">
        {spec.note ? `${spec.note} ` : ''}
        섬 윤곽은 위치를 가늠하기 위한 밑그림이에요.{onPickPlace && legend.length > 0 ? ' 점을 누르면 그 동네를 진단해요.' : ''}
      </p>
    </figure>
  )
}
