import type { ReactNode } from 'react'
import type { Bootstrap } from '../api/types'
import hello from '../assets/mascot-hello.png'
import stage1 from '../assets/mascot-stage1.png'
import stage2 from '../assets/mascot-stage2.png'
import stage3 from '../assets/mascot-stage3.png'
import { Icon } from './Icon'
import { JejuMap } from './viz/JejuMap'
import type { MapDot } from './viz/JejuMap'

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
  '어디서 청년이 빠지고, 어디는 버티는지 봐요.',
  '빈자리를 채우는 소비가 어디에, 언제, 무엇에 오는지 봐요.',
  '항공편이 줄 때 수요가 어떻게 변하고, 어떤 노선으로 오는지 봐요.',
]

/** 첫 화면: 타이핑 없이 시작할 수 있게 단계별 추천 질문과 읍면동 지도를 보여 줘요. */
export function Home({ boot, picked, busy, onAsk, onPick, onDiagnose, onChain }: Props): ReactNode {
  const place = boot.places.find((p) => p.emd_nm === picked) ?? null
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
        <img src={hello} alt="" width={92} height={92} />
        <div>
          <h1>어느 동네가 궁금한가요?</h1>
          <p>읍면동 하나를 골라 청년이 머무는지, 누가 빈자리를 채우는지, 어떻게 오게 할지 차례로 살펴봐요.</p>
        </div>
      </header>

      <section className="stage-cards" aria-label="단계별 추천 질문">
        {boot.suggested.map((g, i) => (
          <article key={g.stage} className="stage-card">
            <img src={STAGE_ART[i]} alt="" width={64} height={64} />
            <p className="stage-card-step">Stage {g.stage}</p>
            <h2>{g.title}</h2>
            <p className="muted">{STAGE_ASK[i]}</p>
            <ul>
              {g.questions.map((q) => (
                <li key={q}>
                  <button type="button" className="chip chip-button" disabled={busy} onClick={() => onAsk(q)}>
                    {q}
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
            <p className="muted">점을 누르면 그 동네를 고를 수 있어요. 읍면동 43곳이 있어요.</p>
          </div>
          <label className="field picker-select">
            <span className="sr-only">읍면동 목록에서 고르기</span>
            <select className="select" value={picked ?? ''} onChange={(e) => onPick(e.target.value || null)}>
              <option value="">목록에서 고르기</option>
              {['제주시', '서귀포시'].map((city) => (
                <optgroup key={city} label={city}>
                  {boot.places
                    .filter((p) => p.city === city)
                    .map((p) => (
                      <option key={p.emd_cd} value={p.emd_nm}>
                        {p.emd_nm}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
        </div>
        <div className="picker-body">
          <JejuMap dots={dots} selectedKey={place?.emd_cd ?? null} onSelect={(d) => onPick(d.name)} label="제주 읍면동 지도. 점을 누르거나 Tab 키로 옮겨 Enter 로 고를 수 있어요." />
          <aside className="picker-panel" aria-live="polite">
            {place ? (
              <>
                <p className="picker-place">
                  <Icon name="pin" /> {place.emd_nm}
                </p>
                <p className="muted">
                  {place.city} · {place.region7}
                </p>
                <button type="button" className="btn btn-accent btn-wide" disabled={busy} onClick={() => onDiagnose(place.emd_nm)}>
                  청년 인구 진단
                </button>
                <button type="button" className="btn btn-dark btn-wide" disabled={busy} onClick={() => onChain(place.emd_nm)}>
                  처음부터 끝까지 <Icon name="play" size={14} />
                </button>
              </>
            ) : (
              <p className="muted">아직 고른 곳이 없어요. 지도의 점이나 목록에서 읍면동을 하나 골라 주세요.</p>
            )}
          </aside>
        </div>
        <p className="viz-note">읍면동 위치는 대략 좌표이고, 섬 윤곽은 위치를 가늠하기 위한 밑그림이에요. 도심의 동은 겹치지 않게 조금 벌려 놓았어요.</p>
      </section>
    </div>
  )
}
