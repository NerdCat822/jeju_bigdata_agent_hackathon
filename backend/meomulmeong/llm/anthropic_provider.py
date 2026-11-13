"""클라우드 LLM (Anthropic Claude, 선택). 인터넷과 인증이 있을 때만, 사용자가 전송에 동의한 뒤에만 써요.

공식 Anthropic Python SDK를 쓰고, 출력은 구조화 출력(output_config.format, JSON 스키마)으로 강제해요.
안전 분류기가 요청을 거절할 때를 대비해 서버 측 대체 모델(fallbacks="default")을 켜 두었어요.
"""

from __future__ import annotations

import time

from pydantic import ValidationError

from .base import LLMError, LLMFormatError, LLMProvider, T

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 서버 측 fallbacks 를 지원하는 모델 계열
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5", "claude-mythos-5", "claude-sonnet-5-5")


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    is_cloud = True

    def __init__(self, model: str = "claude-opus-5-5", max_tokens: int = 16000):
        super().__init__()
        try:
            import anthropic
        except ImportError as e:  # 선택 의존성
            raise LLMError("anthropic 패키지가 없어요. `pip install anthropic` 후 다시 실행하세요.") from e
        self._sdk = anthropic
        self.model = model
        self.max_tokens = max_tokens
        self._client = None
        self._use_fallback = model.startswith(_FALLBACK_MODELS)

    @property
    def client(self):
        if self._client is None:
            # 인증은 SDK가 환경에서 찾아요: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, `ant auth login` 프로필
            self._client = self._sdk.Anthropic()
        return self._client

    def check(self) -> tuple[bool, str]:
        try:
            _ = self.client
        except Exception as e:  # noqa: BLE001  (인증 정보가 전혀 없을 때)
            return False, f"Anthropic 인증 정보를 찾지 못했어요: {e}"
        return True, f"클라우드 · {self.model} (전송 전 미리보기와 동의가 필요해요)"

    def _create(self, system: str, user: str, schema: dict, model: str, effort: str):
        kwargs = dict(
            model=model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if self._use_fallback:
            try:
                return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            except self._sdk.BadRequestError as e:
                if "fallback" not in str(e).lower():
                    raise
                self._use_fallback = False  # 이 계정·플랫폼은 서버 측 대체를 지원하지 않아요
        return self.client.messages.create(**kwargs)

    def generate(self, system: str, user: str, out: type[T], *, purpose: str = "", model: str | None = None,
                 effort: str = "low") -> T:
        # 샘플링 값(temperature)은 보내지 않아요: 최신 Claude 모델은 effort 로 깊이를 조절해요.
        sdk = self._sdk
        use = model or self.model
        t0 = time.perf_counter()
        try:
            resp = self._create(system, user, out.model_json_schema(), use, effort)
        except sdk.AuthenticationError as e:
            raise LLMError("Anthropic 인증에 실패했어요. API 키 또는 `ant auth login` 을 확인하세요.") from e
        except sdk.PermissionDeniedError as e:
            raise LLMError("이 API 키로는 해당 모델을 쓸 권한이 없어요.") from e
        except sdk.NotFoundError as e:
            raise LLMError(f"모델 '{use}' 을(를) 찾을 수 없어요. MEOMUL_ANTHROPIC_MODEL 을 확인하세요.") from e
        except sdk.RateLimitError as e:
            raise LLMError("Anthropic 요청 한도를 넘었어요. 잠시 뒤 다시 시도하세요.") from e
        except sdk.BadRequestError as e:
            raise LLMError(f"Anthropic 요청 형식 오류: {e.message}") from e
        except sdk.APIStatusError as e:
            raise LLMError(f"Anthropic 서버 오류 ({e.status_code}).") from e
        except sdk.APIConnectionError as e:
            raise LLMError("Anthropic 서버에 연결하지 못했어요. 인터넷 연결을 확인하세요.") from e
        dt = time.perf_counter() - t0
        self.usage.calls += 1
        self.usage.seconds += dt
        self.usage.input_tokens += int(getattr(resp.usage, "input_tokens", 0) or 0)
        self.usage.output_tokens += int(getattr(resp.usage, "output_tokens", 0) or 0)
        self.usage.log.append({"purpose": purpose, "model": resp.model, "seconds": round(dt, 2),
                               "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                               "request_id": resp._request_id})
        if resp.stop_reason == "refusal":
            raise LLMError("모델이 이 요청을 거절했어요. 템플릿 해설로 대신해요.")
        if resp.stop_reason == "max_tokens":
            raise LLMFormatError("응답이 길이 제한에 걸려 끝까지 오지 않았어요.")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            raise LLMError("모델 응답에 본문이 없어요.")
        try:
            return out.model_validate_json(text)
        except ValidationError as e:
            raise LLMFormatError(f"모델 출력이 형식에 맞지 않아요: {str(e)[:200]}") from e
