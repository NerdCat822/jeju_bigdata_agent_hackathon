import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Api } from '../api/client'
import { bootstrap, fakeApi, stage1 } from '../test/fixtures'
import { currentPlace, useAgent } from './agent'

async function ready(api = fakeApi()) {
  const hook = renderHook(() => useAgent(api))
  await waitFor(() => expect(hook.result.current.state.boot).not.toBeNull())
  return { ...hook, api }
}

describe('화면 상태', () => {
  it('처음에 상태와 읍면동 목록을 불러와요', async () => {
    const { result } = await ready()
    expect(result.current.state.boot?.places).toHaveLength(43)
    expect(result.current.state.turns).toEqual([])
  })

  it('데이터 창고가 없으면 만드는 법을 알려 주고, 다시 연결할 수 있어요', async () => {
    const health = vi.fn<Api['health']>(async () => ({ ok: true, ready: false, message: '데이터 창고가 없어요. build-data 를 실행하세요.' }))
    const api = fakeApi({ health })
    const { result } = renderHook(() => useAgent(api))
    await waitFor(() => expect(result.current.state.bootError).toContain('build-data'))
    health.mockResolvedValueOnce({ ok: true, ready: true, message: null })
    await act(() => result.current.actions.reload())
    expect(result.current.state.boot).toBe(bootstrap)
  })

  it('직접 쓴 질문은 확인 카드에서 멈추고, 실행을 눌러야 답을 만들어요', async () => {
    const { result, api } = await ready()
    await act(() => result.current.actions.ask('성산읍 청년 인구 왜 줄었어?'))
    let turn = result.current.state.turns[0]
    expect(turn.status).toBe('confirm')
    expect(turn.card?.runnable).toBe(true)
    expect(api.runStream).not.toHaveBeenCalled()
    expect(result.current.state.sessionId).toBe('sess-1')

    await act(() => result.current.actions.runTurn(turn.id))
    turn = result.current.state.turns[0]
    expect(turn.status).toBe('done')
    expect(turn.answers).toEqual([stage1])
    expect(turn.progress.map((p) => p.kind)).toEqual(['start', 'tool'])
    expect(result.current.state.busy).toBe(false)
    expect(currentPlace(result.current.state)).toBe('성산읍')
  })

  it('추천 질문은 바로 실행하고, 같은 세션을 이어 써요', async () => {
    const { result, api } = await ready()
    await act(() => result.current.actions.ask('성산읍 청년 인구 진단', { autoRun: true }))
    await act(() => result.current.actions.ask('성산읍 30대만 보면?', { autoRun: true }))
    expect(result.current.state.turns.map((t) => t.status)).toEqual(['done', 'done'])
    expect(vi.mocked(api.understand).mock.calls.map((c) => c[1])).toEqual([null, 'sess-1'])
    expect(result.current.state.activeId).toBe(result.current.state.turns[1].id)
  })

  it('실행할 수 없는 해석은 실행하지 않고 카드에 남겨요', async () => {
    const { result, api } = await ready()
    await act(() => result.current.actions.ask('오늘 날씨 어때?', { autoRun: true }))
    const turn = result.current.state.turns[0]
    expect(turn.status).toBe('confirm')
    expect(turn.card?.runnable).toBe(false)
    expect(api.runStream).not.toHaveBeenCalled()
  })

  it('처음부터 끝까지는 단계마다 답을 받고 제안서 주소를 남겨요', async () => {
    const { result, api } = await ready()
    await act(async () => result.current.actions.runChain('성산읍'))
    await waitFor(() => expect(result.current.state.turns[0]?.status).toBe('done'))
    const turn = result.current.state.turns[0]
    expect(api.chainStream).toHaveBeenCalledWith('성산읍', 'sess-1', expect.anything(), expect.any(AbortSignal))
    expect(turn.answers.map((a) => a.stage)).toEqual([1, 2, 3])
    expect(turn.kind).toBe('chain')
    expect(turn.reportUrl).toBe('/api/reports/sample.html')
  })

  it('카드를 고치면 서버가 바로잡은 해석으로 바꾸고, 다시 실행하기 전까지 표시해 둬요', async () => {
    const { result, api } = await ready()
    await act(() => result.current.actions.ask('성산읍 청년 인구 진단'))
    const id = result.current.state.turns[0].id
    await act(() => result.current.actions.editCard(id, { place_name: '구좌읍', place_key: null, place_kind: null }))
    const turn = result.current.state.turns[0]
    expect(turn.dirty).toBe(true)
    expect(turn.card?.query.place_name).toBe('구좌읍')
    const sent = vi.mocked(api.confirm).mock.calls[0][0]
    expect(sent.place_name).toBe('구좌읍')
    expect(sent.place_key).toBeNull()
    expect(sent.question).toBe('성산읍 청년 인구 진단') // 고치지 않은 값은 그대로 보내요
    await act(() => result.current.actions.runTurn(id))
    expect(result.current.state.turns[0].dirty).toBe(false)
  })

  it('단계 단추는 이미 본 답이 있으면 그 화면으로 가고, 없으면 대표 질문을 실행해요', async () => {
    const { result, api } = await ready()
    await act(() => result.current.actions.ask('성산읍 청년 인구 진단', { autoRun: true }))
    const first = result.current.state.turns[0].id
    await act(async () => result.current.actions.openStage(2))
    await waitFor(() => expect(result.current.state.turns).toHaveLength(2))
    expect(vi.mocked(api.understand).mock.calls[1][0]).toBe('성산읍에 누가 올까?')
    await waitFor(() => expect(result.current.state.turns[1].status).toBe('done'))
    await act(async () => result.current.actions.openStage(1))
    expect(result.current.state.activeId).toBe(first)
    expect(result.current.state.turns).toHaveLength(2)
  })

  it('장소를 모르면 단계 단추와 연계 실행이 읍면동을 고르라고 안내해요', async () => {
    const { result, api } = await ready()
    await act(async () => result.current.actions.openStage(2))
    expect(result.current.state.notice?.text).toContain('읍면동')
    await act(async () => result.current.actions.runChain())
    expect(api.understand).not.toHaveBeenCalled()
    act(() => result.current.actions.pickPlace('아라동'))
    expect(currentPlace(result.current.state)).toBe('아라동')
  })

  it('실행하다 생긴 오류는 그 질문에 남기고, 다음 질문을 막지 않아요', async () => {
    const api = fakeApi({ runStream: vi.fn(async () => Promise.reject(new ApiError('응답이 중간에 끊겼어요.', 'stream_closed', 200))) })
    const { result } = await ready(api)
    await act(() => result.current.actions.ask('성산읍 청년 인구 진단', { autoRun: true }))
    expect(result.current.state.turns[0].status).toBe('error')
    expect(result.current.state.turns[0].error).toContain('끊겼어요')
    expect(result.current.state.busy).toBe(false)
  })

  it('제안서를 만들면 지금 보는 질문에 주소를 붙여요', async () => {
    const { result, api } = await ready()
    await act(() => result.current.actions.ask('성산읍 청년 인구 진단', { autoRun: true }))
    await act(() => result.current.actions.makeReport())
    expect(api.report).toHaveBeenCalledWith('sess-1', '성산읍')
    expect(result.current.state.turns[0].reportUrl).toBe('/api/reports/sample.html')
  })

  it('LLM 모드만 바꾸면 대화를 이어 가고, 데이터 모드를 바꾸면 새로 시작해요', async () => {
    const { result } = await ready()
    await act(() => result.current.actions.ask('성산읍 청년 인구 진단', { autoRun: true }))
    await act(() => result.current.actions.setModes({ llm_mode: 'anthropic' }))
    expect(result.current.state.boot?.status.llm_mode).toBe('anthropic')
    expect(result.current.state.turns).toHaveLength(1)
    await act(() => result.current.actions.setModes({ data_mode: 'hub' }))
    expect(result.current.state.boot?.status.data_mode).toBe('hub')
    expect(result.current.state.turns).toEqual([])
    expect(result.current.state.sessionId).toBeNull()
  })

  it('LLM을 쓸 수 없어 템플릿으로 내려가면 이유를 알려요', async () => {
    const api = fakeApi({ setModes: vi.fn(async () => ({ ...bootstrap.status, llm_mode: 'template', llm_note: 'Anthropic 인증 정보를 찾지 못했어요. 템플릿 모드로 실행해요.' })) })
    const { result } = await ready(api)
    await act(() => result.current.actions.setModes({ llm_mode: 'anthropic' }))
    expect(result.current.state.notice?.tone).toBe('warn')
    expect(result.current.state.notice?.text).toContain('Anthropic')
  })
})
