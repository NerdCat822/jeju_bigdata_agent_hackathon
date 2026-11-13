"""화면 테스트용 예시 응답을 실제 API에서 다시 뽑아요 (샘플 데이터, 템플릿 모드).

    cd backend && .venv/bin/python ../frontend/src/test/fixtures/make.py

백엔드의 답 모양을 바꾼 뒤에 실행해요. 긴 근거표는 12행까지만 남겨요.
"""

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MEOMUL_OUTPUTS", tempfile.mkdtemp(prefix="meomul-fixtures-"))
# API 키가 있는 PC에서 뽑아도 같은 예시가 나오게, 키가 없는 것처럼 뽑아요 (빈 값은 .env 의 키를 덮어써요)
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["MEOMUL_LLM_MODE"] = "template"

from fastapi.testclient import TestClient  # noqa: E402

from meomulmeong.api import create_app  # noqa: E402

OUT = Path(__file__).resolve().parent
client = TestClient(create_app())


def trim(answer: dict) -> dict:
    for e in answer["evidence"]:
        e["rows"] = e["rows"][:12]
        if e.get("sql"):
            e["sql"] = e["sql"][:400]
    answer["llm_payload"] = None
    return answer


def save(name: str, data: object) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"{name}  {len(text) // 1024} KB")


save("bootstrap.json", client.get("/api/bootstrap").json())
chain = client.post("/api/chain", json={"place": "성산읍", "with_report": True}).json()
for a in chain["chain"]["answers"]:
    trim(a)
chain["chain"]["report_path"] = None
chain["report_url"] = "/api/reports/sample.html"
chain["session_id"] = "fixture-session"
save("chain.json", chain)
card = client.post("/api/understand", json={"question": "성산읍 청년 인구 왜 줄었어?"}).json()
card["session_id"] = "fixture-session"
save("card.json", card)
save("failed.json", trim(client.post("/api/ask", json={"question": "오늘 날씨 어때?"}).json()["answer"]))
