/**
 * 네이버 지도 JS SDK (Dynamic Map) 불러오기.
 *
 * 인터넷이 없거나(센터 PC), 키가 없거나, 등록하지 않은 주소에서 열면 실패해요.
 * 실패하면 한 번만 알리고 다시 시도하지 않아요. 지도를 쓰는 곳은 기본 지도(JejuMap)로 바꿔 그려요.
 */

/* 이 화면이 쓰는 SDK 의 일부만 적었어요. */
export interface NLatLng {
  lat(): number
  lng(): number
}
export interface NMapObject {
  setMap(map: NMap | null): void
}
export interface NMarker extends NMapObject {
  setZIndex(z: number): void
}
export interface NPolyline extends NMapObject {
  setPath(path: NLatLng[]): void
  setOptions(opts: Record<string, unknown>): void
}
export interface NMap {
  fitBounds(bounds: unknown, margin?: number | { top: number; right: number; bottom: number; left: number }): void
  setCenter(c: NLatLng): void
  setZoom(z: number): void
  destroy(): void
}
export interface NaverMapsApi {
  Map: new (el: HTMLElement, opts: Record<string, unknown>) => NMap
  LatLng: new (lat: number, lng: number) => NLatLng
  LatLngBounds: new (sw: NLatLng, ne: NLatLng) => { extend(p: NLatLng): void }
  Marker: new (opts: Record<string, unknown>) => NMarker
  Polyline: new (opts: Record<string, unknown>) => NPolyline
  Point: new (x: number, y: number) => unknown
  Position: Record<string, unknown>
  Event: {
    addListener(target: unknown, name: string, fn: (e: { coord?: NLatLng }) => void): unknown
    removeListener(listener: unknown): void
  }
}

type NaverWindow = Window & { naver?: { maps?: NaverMapsApi }; navermap_authFailure?: () => void }

const SDK = 'https://oapi.map.naver.com/openapi/v3/maps.js'

let loading: Promise<NaverMapsApi> | null = null
let failed = false
const failListeners = new Set<() => void>()

function fail(): void {
  failed = true
  failListeners.forEach((f) => f())
}

/** SDK 를 한 번만 불러요. 실패했으면 바로 거절해요. */
export function loadNaverMaps(keyId: string, timeoutMs = 8000): Promise<NaverMapsApi> {
  if (failed) return Promise.reject(new Error('naver maps unavailable'))
  if (loading) return loading
  const w = window as NaverWindow
  loading = new Promise<NaverMapsApi>((resolve, reject) => {
    if (w.naver?.maps) {
      resolve(w.naver.maps)
      return
    }
    // 등록하지 않은 주소이거나 키가 틀리면 SDK 가 이 함수를 불러요 (지도를 만든 뒤에 불릴 수도 있어요)
    w.navermap_authFailure = fail
    const script = document.createElement('script')
    script.src = `${SDK}?ncpKeyId=${encodeURIComponent(keyId)}`
    script.async = true
    const timer = window.setTimeout(() => {
      fail()
      reject(new Error('naver maps timeout'))
    }, timeoutMs)
    script.onload = () => {
      window.clearTimeout(timer)
      if (w.naver?.maps) resolve(w.naver.maps)
      else {
        fail()
        reject(new Error('naver maps missing'))
      }
    }
    script.onerror = () => {
      window.clearTimeout(timer)
      fail()
      reject(new Error('naver maps load error'))
    }
    document.head.appendChild(script)
  })
  return loading
}

/** 인증 실패를 알려 줘요 (지도를 이미 만든 뒤에 올 수도 있어요). 돌려준 함수로 그만 들어요. */
export function onNaverMapsFailure(fn: () => void): () => void {
  if (failed) {
    fn()
    return () => {}
  }
  failListeners.add(fn)
  return () => failListeners.delete(fn)
}

export const naverMapsFailed = (): boolean => failed
