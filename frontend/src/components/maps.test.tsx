import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { MapSpec } from '../api/types'
import { bootstrap, fakeApi, stage3 } from '../test/fixtures'
import { MapsContext } from './viz/mapsContext'
import { MapCard } from './viz/MapCard'

/* 네이버 지도 SDK 대신 쓰는 가짜. 만든 점·선을 기억하고, 지도 클릭을 흉내 낼 수 있어요. */
const sdk = vi.hoisted(() => {
  const state = {
    mode: 'ok' as 'ok' | 'fail',
    markers: [] as { title: string; map: unknown }[],
    polylines: [] as { pathLength: number; style: string }[],
    mapClick: null as null | ((e: { coord: { lat(): number; lng(): number } }) => void),
  }
  class LatLng {
    y: number
    x: number
    constructor(y: number, x: number) {
      this.y = y
      this.x = x
    }
    lat(): number {
      return this.y
    }
    lng(): number {
      return this.x
    }
  }
  const api = {
    Map: class {
      fitBounds(): void {}
      setCenter(): void {}
      setZoom(): void {}
      destroy(): void {}
    },
    LatLng,
    LatLngBounds: class {
      extend(): void {}
    },
    Marker: class {
      map: unknown
      title: string
      constructor(o: { title: string; map: unknown }) {
        this.title = o.title
        this.map = o.map
        state.markers.push(this)
      }
      setMap(m: unknown): void {
        this.map = m
      }
      setZIndex(): void {}
    },
    Polyline: class {
      constructor(o: { path: unknown[]; strokeStyle: string }) {
        state.polylines.push({ pathLength: o.path.length, style: o.strokeStyle })
      }
      setMap(): void {}
      setPath(): void {}
      setOptions(): void {}
    },
    Point: class {},
    Position: { TOP_RIGHT: 1 },
    Event: {
      addListener(target: unknown, name: string, fn: (e: { coord: { lat(): number; lng(): number } }) => void) {
        if (name === 'click' && target instanceof api.Map) state.mapClick = fn
        return {}
      },
      removeListener(): void {},
    },
  }
  return { state, api }
})

vi.mock('../lib/naverMaps', () => ({
  loadNaverMaps: () => (sdk.state.mode === 'ok' ? Promise.resolve(sdk.api) : Promise.reject(new Error('offline'))),
  onNaverMapsFailure: () => () => {},
  naverMapsFailed: () => false,
}))

beforeEach(() => {
  sdk.state.mode = 'ok'
  sdk.state.markers = []
  sdk.state.polylines = []
  sdk.state.mapClick = null
})

const withKey = { ...bootstrap, naver_map_key_id: 'test-key' }
const courseMap = stage3.maps[0] as MapSpec

describe('네이버 지도', () => {
  it('지도 키가 없으면 지금처럼 간단한 지도만 그리고, 바꾸기 단추도 주소 찾기도 없어요', async () => {
    render(<App api={fakeApi()} />)
    await screen.findByRole('heading', { name: '어느 동네가 궁금한가요?' })
    expect(screen.getByRole('group', { name: /제주 읍면동 지도/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /지도로 보기/ })).toBeNull()
    expect(screen.queryByRole('search', { name: '주소로 읍면동 찾기' })).toBeNull()
  })

  it('지도 키가 있으면 첫 화면을 네이버 지도로 그리고, 지도 아무 곳을 누르면 그 자리의 읍면동을 골라요', async () => {
    const api = fakeApi({
      bootstrap: vi.fn(async () => withKey),
      mapLocate: vi.fn(async () => ({ emd_cd: '50130259', emd_nm: '성산읍' })),
    })
    render(<App api={api} />)
    await screen.findByRole('region', { name: /제주 읍면동 네이버 지도/ })
    await waitFor(() => expect(sdk.state.markers.length).toBe(bootstrap.places.length))
    sdk.state.mapClick?.({ coord: { lat: () => 33.4589, lng: () => 126.9408 } })
    await waitFor(() => expect(screen.getByLabelText('읍면동 목록에서 고르기')).toHaveValue('성산읍'))
    expect(api.mapLocate).toHaveBeenCalledWith(33.4589, 126.9408)
    expect(screen.getByRole('status')).toHaveTextContent('성산읍을 골랐어요')
    // 언제든 간단한 지도로 바꿔 볼 수 있어요 (키보드로 점을 하나씩 읽을 수 있어요)
    await userEvent.click(screen.getByRole('button', { name: '간단한 지도로 보기' }))
    expect(screen.getByRole('group', { name: /제주 읍면동 지도/ })).toBeInTheDocument()
  })

  it('주소로 찾으면 그 주소의 읍면동을 골라요', async () => {
    const api = fakeApi({
      bootstrap: vi.fn(async () => withKey),
      mapSearch: vi.fn(async () => [{ address: '제주특별자치도 서귀포시 성산읍 일출로 284-12', jibun: '', lat: 33.46, lon: 126.94, emd_cd: '50130259', emd_nm: '성산읍' }]),
    })
    render(<App api={api} />)
    const form = await screen.findByRole('search', { name: '주소로 읍면동 찾기' })
    await userEvent.type(within(form).getByLabelText('주소로 찾기'), '성산읍 일출로 284-12')
    await userEvent.click(within(form).getByRole('button', { name: '찾기' }))
    await waitFor(() => expect(screen.getByLabelText('읍면동 목록에서 고르기')).toHaveValue('성산읍'))
    expect(api.mapSearch).toHaveBeenCalledWith('성산읍 일출로 284-12')
    expect(screen.getByText(/일출로 284-12 → 성산읍을 골랐어요/)).toBeInTheDocument()
  })

  it('네이버 지도를 불러오지 못하면(인터넷이 없는 센터 PC) 간단한 지도로 바꿔 그려요', async () => {
    sdk.state.mode = 'fail'
    render(<App api={fakeApi({ bootstrap: vi.fn(async () => withKey) })} />)
    expect(await screen.findByRole('group', { name: /제주 읍면동 지도/ })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /네이버 지도/ })).toBeNull()
  })

  it('코스 지도는 코스마다 자동차 도로 경로를 그리고 거리와 시간을 자동차 기준이라고 밝혀요', async () => {
    const mapRoute = vi.fn(async (keys: string[]) => ({ distance_m: 45_627, duration_s: 3_358, path: keys.map((_, i) => [33.4 + i * 0.01, 126.5 + i * 0.1] as [number, number]) }))
    render(
      <MapsContext.Provider value={{ keyId: 'test-key', api: { mapRoute, mapLocate: vi.fn(), mapSearch: vi.fn() } }}>
        <MapCard spec={courseMap} wide />
      </MapsContext.Provider>,
    )
    const list = await screen.findByRole('list', { name: '코스별 도로 거리와 시간' })
    expect(mapRoute).toHaveBeenCalledTimes(courseMap.lines.length)
    expect(within(list).getAllByRole('listitem')).toHaveLength(courseMap.lines.length)
    expect(within(list).getAllByText('도로 45.6km · 자동차 약 56분')).toHaveLength(courseMap.lines.length)
    expect(screen.getByText(/자동차 기준이에요. 버스는 정류장을 들르고/)).toBeInTheDocument()
    await waitFor(() => expect(sdk.state.polylines.some((l) => l.style === 'solid')).toBe(true)) // 받은 도로 경로는 실선
  })
})
