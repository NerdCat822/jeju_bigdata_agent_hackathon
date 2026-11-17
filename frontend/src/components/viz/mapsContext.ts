import { createContext, useContext } from 'react'
import type { Api } from '../../api/client'

export interface MapsValue {
  /** 네이버 지도 Client ID. 서버에 지도 키가 없으면 null 이고, 화면은 기본 지도만 써요. */
  keyId: string | null
  /** 지도 API (점 → 읍면동, 주소 찾기, 코스 도로 경로). */
  api: Pick<Api, 'mapLocate' | 'mapSearch' | 'mapRoute'> | null
}

export const MapsContext = createContext<MapsValue>({ keyId: null, api: null })

export const useMaps = (): MapsValue => useContext(MapsContext)
