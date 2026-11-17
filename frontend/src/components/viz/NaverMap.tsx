import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { OFF_MAP_LAT } from '../../lib/geo'
import { loadNaverMaps, onNaverMapsFailure } from '../../lib/naverMaps'
import type { NMap, NMapObject, NaverMapsApi } from '../../lib/naverMaps'
import type { MapDot } from './JejuMap'
import { TYPE_COLORS, TYPE_INK, seriesColor } from './palette'

interface Props {
  keyId: string
  dots: MapDot[]
  /** 점 key 를 잇는 선 (코스). routes 에 같은 label 의 도로 경로가 있으면 그것으로 그려요. */
  lines?: { label: string; keys: string[] }[]
  /** label → (위도, 경도) 도로 경로. */
  routes?: Record<string, [number, number][]>
  selectedKey?: string | null
  onSelect?: (dot: MapDot) => void
  /** 점이 아닌 곳을 누르면 그 자리의 위도·경도를 알려 줘요. */
  onPickPoint?: (lat: number, lon: number) => void
  label: string
  /** 불러오기·인증에 실패하면 불러요. 부르는 쪽은 기본 지도로 바꿔 그려요. */
  onFail: () => void
}

const esc = (s: string): string => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

/** 'var(--series-1)' 같은 색을 지도 SDK 가 쓸 수 있는 실제 색으로 바꿔요. */
function cssColor(value: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(value)
  if (!m) return value
  return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || '#2f80ed'
}

/** 점 하나의 모양 (HTML). 유형 색에 유형 글자를 함께 써서 색만으로 구분하지 않아요. */
function markerHtml(d: MapDot, selected: boolean): { html: string; size: number } {
  const typed = !!d.category && d.category in TYPE_COLORS
  const size = d.role === 'target' || selected ? 22 : d.role === 'hub' ? (d.mark ? 20 : 18) : d.role === 'peer' || d.role === 'via' ? 18 : typed ? 16 : 12
  let cls = 'nm-dot'
  let style = ''
  let text = ''
  if (d.role === 'hub') {
    cls += ' is-hub'
    text = d.mark ? esc(d.mark) : ''
  } else if (typed) {
    style = `background:${TYPE_COLORS[d.category!]};color:${TYPE_INK[d.category!]};`
    text = d.category === '유지' ? '' : esc(d.category!)
  }
  if (d.role === 'target' || selected) cls += ' is-target'
  else if (d.role === 'via') cls += ' is-via'
  const label = !d.mark && (d.labeled || d.role !== 'other' || selected) ? `<span class="nm-name">${esc(d.name)}</span>` : ''
  return { html: `<span class="nm-mark" style="width:${size}px;height:${size}px"><span class="${cls}" style="${style}">${text}</span>${label}</span>`, size }
}

/** 네이버 지도 (Dynamic Map). 기본 지도(JejuMap)와 같은 점·선을 받아 실제 지도 위에 그려요. */
export function NaverMap({ keyId, dots, lines = [], routes = {}, selectedKey = null, onSelect, onPickPoint, label, onFail }: Props): ReactNode {
  const box = useRef<HTMLDivElement | null>(null)
  const sdk = useRef<NaverMapsApi | null>(null)
  const map = useRef<NMap | null>(null)
  const overlays = useRef<NMapObject[]>([])
  const listeners = useRef<unknown[]>([])
  const markerListeners = useRef<unknown[]>([])
  // 바뀌는 값과 콜백은 최신 것을 써요 (지도는 한 번만 만들고, 점과 선만 다시 그려요)
  const latest = useRef({ dots, lines, routes, selectedKey, onSelect, onPickPoint, onFail })
  useLayoutEffect(() => {
    latest.current = { dots, lines, routes, selectedKey, onSelect, onPickPoint, onFail }
  })
  const lastMarkerClick = useRef(0)
  const ready = useRef(false)
  const fitted = useRef('') // 지금 맞춘 점들. 같은 점들이면 사람이 옮긴 지도 범위를 그대로 둬요

  // 점과 선 그리기
  const draw = useCallback(() => {
    const maps = sdk.current
    const m = map.current
    if (!ready.current || !maps || !m) return
    const { dots, lines, routes, selectedKey, onSelect } = latest.current
    overlays.current.forEach((o) => o.setMap(null))
    overlays.current = []
    markerListeners.current.forEach((l) => maps.Event.removeListener(l))
    markerListeners.current = []
    const byKey = new Map(dots.map((d) => [d.key, d]))
    lines.forEach((ln, k) => {
      const road = routes[ln.label]
      const coords = road?.length ? road : ln.keys.map((key) => byKey.get(key)).filter((d): d is MapDot => !!d).map((d) => [d.lat, d.lon] as [number, number])
      if (coords.length < 2) return
      overlays.current.push(
        new maps.Polyline({
          map: m,
          path: coords.map(([lat, lon]) => new maps.LatLng(lat, lon)),
          strokeColor: cssColor(seriesColor(k)),
          strokeWeight: road ? 4 + 2 * (lines.length - 1 - k) : 3,
          strokeOpacity: road ? 0.85 : 0.7,
          strokeStyle: road ? 'solid' : 'shortdash', // 도로 경로를 못 받으면 점선 직선으로
          strokeLineCap: 'round',
          strokeLineJoin: 'round',
        }),
      )
    })
    const order = (d: MapDot): number => (d.key === selectedKey || d.role === 'target' ? 3 : d.role === 'hub' ? 2 : d.labeled ? 1 : 0)
    for (const d of [...dots].sort((a, b) => order(a) - order(b))) {
      const { html, size } = markerHtml(d, d.key === selectedKey)
      const marker = new maps.Marker({
        map: m,
        position: new maps.LatLng(d.lat, d.lon),
        title: d.detail ? `${d.name} · ${d.detail}` : d.name,
        icon: { content: html, anchor: new maps.Point(size / 2, size / 2) },
        zIndex: 100 + order(d),
        clickable: !!onSelect,
      })
      if (onSelect) {
        markerListeners.current.push(
          maps.Event.addListener(marker, 'click', () => {
            lastMarkerClick.current = Date.now()
            latest.current.onSelect?.(d)
          }),
        )
      }
      overlays.current.push(marker)
    }
    // 본섬이 다 보이게 맞춰요 (멀리 떨어진 추자면은 빼요). 점들이 그대로면 다시 맞추지 않아요
    const inMain = dots.filter((d) => d.lat <= OFF_MAP_LAT)
    const fitKey = inMain.map((d) => d.key).join(',')
    if (fitKey === fitted.current) return
    fitted.current = fitKey
    if (inMain.length === 1) {
      m.setCenter(new maps.LatLng(inMain[0].lat, inMain[0].lon))
      m.setZoom(12)
    } else if (inMain.length > 1) {
      const lats = inMain.map((d) => d.lat)
      const lons = inMain.map((d) => d.lon)
      const bounds = new maps.LatLngBounds(new maps.LatLng(Math.min(...lats), Math.min(...lons)), new maps.LatLng(Math.max(...lats), Math.max(...lons)))
      m.fitBounds(bounds, { top: 36, right: 36, bottom: 36, left: 36 })
    }
  }, [])

  // 지도 만들기 (한 번)
  useEffect(() => {
    let alive = true
    const off = onNaverMapsFailure(() => latest.current.onFail())
    loadNaverMaps(keyId)
      .then((maps) => {
        if (!alive || !box.current) return
        sdk.current = maps
        const m = new maps.Map(box.current, {
          center: new maps.LatLng(33.38, 126.55),
          zoom: 10,
          minZoom: 7,
          scrollWheel: false, // 페이지를 내리다가 지도가 확대되지 않게 (확대는 +/- 단추로)
          zoomControl: true,
          zoomControlOptions: { position: maps.Position.TOP_RIGHT },
          mapDataControl: false,
          scaleControl: true,
        })
        map.current = m
        listeners.current.push(
          maps.Event.addListener(m, 'click', (e) => {
            if (Date.now() - lastMarkerClick.current < 400 || !e.coord) return
            latest.current.onPickPoint?.(e.coord.lat(), e.coord.lng())
          }),
        )
        ready.current = true
        draw()
      })
      .catch(() => alive && latest.current.onFail())
    return () => {
      alive = false
      off()
      const maps = sdk.current
      if (maps) [...listeners.current, ...markerListeners.current].forEach((l) => maps.Event.removeListener(l))
      listeners.current = []
      markerListeners.current = []
      overlays.current.forEach((o) => o.setMap(null))
      overlays.current = []
      map.current?.destroy()
      map.current = null
      ready.current = false
      fitted.current = ''
    }
  }, [keyId, draw])

  useEffect(() => {
    draw()
  }, [dots, lines, routes, selectedKey, draw])

  return <div ref={box} className="nmap" role="region" aria-label={label} />
}
