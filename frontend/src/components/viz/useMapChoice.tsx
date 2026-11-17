import { useState } from 'react'
import type { ReactNode } from 'react'
import { naverMapsFailed } from '../../lib/naverMaps'
import { useMaps } from './mapsContext'

export interface MapChoice {
  /** 네이버 지도로 그릴지 (키가 있고, 실패하지 않았고, 사람이 기본 지도를 고르지 않았을 때). */
  naver: boolean
  keyId: string | null
  /** 네이버 지도 ↔ 간단한 지도 바꾸기 단추 (네이버 지도를 쓸 수 없으면 null). */
  toggle: ReactNode
  /** 네이버 지도를 불러오지 못했을 때 불러요. */
  fail: () => void
}

/**
 * 어느 지도로 그릴지 정해요. 기본은 네이버 지도이고, 키가 없거나 인터넷이 없으면(센터 PC) 간단한 지도예요.
 * 간단한 지도는 키보드로 점마다 이름을 읽을 수 있어서, 언제든 바꿔 볼 수 있게 단추를 둬요.
 */
export function useMapChoice(): MapChoice {
  const { keyId } = useMaps()
  const [basic, setBasic] = useState(false)
  const [failed, setFailed] = useState(() => naverMapsFailed())
  const usable = !!keyId && !failed
  const naver = usable && !basic
  const toggle = usable ? (
    <button type="button" className="viz-toggle" aria-pressed={!naver} onClick={() => setBasic((v) => !v)}>
      {naver ? '간단한 지도로 보기' : '네이버 지도로 보기'}
    </button>
  ) : null
  return { naver, keyId, toggle, fail: () => setFailed(true) }
}
