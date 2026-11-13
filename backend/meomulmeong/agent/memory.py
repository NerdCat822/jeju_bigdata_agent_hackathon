"""대화 맥락: 직전 질문의 장소·단계와 단계별 산출물을 기억해 후속 질문과 연계 실행에 써요."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..schemas import Answer, ParsedQuery


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    last_query: ParsedQuery | None = None
    # 장소 키 → 단계 → 산출물 (Stage 1의 유형 → Stage 2의 타깃 → Stage 3)
    stage_outputs: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)
    answers: list[Answer] = field(default_factory=list)
    cloud_consent: bool = False  # 클라우드 LLM 전송 동의 (사용자 확인 후에만 True)

    def remember(self, answer: Answer, store_stage: bool = True) -> None:
        """답을 기억해요. store_stage=False 면 단계 산출물은 덮어쓰지 않아요 (연령을 바꿔 본 Stage 1 답 등)."""
        self.last_query = answer.query
        key = answer.query.place_key
        if store_stage and key and answer.stage and answer.stage_output:
            self.stage_outputs.setdefault(key, {})[answer.stage] = answer.stage_output
        self.answers.append(answer)
        del self.answers[:-30]

    def stage_output(self, place_key: str | None, stage: int) -> dict[str, Any] | None:
        if not place_key:
            return None
        return self.stage_outputs.get(place_key, {}).get(stage)

    def latest(self, place_key: str | None, stage: int) -> Answer | None:
        """그 장소·단계의 가장 최근 답 (최종 제안서에 넣을 답)."""
        for a in reversed(self.answers):
            if a.ok and a.stage == stage and a.query.place_key == place_key:
                return a
        return None
