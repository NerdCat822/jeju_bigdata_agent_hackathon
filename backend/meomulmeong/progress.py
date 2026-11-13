"""진행 알림: 답을 만드는 동안 지금 무엇을 하는지 화면에 알려요.

웹 API의 스트리밍 응답이 듣는 쪽이에요. 듣는 쪽이 없으면 아무 일도 하지 않아요.

    with progress.listen(queue.put):      # 이 스레드에서 나오는 알림을 받아요
        agent.ask("성산읍 처음부터 끝까지")

알림 하나는 dict 예요: {"kind": "tool", "tool": "s1_trend", "label": "청년 인구 추이 계산", "ok": True, "seconds": 0.05}
kind 는 stage(연계 실행의 단계 시작) · tool(도구 하나 끝) · llm(LLM 호출 시작) · llm_result(LLM 답 검증 결과) · answer(답 하나 완성).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

Listener = Callable[[dict[str, Any]], None]

_listener: ContextVar[Listener | None] = ContextVar("meomul_progress", default=None)

# 화면에 그대로 보여 줄 짧은 이름
TOOL_LABEL = {
    "resolve_place": "장소 확인",
    "search_catalog": "관련 테이블 찾기",
    "run_sql": "조회 실행",
    "s1_trend": "청년 인구 추이 계산",
    "s1_classify": "읍면동 유형 분류",
    "s1_peers": "비슷한 읍면 찾기",
    "s1_zone": "지구 묶음 진단",
    "s2_shift": "관광객 소비 구조 분석",
    "s2_playbook": "제안 규칙 적용",
    "s3_forecast": "수요 시나리오 계산",
    "s3_route_beta": "노선 관광 민감도 계산",
    "s3_courses": "오는 길 찾기",
}
LLM_LABEL = {"parse": "질문 해석", "explain": "쉬운 해설 쓰기", "sql": "조회문 쓰기"}


def emit(kind: str, **data: Any) -> None:
    """알림을 보내요. 듣는 쪽의 오류가 분석을 멈추지 않게 삼켜요."""
    fn = _listener.get()
    if fn is None:
        return
    try:
        fn({"kind": kind, **data})
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def listen(fn: Listener) -> Iterator[None]:
    """with 블록 안(같은 스레드)에서 나오는 알림을 fn 으로 받아요."""
    token = _listener.set(fn)
    try:
        yield
    finally:
        _listener.reset(token)
