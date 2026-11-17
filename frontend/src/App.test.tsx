import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError } from './api/client'
import type { Api } from './api/client'
import { bootstrap, fakeApi, stage1, stage2 } from './test/fixtures'

async function start(api = fakeApi()) {
  render(<App api={api} />)
  await screen.findByRole('heading', { name: '어느 동네가 궁금한가요?' })
  return api
}

describe('머물멍 화면', () => {
  it('첫 화면에 데이터 배지, AI 설명 방식, 단계별 추천 질문, 읍면동 지도를 보여 줘요', async () => {
    await start()
    const badges = screen.getByRole('list', { name: '지금 쓰는 데이터와 AI 설명 방식' })
    expect(within(badges).getByText('샘플 데이터')).toBeInTheDocument()
    expect(within(badges).getByText('기본 (AI 없이)')).toBeInTheDocument()
    expect(screen.getAllByText(/^[123]단계$/)).toHaveLength(3) // 'Stage 1' 대신 '1단계'
    expect(screen.getAllByRole('article')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '성산읍에 누가 올까?' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /제주 읍면동 지도/ })).toBeInTheDocument()
  })

  it('추천 질문을 누르면 타이핑 없이 바로 답까지 가요', async () => {
    const api = await start()
    await userEvent.click(screen.getByRole('button', { name: '성산읍 청년 인구 왜 줄었어?' }))
    expect(await screen.findByRole('heading', { level: 2, name: stage1.headline })).toBeInTheDocument()
    expect(api.runStream).toHaveBeenCalledOnce()
    expect(screen.getByRole('heading', { name: '이렇게 이해하고 계산했어요' })).toBeInTheDocument() // 해석은 답과 함께 남아 있어요
    expect(screen.getByRole('button', { name: '청년이 머무는 동네' })).toHaveAttribute('aria-current', 'step')
  })

  it('Claude 모드에서는 도는 동안 멈추기를 누를 수 있고, 서버에도 멈추라고 알려요', async () => {
    const status = { ...bootstrap.status, llm_mode: 'anthropic' as const, llm_label: 'Claude Opus 5.5' }
    // 끝나지 않고 기다리다가, 멈추면 끊기는 스트리밍
    const runStream = vi.fn<Api['runStream']>((_q, _sid, on, signal) => {
      on.onRun?.('run-1')
      on.onProgress?.({ kind: 'start', run: 'run-1' })
      return new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    })
    const api = fakeApi({ bootstrap: vi.fn(async () => ({ ...bootstrap, status })), runStream })
    await start(api)
    await userEvent.click(screen.getByRole('button', { name: '성산읍 청년 인구 왜 줄었어?' }))
    await userEvent.click(await screen.findByRole('button', { name: '멈추기' }))
    expect(api.cancelRun).toHaveBeenCalledWith('run-1')
    expect(await screen.findByRole('alert')).toHaveTextContent('분석을 멈췄어요')
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeEnabled()
  })

  it('직접 쓴 질문은 확인 카드를 먼저 보여 주고, 실행을 눌러야 답을 만들어요', async () => {
    const api = await start()
    await userEvent.type(screen.getByLabelText('질문'), '성산읍 청년 인구 왜 줄었어?{Enter}')
    expect(await screen.findByRole('heading', { name: '이렇게 이해했어요' })).toBeInTheDocument()
    expect(api.runStream).not.toHaveBeenCalled()
    expect(screen.queryByText(stage1.headline)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '실행' }))
    expect(await screen.findByText(stage1.headline)).toBeInTheDocument()
  })

  it('다음 단계 단추로 Stage 2 로 넘어가고, 지난 질문으로 돌아갈 수 있어요', async () => {
    await start()
    await userEvent.click(screen.getByRole('button', { name: '성산읍 청년 인구 왜 줄었어?' }))
    await screen.findByText(stage1.headline)
    await userEvent.click(screen.getByRole('button', { name: /이 동네에 누가 올까/ }))
    expect(await screen.findByText(stage2.headline)).toBeInTheDocument()
    const history = screen.getByRole('region', { name: '지난 질문' })
    await userEvent.click(within(history).getByRole('button', { name: '성산읍 청년 인구 왜 줄었어?' }))
    expect(await screen.findByText(stage1.headline)).toBeInTheDocument()
    expect(screen.queryByText(stage2.headline)).toBeNull()
  })

  it('지도에서 읍면동을 고르고 처음부터 끝까지를 누르면 세 단계와 제안서가 나와요', async () => {
    const api = await start()
    await userEvent.selectOptions(screen.getByLabelText('읍면동 목록에서 고르기'), '성산읍')
    const panel = screen.getByText('서귀포시 · 서귀포시 동부').closest('aside')!
    await userEvent.click(within(panel).getByRole('button', { name: /처음부터 끝까지/ }))
    await waitFor(() => expect(document.querySelectorAll('.headline-text')).toHaveLength(3))
    expect(api.chainStream).toHaveBeenCalledWith('성산읍', 'sess-1', expect.anything(), expect.any(AbortSignal))
    const report = screen.getByRole('complementary', { name: '최종 제안서' })
    expect(within(report).getByRole('link', { name: /제안서 열기/ })).toHaveAttribute('href', '/api/reports/sample.html')
    expect(within(report).getByRole('link', { name: /HTML로 내려받기/ })).toHaveAttribute('href', '/api/reports/sample.html?download=true')
    const jump = screen.getByRole('navigation', { name: '단계로 이동' })
    expect(within(jump).getAllByRole('link').map((l) => l.getAttribute('href'))).toEqual(['#stage-1', '#stage-2', '#stage-3', '#report'])
  })

  it('첫 화면 맨 위에서 동네를 고르고 바로 처음부터 끝까지 볼 수 있어요', async () => {
    const api = await start()
    const hero = screen.getByRole('heading', { name: '어느 동네가 궁금한가요?' }).closest('header') as HTMLElement
    const run = within(hero).getByRole('button', { name: /처음부터 끝까지/ })
    expect(run).toBeDisabled() // 동네를 고르기 전에는 누를 수 없고, 아래에 무엇을 하는지 적혀 있어요
    expect(within(hero).getByText(/동네를 고르면 세 단계를 한 번에/)).toBeInTheDocument()
    await userEvent.selectOptions(within(hero).getByLabelText('읍면동 고르기'), '성산읍')
    expect(screen.getByLabelText('읍면동 목록에서 고르기')).toHaveValue('성산읍') // 지도 쪽 목록과 같은 값을 써요
    await userEvent.click(run)
    await waitFor(() => expect(api.chainStream).toHaveBeenCalledWith('성산읍', 'sess-1', expect.anything(), expect.any(AbortSignal)))
  })

  it('AI 설명 방식은 기본과 Claude 둘이고, 바꾸면 위쪽 배지도 바뀌어요', async () => {
    // API 키가 있는 PC처럼 클라우드 모드를 고를 수 있게 해요
    const llm = bootstrap.status.modes.llm.map((m) => (m.mode === 'anthropic' ? { ...m, available: true } : m))
    const status = { ...bootstrap.status, modes: { ...bootstrap.status.modes, llm } }
    const api = fakeApi({
      bootstrap: vi.fn(async () => ({ ...bootstrap, status })),
      setModes: vi.fn(async () => ({ ...status, llm_mode: 'anthropic' as const, llm_label: 'Claude Opus 5.5' })),
    })
    await start(api)
    const select = screen.getByRole('combobox', { name: 'AI 설명' })
    expect(within(select).getAllByRole('option').map((o) => o.getAttribute('value'))).toEqual(['template', 'anthropic'])
    await userEvent.selectOptions(select, 'anthropic')
    const badges = screen.getByRole('list', { name: '지금 쓰는 데이터와 AI 설명 방식' })
    expect(await within(badges).findByText('Claude Opus 5.5')).toBeInTheDocument()
    expect(api.setModes).toHaveBeenCalledWith({ llm_mode: 'anthropic' })
  })

  it('데이터 창고가 없는 모드는 고를 수 없어요', async () => {
    await start()
    expect(screen.getByRole('button', { name: '샘플' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '실데이터' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '센터' })).toBeDisabled()
    expect(screen.getByText('센터 데이터는 센터 PC에서만 열 수 있어요')).toBeInTheDocument() // 회색 단추의 이유를 글로
  })

  it('모드가 정해진 배포본에서는 고르는 단추 대신 지금 모드만 보여 줘요', async () => {
    const data = bootstrap.status.modes.data.map((m) => (m.mode === 'hub' ? { ...m, available: true, current: true } : { ...m, current: false }))
    const status = {
      ...bootstrap.status,
      data_mode: 'hub' as const,
      data_badge: '실데이터',
      llm_mode: 'anthropic' as const,
      llm_label: 'Claude Opus 5.5',
      modes: { ...bootstrap.status.modes, data, locked: true },
    }
    const api = fakeApi({ bootstrap: vi.fn(async () => ({ ...bootstrap, status })) })
    await start(api)
    const side = screen.getByRole('complementary', { name: '머물멍 메뉴' })
    expect(within(side).queryByRole('combobox')).toBeNull()
    expect(within(side).queryByRole('button', { name: '실데이터' })).toBeNull()
    expect(within(side).getByText('실데이터')).toBeInTheDocument()
    expect(within(side).getByText('Claude Opus 5.5')).toBeInTheDocument()
    expect(within(side).getByText('센터 데이터는 센터 PC에서만 열 수 있어요')).toBeInTheDocument()
    expect(api.setModes).not.toHaveBeenCalled()
  })

  it('실데이터가 있으면 샘플 단추는 보이지 않아요', async () => {
    // 허브 실데이터를 올려 두고 그 모드로 띄운 서버처럼 만들어요
    const data = bootstrap.status.modes.data.map((m) =>
      m.mode === 'hub' ? { ...m, available: true, current: true } : { ...m, current: false },
    )
    const status = { ...bootstrap.status, data_mode: 'hub' as const, data_badge: '실데이터', modes: { ...bootstrap.status.modes, data } }
    await start(fakeApi({ bootstrap: vi.fn(async () => ({ ...bootstrap, status })) }))
    expect(screen.queryByRole('button', { name: '샘플' })).toBeNull()
    expect(screen.getByRole('button', { name: '실데이터' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '센터' })).toBeDisabled()
  })

  it('실데이터가 있어도 지금 샘플을 보고 있으면 샘플 단추를 남겨 둬요', async () => {
    const data = bootstrap.status.modes.data.map((m) => (m.mode === 'hub' ? { ...m, available: true } : m))
    const status = { ...bootstrap.status, modes: { ...bootstrap.status.modes, data } }
    await start(fakeApi({ bootstrap: vi.fn(async () => ({ ...bootstrap, status })) }))
    expect(screen.getByRole('button', { name: '샘플' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '실데이터' })).toBeEnabled()
  })

  it('장소 없이 처음부터 끝까지를 누르면 읍면동을 고르라고 안내해요', async () => {
    const api = await start()
    const side = screen.getByRole('complementary', { name: '머물멍 메뉴' })
    expect(within(side).getByText('먼저 지도나 목록에서 읍면동을 골라 주세요')).toBeInTheDocument() // 누르기 전에 미리 알려요
    await userEvent.click(within(side).getByRole('button', { name: /처음부터 끝까지/ }))
    expect(await screen.findByRole('status')).toHaveTextContent('읍면동을 하나 골라 주세요')
    expect(api.understand).not.toHaveBeenCalled()
  })

  it('수록 기간과 출처를 볼 수 있어요', async () => {
    await start()
    await userEvent.click(screen.getByRole('button', { name: '수록 기간과 출처' }))
    const dialog = screen.getByRole('dialog', { hidden: true })
    expect(within(dialog).getByText('데이터 정보')).toBeInTheDocument()
    expect(within(dialog).getAllByRole('row', { hidden: true }).length).toBeGreaterThan(5)
    expect(within(dialog).getByText(/합성 자료예요/)).toBeInTheDocument()
  })

  it('서버에 연결하지 못하면 이유를 보여 주고 다시 연결할 수 있어요', async () => {
    const health = vi.fn<Api['health']>(async () => Promise.reject(new ApiError('백엔드 서버에 연결하지 못했어요.', 'offline', 0)))
    const api = fakeApi({ health })
    render(<App api={api} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('연결하지 못했어요')
    health.mockImplementationOnce(async () => ({ ok: true, ready: true, message: null }))
    await userEvent.click(screen.getByRole('button', { name: '다시 연결' }))
    expect(await screen.findByRole('heading', { name: '어느 동네가 궁금한가요?' })).toBeInTheDocument()
  })
})
