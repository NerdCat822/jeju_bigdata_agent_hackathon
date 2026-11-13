"""OpenAPI 명세를 파일로 내보내요. 화면(React) 쪽 타입을 만들 때 써요.

    python -m meomulmeong.api.export_openapi ../frontend/src/api/openapi.json
    (frontend 폴더에서) npm run gen:api

서버를 띄우지 않고, 데이터 창고가 없어도 돼요.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .app import create_app


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    spec = create_app().openapi()
    text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args:
        Path(args[0]).write_text(text, encoding="utf-8")
        print(f"OpenAPI 명세를 썼어요: {args[0]} (경로 {len(spec['paths'])}개, 모델 {len(spec['components']['schemas'])}개)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
