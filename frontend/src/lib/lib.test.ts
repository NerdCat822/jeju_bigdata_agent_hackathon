import { describe, expect, it } from 'vitest'
import { bootstrap } from '../test/fixtures'
import { axisTick, caption, compact, formatCell, josa, pct, seconds, shortMonth, valueLabel } from './format'
import { JEJU_OUTLINE, OFF_MAP_LAT, declutter, makeProjection } from './geo'
import { niceAxis, thin } from './scale'
import { SseParser } from './sse'

describe('숫자 표기 (백엔드와 같은 규칙)', () => {
  it('변화율은 부호를 붙이고 비중은 붙이지 않아요', () => {
    expect(pct(0.068)).toBe('+6.8%')
    expect(pct(-0.0547)).toBe('-5.5%')
    expect(pct(0.00001)).toBe('0.0%')
    expect(pct(0.175, 1, false)).toBe('17.5%')
    expect(pct(null)).toBe('-')
  })

  it('근거표 칸을 종류대로 적어요', () => {
    expect(formatCell(-0.0547, 'pct')).toBe('-5.5%')
    expect(formatCell(0.175, 'share')).toBe('17.5%')
    expect(formatCell(1193769, 'int')).toBe('1,193,769')
    expect(formatCell(1589.24, 'num1')).toBe('1,589.2')
    expect(formatCell(0.89, 'num2')).toBe('0.89')
    expect(formatCell(197_000_000, 'won')).toBe('1.97억')
    expect(formatCell(14_010_000, 'won')).toBe('1,401만')
    expect(formatCell(9800, 'won')).toBe('9,800')
    expect(formatCell(null, 'pct')).toBe('-')
    expect(formatCell('성산읍', 'pct')).toBe('성산읍')
    expect(formatCell(42)).toBe('42')
  })

  it('축 눈금은 짧게, 툴팁 값은 자세하게 적어요', () => {
    expect(compact(1_500_000)).toBe('150만')
    expect(compact(120_000_000)).toBe('1.2억')
    expect(axisTick(1_000_000, 'num', 1_193_769)).toBe('100만')
    expect(axisTick(-0.05, 'pct', 0.086)).toBe('-5.0%')
    expect(axisTick(0.2, 'pct', 0.28)).toBe('+20%')
    expect(axisTick(120, 'index', 133)).toBe('120')
    expect(valueLabel(1193769, 'num')).toBe('1,193,769')
    expect(valueLabel(133.42, 'index')).toBe('133.4')
    expect(valueLabel(null, 'num')).toBe('-')
    expect(shortMonth('2024-11')).toBe('24.11')
    expect(shortMonth('기준선')).toBe('기준선')
  })

  it('걸린 시간과 조사를 사람 말로 적어요', () => {
    expect(seconds(0.03)).toBe('0.1초 미만')
    expect(seconds(2.34)).toBe('2.3초')
    expect(seconds(21.8)).toBe('22초')
    expect(seconds(75)).toBe('1분 15초')
    expect(josa('성산읍', '을를')).toBe('성산읍을')
    expect(josa('아라동', '을를')).toBe('아라동을')
    expect(josa('구좌', '을를')).toBe('구좌를')
  })

  it('한 문장짜리 설명은 마침표를 떼고, 여러 문장은 그대로 둬요', () => {
    expect(caption('유동인구는 통신 데이터 추정치예요.')).toBe('유동인구는 통신 데이터 추정치예요')
    expect(caption('임계값 τ = ±3%. 위에서부터 먼저 맞는 유형이에요.')).toBe('임계값 τ = ±3%. 위에서부터 먼저 맞는 유형이에요.')
    expect(caption('탄력성 ε 1.0 가정')).toBe('탄력성 ε 1.0 가정')
  })
})

describe('축 눈금', () => {
  it('막대는 0 을 포함하고 깔끔한 간격을 써요', () => {
    const a = niceAxis([1193769, 1014704], true)
    expect(a.lo).toBe(0)
    expect(a.ticks).toEqual([0, 500000, 1000000, 1500000])
    const neg = niceAxis([-0.0547, -0.0861], true)
    expect(neg.hi).toBe(0)
    expect(neg.lo).toBeLessThanOrEqual(-0.0861)
    expect(neg.ticks).toContain(0)
  })

  it('선은 값의 범위만 감싸요', () => {
    const a = niceAxis([89.2, 133.4, 100], false)
    expect(a.lo).toBe(80)
    expect(a.hi).toBe(140)
    expect(niceAxis([5, 5], false).ticks.length).toBeGreaterThan(1)
  })

  it('가로축 이름표는 마지막 항목을 꼭 남기고 솎아요', () => {
    expect(thin(4, 6)).toEqual([0, 1, 2, 3])
    const picked = thin(24, 6)
    expect(picked[picked.length - 1]).toBe(23)
    expect(picked.length).toBeLessThanOrEqual(6)
    expect(new Set(picked.slice(1).map((v, i) => v - picked[i])).size).toBe(1) // 간격이 같아요
  })
})

describe('SSE 풀기', () => {
  it('이벤트 중간에서 끊겨 와도 이어 붙여요', () => {
    const p = new SseParser()
    expect(p.push('event: progress\ndata: {"kind":"st')).toEqual([])
    expect(p.push('art"}\n\nevent: answer\ndata: {"id":"a1"}\n\n')).toEqual([
      { event: 'progress', data: { kind: 'start' } },
      { event: 'answer', data: { id: 'a1' } },
    ])
  })

  it('줄바꿈이 CRLF 여도 되고, 깨진 조각은 건너뛰어요', () => {
    const p = new SseParser()
    const out = p.push('event: done\r\ndata: {"kind":"answer"}\r\n\r\nevent: answer\ndata: {깨짐\n\nevent: done\ndata: {"ok":true}\n\n')
    expect(out).toEqual([
      { event: 'done', data: { kind: 'answer' } },
      { event: 'done', data: { ok: true } },
    ])
  })
})

describe('지도', () => {
  it('본섬의 읍면동과 윤곽이 모두 지도 영역 안에 들어가요', () => {
    const proj = makeProjection(600, 320, 18)
    const pts = [
      ...bootstrap.places.filter((p) => p.lat < OFF_MAP_LAT).map((p) => proj.project(p.lon, p.lat)),
      ...JEJU_OUTLINE.map(([lon, lat]) => proj.project(lon, lat)),
    ]
    for (const p of pts) {
      expect(p.x).toBeGreaterThanOrEqual(0)
      expect(p.x).toBeLessThanOrEqual(600)
      expect(p.y).toBeGreaterThanOrEqual(0)
      expect(p.y).toBeLessThanOrEqual(320)
    }
    expect(proj.outline.startsWith('M')).toBe(true)
    expect(proj.outline.endsWith('Z')).toBe(true)
  })

  it('동서 방향과 남북 방향을 뒤집지 않아요', () => {
    const proj = makeProjection(600, 320)
    const seongsan = proj.project(126.91, 33.44)
    const hallim = proj.project(126.269, 33.411)
    const daejeong = proj.project(126.25, 33.222)
    expect(seongsan.x).toBeGreaterThan(hallim.x) // 성산은 동쪽
    expect(daejeong.y).toBeGreaterThan(hallim.y) // 대정은 남쪽 (화면에서는 아래)
  })

  it('겹친 점을 벌리고, 고정한 점은 제자리에 두고, 같은 입력에는 같은 결과를 내요', () => {
    const dots = [
      { x: 100, y: 100, r: 8, fixed: true },
      { x: 100, y: 100, r: 6 },
      { x: 101, y: 100, r: 6 },
      { x: 300, y: 50, r: 6 },
    ]
    const a = declutter(dots)
    expect(a[0]).toEqual({ x: 100, y: 100 })
    for (let i = 0; i < 3; i++) {
      for (let j = i + 1; j < 3; j++) {
        expect(Math.hypot(a[i].x - a[j].x, a[i].y - a[j].y)).toBeGreaterThanOrEqual(dots[i].r + dots[j].r)
      }
    }
    expect(a[3]).toEqual({ x: 300, y: 50 }) // 떨어져 있던 점은 그대로
    expect(declutter(dots)).toEqual(a)
  })
})
