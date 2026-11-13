"""로컬 LLM (Ollama). 외부로 아무것도 보내지 않아요. JSON 스키마 강제 출력(format)을 써요."""

from __future__ import annotations

import re
import subprocess
import time

import httpx
from pydantic import ValidationError

from .base import LLMError, LLMFormatError, LLMProvider, T

SMALL_VRAM_MODEL = "exaone3.5:2.4b"  # GPU 메모리 3GB 환경용
_THINK = re.compile(r"<think>.*?</think>", re.S)


def detect_vram_mb() -> int | None:
    """NVIDIA GPU 메모리(MiB). nvidia-smi 가 없거나 실패하면 None."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=False)
        vals = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        return max(vals) if vals else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


class OllamaProvider(LLMProvider):
    name = "ollama"
    is_cloud = False

    def __init__(self, host: str, model: str, timeout: float = 180.0, auto_select: bool = True):
        super().__init__()
        self.host = host.rstrip("/")
        self.requested_model = model
        self.model = model
        self.timeout = timeout
        self.note = ""
        self._version: tuple[int, ...] | None = None
        self._models: list[str] | None = None
        if auto_select:
            self._select_model()

    # ------------------------------------------------------------------ 모델 선택
    def _list_models(self) -> list[str]:
        if self._models is None:
            try:
                r = httpx.get(f"{self.host}/api/tags", timeout=5.0)
                r.raise_for_status()
                self._models = [m["name"] for m in r.json().get("models", [])]
                v = httpx.get(f"{self.host}/api/version", timeout=5.0).json().get("version", "")
                self._version = _version_tuple(v)
            except (httpx.HTTPError, ValueError, KeyError):
                self._models = []
        return self._models

    def _has(self, model: str) -> bool:
        names = self._list_models()
        return model in names or (":" not in model and f"{model}:latest" in names)

    def _select_model(self) -> None:
        """요청한 모델이 없거나 GPU 메모리가 작으면 쓸 수 있는 모델로 바꿔요."""
        names = self._list_models()
        if not names:
            return
        vram = detect_vram_mb()
        if vram is not None and vram < 3500 and self._has(SMALL_VRAM_MODEL):
            self.model = SMALL_VRAM_MODEL
            self.note = f"GPU 메모리 {vram}MiB라 {SMALL_VRAM_MODEL} 로 전환했어요."
            return
        if self._has(self.requested_model):
            return
        family = self.requested_model.split(":")[0]
        alt = next((n for n in names if n.split(":")[0] == family), None) or next(
            (n for n in names if n.split(":")[0] in ("qwen3", "exaone3.5")), None)
        if alt:
            self.model = alt
            self.note = f"{self.requested_model} 이 설치되어 있지 않아 {alt} 를 써요. (`ollama pull {self.requested_model}`)"

    def check(self) -> tuple[bool, str]:
        names = self._list_models()
        if not names:
            return False, f"Ollama 서버({self.host})에 연결할 수 없거나 설치된 모델이 없어요."
        if not self._has(self.model):
            return False, f"모델 {self.model} 이 없어요. `ollama pull {self.model}` 을 실행하세요."
        return True, f"로컬 · {self.model}" + (f" ({self.note})" if self.note else "")

    # ------------------------------------------------------------------ 호출
    def generate(self, system: str, user: str, out: type[T], *, purpose: str = "", model: str | None = None,
                 effort: str = "low", temperature: float = 0.0) -> T:
        use = model or self.model
        is_qwen = use.startswith("qwen3")
        self._list_models()
        new_api = bool(self._version and self._version >= (0, 9, 0))
        body = {
            "model": use,
            "messages": [
                {"role": "system", "content": system},
                # Qwen3 는 생각 모드를 끄면 훨씬 빨라요. 구버전 Ollama 는 /no_think 지시어로 꺼요.
                {"role": "user", "content": user + (" /no_think" if is_qwen and not new_api else "")},
            ],
            "stream": False,
            "format": out.model_json_schema(),
            "options": {"temperature": temperature, "seed": 7, "num_ctx": 3072, "num_predict": 400},
            "keep_alive": "30m",
        }
        if new_api:
            body["think"] = False
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{self.host}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except httpx.TimeoutException as e:
            raise LLMError(f"로컬 LLM 응답이 {self.timeout:.0f}초 안에 오지 않았어요.") from e
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama 오류 {e.response.status_code}: {e.response.text[:200]}") from e
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError(f"Ollama 서버({self.host})에 연결하지 못했어요: {e}") from e
        dt = time.perf_counter() - t0
        content = _THINK.sub("", (data.get("message") or {}).get("content", "")).strip()
        self.usage.calls += 1
        self.usage.seconds += dt
        self.usage.input_tokens += int(data.get("prompt_eval_count") or 0)
        self.usage.output_tokens += int(data.get("eval_count") or 0)
        self.usage.log.append({"purpose": purpose, "model": use, "seconds": round(dt, 2),
                               "input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")})
        try:
            return out.model_validate_json(content)
        except ValidationError as e:
            raise LLMFormatError(f"로컬 LLM 출력이 형식에 맞지 않아요 (너무 길어 잘렸을 수 있어요): {str(e)[:120]}") from e
