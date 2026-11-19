"""제출 문서(HTML)를 A4 PDF 로 만들어요. 헤드리스 Chromium(Playwright)으로 인쇄해요.

    python docs/submission/make_pdf.py              # 세 문서 모두
    python docs/submission/make_pdf.py 01 03        # 파일 이름 앞부분으로 골라서

필요한 것: pip install playwright && python -m playwright install chromium
글꼴은 화면과 같은 Pretendard 를 frontend/node_modules 에서 읽어요 (cd frontend && npm ci).
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DOCS = [
    ("01_실행환경_매뉴얼.html", "머물멍_실행환경_매뉴얼.pdf", "실행환경 · 매뉴얼"),
    ("02_데이터_활용_명세.html", "머물멍_데이터_활용_명세.pdf", "데이터 활용 명세"),
    ("03_결과_설명자료.html", "머물멍_결과_설명자료.pdf", "결과 설명자료"),
    # 기획서는 쪽마다 크기가 고정된 HTML 이라(쪽 번호도 HTML 안에 있음) 여백 없이 그대로 인쇄해요
    ("../proposal/머물멍_AI_Agent_기획서.html", "../머물멍_AI_Agent_기획서.pdf", None),
]
FOOTER = (
    '<div style="width:100%;margin:0 15mm;font-size:7.5pt;color:#8a776a;'
    "font-family:'Pretendard Variable','NanumGothic','Noto Sans KR',sans-serif;"
    'display:flex;justify-content:space-between;">'
    '<span>머물멍 · {name}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
)


def main(picks: list[str]) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for src, out, name in DOCS:
            if picks and not any(src.startswith(p) for p in picks):
                continue
            if not (HERE / src).exists():
                print("없음:", src)
                continue
            page.goto((HERE / src).resolve().as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            if name is None:
                over = page.evaluate("""() => [...document.querySelectorAll('.page')].map((p, i) => [i + 1, p.scrollHeight - p.clientHeight]).filter(x => x[1] > 1)""")
                if over:
                    print("  넘친 쪽 (쪽, px):", over)
                page.pdf(path=str((HERE / out).resolve()), prefer_css_page_size=True, print_background=True,
                         margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
                print("만듦:", out)
                continue
            page.pdf(
                path=str(HERE / out),
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=FOOTER.format(name=name),
                margin={"top": "15mm", "bottom": "17mm", "left": "15mm", "right": "15mm"},
            )
            print("만듦:", out)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
