import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { MapSpec, RouteOut } from '../../api/types'
import { pct } from '../../lib/format'
import { TypeMark } from '../TypeMark'
import { JejuMap } from './JejuMap'
import type { MapDot } from './JejuMap'
import { useMaps } from './mapsContext'
import { NaverMap } from './NaverMap'
import { seriesColor } from './palette'
import { useMapChoice } from './useMapChoice'

interface Props {
  spec: MapSpec
  wide?: boolean
  /** 지도에서 읍면동을 누르면 그 동네를 진단해요. */
  onPickPlace?: (name: string) => void
}

/** '약 56분', '약 1시간 5분'. */
function minutes(s: number): string {
  const m = Math.max(1, Math.round(s / 60))
  return m < 60 ? `약 ${m}분` : `약 ${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ''}`
}

/** 코스마다 자동차 도로 경로와 거리·시간 (네이버 길찾기). 서버에 지도 키가 없거나 실패하면 빈 표예요. */
function useRoutes(spec: MapSpec): Record<string, RouteOut> {
  const { keyId, api } = useMaps()
  const [routes, setRoutes] = useState<Record<string, RouteOut>>({})
  useEffect(() => {
    if (!keyId || !api || !spec.lines.length) return
    let alive = true
    void Promise.all(spec.lines.map((l) => api.mapRoute(l.keys).then((r) => [l.label, r] as const, () => null))).then((found) => {
      if (alive) setRoutes(Object.fromEntries(found.filter((x): x is readonly [string, RouteOut] => x !== null)))
    })
    return () => {
      alive = false
    }
  }, [spec, keyId, api])
  return routes
}

/** 답에 딸린 지도: 유형 지도(43개 읍면동) 또는 거점에서 오는 코스 지도. */
export function MapCard({ spec, wide = false, onPickPlace }: Props): ReactNode {
  const choice = useMapChoice()
  const routes = useRoutes(spec)
  const legend = Object.entries(spec.legend)
  const counts = new Map<string, number>()
  for (const p of spec.points) if (p.category) counts.set(p.category, (counts.get(p.category) ?? 0) + 1)
  const hasHub = spec.points.some((p) => p.role === 'hub')
  const paths = useMemo(() => Object.fromEntries(Object.entries(routes).map(([k, r]) => [k, r.path as [number, number][]])), [routes])

  const dots: MapDot[] = spec.points.map((p) => {
    const typeLabel = p.category ? spec.legend[p.category] : null
    const parts = [
      p.role === 'hub' ? `거점 · ${p.category ?? ''}` : typeLabel,
      p.value !== null && p.value !== undefined ? `청년 거주 ${pct(p.value)}` : null,
      p.role === 'target' ? '지금 보는 곳' : p.role === 'peer' ? '비슷한 곳' : null,
    ].filter(Boolean)
    // 코스 지도의 거점은 코스 번호로 적어요 (가까운 거점의 이름표가 겹치지 않게, 이름은 아래 코스 목록에)
    const courses = spec.lines.flatMap((l, k) => (l.keys[0] === p.key ? [String(k + 1)] : []))
    return {
      key: p.key,
      name: p.name,
      lat: p.lat,
      lon: p.lon,
      category: p.category,
      role: p.role,
      detail: courses.length ? `${parts.join(' · ')} · 코스 ${courses.join('·')}` : parts.join(' · '),
      mark: p.role === 'hub' && courses.length ? courses.join('·') : undefined,
    }
  })
  const target = spec.points.find((p) => p.role === 'target')
  const select = onPickPlace ? (d: MapDot) => d.role !== 'hub' && onPickPlace(d.name) : undefined
  const names = new Map(spec.points.map((p) => [p.key, p.name]))

  return (
    <figure className={`viz-card${wide ? ' is-wide' : ''}`}>
      <div className="viz-head">
        <figcaption className="viz-title">{spec.title}</figcaption>
        {choice.toggle}
      </div>
      {choice.naver && choice.keyId ? (
        <NaverMap
          keyId={choice.keyId}
          dots={dots}
          lines={spec.lines}
          routes={paths}
          selectedKey={target?.key ?? null}
          label={`${spec.title}. 네이버 지도예요. 점마다 이름이 있고, '간단한 지도로 보기'를 누르면 키보드로 점을 하나씩 읽을 수 있어요.`}
          onSelect={select}
          onFail={choice.fail}
        />
      ) : (
        <JejuMap
          dots={dots}
          lines={spec.lines}
          selectedKey={target?.key ?? null}
          label={`${spec.title}. 점마다 Tab 키로 이름과 유형을 읽을 수 있어요.`}
          onSelect={select}
        />
      )}
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
            {choice.naver && spec.lines.length ? '출발 거점 (숫자는 코스 번호)' : '출발 거점'}
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
      {spec.lines.length > 0 && Object.keys(routes).length > 0 && (
        <ul className="route-list" aria-label="코스별 도로 거리와 시간">
          {spec.lines.map((l, k) =>
            routes[l.label] ? (
              <li key={l.label}>
                <span className="route-key" style={{ background: seriesColor(k) }} aria-hidden="true" />
                <span>
                  {l.label} · {names.get(l.keys[0]) ?? ''} → {names.get(l.keys[l.keys.length - 1]) ?? ''}
                </span>
                <span className="muted">
                  도로 {(routes[l.label].distance_m / 1000).toFixed(1)}km · 자동차 {minutes(routes[l.label].duration_s)}
                </span>
              </li>
            ) : null,
          )}
        </ul>
      )}
      <p className="viz-note">
        {spec.note ? `${spec.note} ` : ''}
        {choice.naver ? '지도 © NAVER Corp.' : '섬 윤곽은 위치를 가늠하기 위한 밑그림이에요.'}
        {Object.keys(routes).length > 0
          ? ' 코스의 도로 경로와 시간은 네이버 길찾기의 자동차 기준이에요. 버스는 정류장을 들르고 배차를 기다려서 더 걸려요.'
          : ''}
        {onPickPlace && legend.length > 0 ? ' 점을 누르면 그 동네를 진단해요.' : ''}
      </p>
    </figure>
  )
}
