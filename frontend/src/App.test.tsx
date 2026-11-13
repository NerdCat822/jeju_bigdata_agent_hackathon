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
  it('첫 화면에 데이터 배지, LLM 모드, 단계별 추천 질문, 읍면동 지도를 보여 줘요', async () => {
    await start()
    const badges = screen.getByRole('list', { name: '지금 쓰는 데이터와 LLM 모드' })
    expect(within(badges).getByText('샘플 데이터')).toBeInTheDocument()
    expect(within(badges).getByText('템플릿 (LLM 없음)')).toBeInTheDocument()
    expect(screen.getAllByRole('article')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '성산읍에 누가 올까?' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /제주 읍면동 지도/ })).toBeInTheDocument()
  })

  it('추천 질문을 누르면 타이핑 없이 바로 답까지 가요', async () => {
    const api = await start()
    await userEvent.click(screen.getByRole('button', { name: '성산읍 청년 인구 왜 줄었어?' }))
    expect(await screen.findByRole('heading', { level: 2, name: stage1.headline })).toBeInTheDocument()
    expect(api.runStream).toHaveBeenCalledOnce()
    expect(screen.getByRole('heading', { name: '이렇게 이해했어요' })).toBeInTheDocument() // 해석은 답과 함께 남아 있어요
    expect(screen.getByRole('button', { name: '청년이 머무는 동네' })).toHaveAttribute('aria-current', 'step')
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
    await waitFor(() => expect(screen.getAllByText('한 줄 결론')).toHaveLength(3))
    expect(api.chainStream).toHaveBeenCalledWith('성산읍', 'sess-1', expect.anything())
    const report = screen.getByRole('complementary', { name: '최종 제안서' })
    expect(within(report).getByRole('link', { name: /제안서 열기/ })).toHaveAttribute('href', '/api/reports/sample.html')
    expect(within(report).getByRole('link', { name: /내려받기/ })).toHaveAttribute('href', '/api/reports/sample.html?download=true')
    expect(screen.getByRole('navigation', { name: '단계로 이동' })).toBeInTheDocument()
  })

  it('LLM 모드를 바꾸면 위쪽 배지도 바뀌어요', async () => {
    const api = fakeApi({
      setModes: vi.fn(async () => ({ ...bootstrap.status, llm_mode: 'ollama', llm_label: '로컬 · qwen3:4b' })),
    })
    await start(api)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'LLM 모드' }), 'ollama')
    const badges = screen.getByRole('list', { name: '지금 쓰는 데이터와 LLM 모드' })
    expect(await within(badges).findByText('로컬 · qwen3:4b')).toBeInTheDocument()
    expect(api.setModes).toHaveBeenCalledWith({ llm_mode: 'ollama' })
  })

  it('데이터 창고가 없는 모드는 고를 수 없어요', async () => {
    await start()
    expect(screen.getByRole('button', { name: '샘플' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '실데이터' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '센터' })).toBeDisabled()
  })

  it('장소 없이 처음부터 끝까지를 누르면 읍면동을 고르라고 안내해요', async () => {
    const api = await start()
    const side = screen.getByRole('complementary', { name: '머물멍 메뉴' })
    await userEvent.click(within(side).getByRole('button', { name: /처음부터 끝까지/ }))
    expect(await screen.findByRole('status')).toHaveTextContent('읍면동을 하나 골라 주세요')
    expect(api.understand).not.toHaveBeenCalled()
  })

  it('수록 기간과 출처를 볼 수 있어요', async () => {
    await start()
    await userEvent.click(screen.getByRole('button', { name: /수록 기간과 출처 보기/ }))
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
