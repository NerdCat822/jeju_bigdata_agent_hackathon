import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { AddressHit, Bootstrap, Place } from '../api/types'
import hello from '../assets/mascot-hello.png'
import stage1 from '../assets/mascot-stage1.png'
import stage2 from '../assets/mascot-stage2.png'
import stage3 from '../assets/mascot-stage3.png'
import { Icon } from './Icon'
import { JejuMap } from './viz/JejuMap'
import type { MapDot } from './viz/JejuMap'
import { useMaps } from './viz/mapsContext'
import { NaverMap } from './viz/NaverMap'
import { useMapChoice } from './viz/useMapChoice'

interface Props {
  boot: Bootstrap
  picked: string | null
  busy: boolean
  onAsk: (question: string) => void
  onPick: (place: string | null) => void
  onDiagnose: (place: string) => void
  onChain: (place: string) => void
}

const STAGE_ART = [stage1, stage2, stage3]
const STAGE_ASK = [
  '어디서 청년이 빠지고, 어디는 버티는지 봐요',
  '빈자리를 채우는 소비가 어디에, 언제, 무엇에 오는지 봐요',
  '항공편이 줄 때 수요가 어떻게 변하고, 어떤 노선으로 오는지 봐요',
]

/** 읍면동 고르기 목록 (제주시 · 서귀포시로 묶어요). */
function PlaceOptions({ places }: { places: Place[] }): ReactNode {
  return (
    <>
      {['제주시', '서귀포시'].map((city) => (
        <optgroup key={city} label={city}>
          {places
            .filter((p) => p.city === city)
            .map((p) => (
              <option key={p.emd_cd} value={p.emd_nm}>
                {p.emd_nm}
              </option>
            ))}
        </optgroup>
      ))}
    </>
  )
}

const why = (e: unknown, fallback: string): string => (e instanceof ApiError && e.status !== 503 ? e.message : fallback)

/** 주소로 읍면동 찾기 (네이버 Geocoding). 가게·집 주소는 알아도 행정동 이름은 모를 때 써요. */
function AddressSearch({ onPick }: { onPick: (place: string) => void }): ReactNode {
  const { api } = useMaps()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<AddressHit[] | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  if (!api) return null
  const submit = (e: FormEvent): void => {
    e.preventDefault()
    const text = q.trim()
    if (text.length < 2 || busy) return
    setBusy(true)
    setMsg('')
    api
      .mapSearch(text)
      .then((found) => {
        const inside = found.filter((h) => h.emd_nm)
        if (inside.length === 1) {
          onPick(inside[0].emd_nm!)
          setHits(null)
          setMsg(`${inside[0].address} → ${inside[0].emd_nm}을 골랐어요`)
        } else {
          setHits(found)
          setMsg(found.length ? '' : '제주의 도로명이나 지번 주소로 찾아 주세요. 장소 이름은 찾지 못해요')
        }
      })
      .catch((err: unknown) => setMsg(why(err, '지금은 주소를 찾을 수 없어요. 지도나 목록에서 골라 주세요')))
      .finally(() => setBusy(false))
  }
  return (
    <div className="addr">
      <form className="addr-form" onSubmit={submit} role="search" aria-label="주소로 읍면동 찾기">
        <label className="sr-only" htmlFor="addr-input">
          주소로 찾기
        </label>
        <input id="addr-input" className="input" value={q} maxLength={80} placeholder="주소로 찾기 (예: 성산읍 일출로 284-12)" onChange={(e) => setQ(e.target.value)} />
        <button type="submit" className="btn btn-outline" disabled={busy || q.trim().length < 2}>
          찾기
        </button>
      </form>
      {hits && hits.length > 0 && (
        <ul className="addr-hits" aria-label="찾은 주소">
          {hits.map((h) => (
            <li key={`${h.lat},${h.lon}`}>
              <button type="button" className="ask-row" disabled={!h.emd_nm} onClick={() => h.emd_nm && (onPick(h.emd_nm), setHits(null), setMsg(`${h.address} → ${h.emd_nm}을 골랐어요`))}>
                <span>{h.address}</span>
                <span className="muted small">{h.emd_nm ?? '43개 읍면동 밖'}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="addr-msg muted small" aria-live="polite">
        {msg}
      </p>
    </div>
  )
}

/**
 * 첫 화면: 타이핑 없이 시작할 수 있게 단계별 추천 질문과 읍면동 지도를 보여 줘요.
 * 가장 많이 쓰는 흐름(동네 고르기 → 처음부터 끝까지)은 인사말 바로 아래에 한 줄로 둬요.
 */
export function Home({ boot, picked, busy, onAsk, onPick, onDiagnose, onChain }: Props): ReactNode {
  const place = boot.places.find((p) => p.emd_nm === picked) ?? null
  const choice = useMapChoice()
  const { api } = useMaps()
  const [mapMsg, setMapMsg] = useState('')
  // 네이버 지도에서 점이 아닌 곳을 누르면 그 자리가 속한 읍면동을 골라요 (Reverse Geocoding)
  const pickPoint = (lat: number, lon: number): void => {
    if (!api) return
    setMapMsg('그 자리의 읍면동을 찾고 있어요')
    api
      .mapLocate(lat, lon)
      .then((p) => {
        onPick(p.emd_nm)
        setMapMsg(`${p.emd_nm}을 골랐어요`)
      })
      .catch((err: unknown) => setMapMsg(why(err, '지금은 지도에서 동네를 찾을 수 없어요. 점이나 목록에서 골라 주세요')))
  }
  const dots: MapDot[] = boot.places.map((p) => ({
    key: p.emd_cd,
    name: p.emd_nm,
    lat: p.lat,
    lon: p.lon,
    role: p.emd_nm === picked ? 'target' : 'other',
    labeled: p.area_type === '읍면' || p.emd_nm === picked,
    detail: `${p.city} · ${p.area_type === '읍면' ? '읍면 지역' : '동 지역'}`,
  }))
  return (
    <div className="home">
      <header className="hero">
        <img src={hello} alt="" width={72} height={72} />
        <div className="hero-body">
          <h1>어느 동네가 궁금한가요?</h1>
          <p>읍면동 하나를 골라 청년이 머무는지, 누가 빈자리를 채우는지, 어떻게 오게 할지 차례로 살펴봐요</p>
          <div className="hero-pick">
            <label className="field hero-select">
              <span className="sr-only">읍면동 고르기</span>
              <select className="select" value={picked ?? ''} onChange={(e) => onPick(e.target.value || null)}>
                <option value="">읍면동 고르기</option>
                <PlaceOptions places={boot.places} />
              </select>
            </label>
            <button type="button" className="btn btn-accent" disabled={busy || !place} onClick={() => place && onChain(place.emd_nm)}>
              처음부터 끝까지 <Icon name="arrow" />
            </button>
          </div>
          <p className="hero-hint">{place ? `${place.emd_nm}의 세 단계를 한 번에 분석하고 최종 제안서까지 만들어요` : '동네를 고르면 세 단계를 한 번에 분석하고 최종 제안서까지 만들어요'}</p>
        </div>
      </header>

      <section className="stages" aria-label="단계별 추천 질문">
        {boot.suggested.map((g, i) => (
          <article key={g.stage} className="stage-col">
            <div className="stage-head">
              <span className="stage-no">{g.stage}단계</span>
              <img src={STAGE_ART[i]} alt="" width={40} height={40} />
            </div>
            <h2>{g.title}</h2>
            <p className="muted">{STAGE_ASK[i]}</p>
            <ul>
              {g.questions.map((q) => (
                <li key={q}>
                  <button type="button" className="ask-row" disabled={busy} onClick={() => onAsk(q)}>
                    <span>{q}</span>
                    <Icon name="arrow" />
                  </button>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="picker" aria-labelledby="picker-title">
        <div className="picker-head">
          <div>
            <h2 id="picker-title">지도에서 읍면동 고르기</h2>
            <p className="muted small">읍면동 43곳 가운데 하나를 골라요</p>
          </div>
          <div className="picker-tools">
            {choice.toggle}
            <label className="field picker-select">
              <span className="sr-only">읍면동 목록에서 고르기</span>
              <select className="select" value={picked ?? ''} onChange={(e) => onPick(e.target.value || null)}>
                <option value="">목록에서 고르기</option>
                <PlaceOptions places={boot.places} />
              </select>
            </label>
          </div>
        </div>
        {/* 주소 찾기는 서버의 Geocoding 만 써서, 화면 지도가 간단한 지도여도 쓸 수 있어요 */}
        {choice.keyId && <AddressSearch onPick={onPick} />}
        <div className="picker-body">
          {choice.naver && choice.keyId ? (
            <NaverMap
              keyId={choice.keyId}
              dots={dots}
              selectedKey={place?.emd_cd ?? null}
              onSelect={(d) => onPick(d.name)}
              onPickPoint={pickPoint}
              label="제주 읍면동 네이버 지도. 점이나 지도 위 아무 곳을 누르면 그 읍면동을 골라요. 목록이나 '간단한 지도로 보기'로도 고를 수 있어요."
              onFail={choice.fail}
            />
          ) : (
            <JejuMap dots={dots} selectedKey={place?.emd_cd ?? null} onSelect={(d) => onPick(d.name)} label="제주 읍면동 지도. 점을 누르거나 Tab 키로 옮겨 Enter 로 고를 수 있어요." />
          )}
          <aside className="picker-panel" aria-live="polite">
            {place ? (
              <>
                <p className="picker-place">
                  <Icon name="pin" /> {place.emd_nm}
                </p>
                <p className="muted small">
                  {place.city} · {place.region7}
                </p>
                <button type="button" className="btn btn-accent btn-wide" disabled={busy} onClick={() => onDiagnose(place.emd_nm)}>
                  청년 인구 진단
                </button>
                <button type="button" className="btn btn-outline btn-wide" disabled={busy} onClick={() => onChain(place.emd_nm)}>
                  처음부터 끝까지
                </button>
              </>
            ) : (
              <p className="muted small">{choice.naver ? '지도의 점이나 아무 곳, 또는 목록에서 읍면동을 골라 주세요' : '지도의 점이나 목록에서 읍면동을 하나 골라 주세요'}</p>
            )}
            {mapMsg && (
              <p className="muted small" role="status">
                {mapMsg}
              </p>
            )}
          </aside>
        </div>
        <p className="viz-note">
          {choice.naver
            ? '점은 읍면동의 대략 위치예요. 지도 위 아무 곳을 누르면 그 자리가 속한 읍면동을 골라요 (지도 © NAVER Corp.)'
            : '읍면동 위치는 대략 좌표이고, 섬 윤곽은 위치를 가늠하기 위한 밑그림이에요. 도심의 동은 겹치지 않게 조금 벌려 놓았어요'}
        </p>
      </section>
    </div>
  )
}
