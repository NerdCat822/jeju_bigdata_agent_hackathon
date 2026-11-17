"""명령줄 실행: 데이터 창고 만들기, 질문하기, 연계 실행, 상태 보기.

    python -m meomulmeong build-data --mode synthetic
    python -m meomulmeong ask "성산읍 청년 인구 왜 줄었어?"
    python -m meomulmeong chain 성산읍 --report
    python -m meomulmeong status
    python -m meomulmeong serve          # 웹 API 서버 (React 화면이 붙는 곳)
"""

from __future__ import annotations

import argparse
import json
import sys

from .schemas import Answer, ChainResult
from .settings import get_settings, load_config


def _print_answer(a: Answer, verbose: bool = False) -> None:
    stage = f"Stage {a.stage}" if a.stage else "자유 질문"
    print(f"\n[{stage} · {a.intent}] {' · '.join(b.label for b in a.badges)}")
    print(f"■ {a.headline}")
    if a.explanation:
        print(f"  {a.explanation}")
    for n in a.notices:
        print(f"  ※ {n}")
    for s in a.suggestions:
        print(f"  제안 {s.rule_id}: {s.text}\n      근거: {' · '.join(s.evidence_text)}")
    if a.limits:
        print("  한계: " + " / ".join(a.limits[:3]) + (" …" if len(a.limits) > 3 else ""))
    v = a.verification
    failed = [c for c in v.checks if not c.passed]
    print(f"  검증: {'통과' if v.passed else '실패'} ({len(v.checks)}개 항목"
          + (f", 재시도 {v.retries}회" if v.retries else "") + (", 템플릿 대체" if v.fallback else "") + ")"
          + (" → " + "; ".join(f"{c.name}: {c.detail}" for c in failed) if failed else ""))
    print(f"  해설: {a.explained_by} · LLM {a.llm_mode}{'/' + a.llm_model if a.llm_model else ''} · 기간 {a.data_period or '-'} · {a.elapsed:.2f}초")
    if a.next_questions:
        print("  다음 질문: " + " | ".join(n.label for n in a.next_questions))
    if verbose:
        for e in a.evidence:
            print(f"\n  [근거표] {e.title} ({len(e.rows)}행, {e.period or '-'})")
            for r in e.rows[:8]:
                print("    ", r)
            if e.sql:
                print("    SQL:", " ".join(e.sql.split())[:400])
        print("\n  실행 기록: " + ", ".join(f"{s.tool}({s.seconds}s{'' if s.ok else ',실패'})" for s in a.steps))


def _build_data(settings, mode: str, generate: bool = True) -> str:
    """원본을 읽어 데이터 창고를 만들고 요약 문장을 돌려줘요. 샘플 모드는 합성 데이터부터 만들어요."""
    from .data import synthetic
    from .data.catalog import Catalog
    from .data.refs import Refs
    from .data.warehouse import build_warehouse

    lines = []
    if mode == "synthetic" and generate:
        m = synthetic.generate(settings.raw_dir("synthetic"), Refs(settings.ref_dir))
        lines.append(f"합성 데이터 생성: {m['first_day']}~{m['last_day']}, 시드 {m['seed']}, {sum(m['rows'].values()):,}행")
    report = build_warehouse(settings, load_config(settings.config_dir), Catalog.load(settings.catalog_dir), mode)  # type: ignore[arg-type]
    lines.append(report.summary())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="meomulmeong", description="머물멍 백엔드")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-data", help="원본을 읽어 데이터 창고(PostgreSQL)를 만들어요")
    b.add_argument("--mode", choices=["synthetic", "hub", "center"], default=None)
    b.add_argument("--no-generate", action="store_true", help="샘플 모드에서 합성 데이터를 다시 만들지 않아요")
    for name, help_ in (("ask", "질문 한 줄을 실행해요"), ("chain", "읍면동 하나를 Stage 1→2→3으로 실행해요")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("text")
        s.add_argument("--data", choices=["synthetic", "hub", "center"], default=None)
        s.add_argument("--llm", choices=["template", "anthropic"], default=None)
        s.add_argument("--yes-cloud", action="store_true", help="클라우드 LLM 전송에 동의해요")
        s.add_argument("-v", "--verbose", action="store_true")
        s.add_argument("--json", action="store_true", help="결과를 JSON으로 출력해요")
        if name == "chain":
            s.add_argument("--report", action="store_true", help="최종 제안서(HTML)도 만들어요")
    st = sub.add_parser("status", help="데이터·LLM 상태를 보여 줘요")
    st.add_argument("--data", choices=["synthetic", "hub", "center"], default=None)
    st.add_argument("--llm", choices=["template", "anthropic"], default=None)
    sv = sub.add_parser("serve", help="웹 API 서버를 띄워요 (React 화면이 붙는 곳)")
    sv.add_argument("--host", default=None, help="기본 127.0.0.1 (이 PC 안에서만 열려요)")
    sv.add_argument("--port", type=int, default=None, help="기본 8501")
    sv.add_argument("--data", choices=["synthetic", "hub", "center"], default=None)
    sv.add_argument("--llm", choices=["template", "anthropic"], default=None)
    sv.add_argument("--open", action="store_true", help="서버가 뜨면 브라우저를 열어요")
    sv.add_argument("--prepare", action="store_true", help="샘플 데이터 창고가 없으면 먼저 만들어요 (컨테이너가 처음 뜰 때)")
    ex = sub.add_parser("export-csv", help="데이터 창고의 테이블을 CSV 로 내보내요 (이 PC 에서만 쓰고 저장소에 올리지 않아요)")
    ex.add_argument("--mode", choices=["synthetic", "hub", "center"], default=None)
    ex.add_argument("--out", default=None, help="내보낼 폴더 (기본 data/export/<모드>)")
    f = sub.add_parser("fetch-hub", help="제주데이터허브 Open API에서 데이터를 내려받아요 (프로젝트 키 필요)")
    f.add_argument("--table", action="append", help="받을 테이블 (여러 번 지정 가능, 생략하면 전부)")
    f.add_argument("--start", help="시작일 YYYYMMDD (일 단위 데이터)")
    f.add_argument("--end", help="종료일 YYYYMMDD")
    f.add_argument("--max-calls", type=int, default=900, help="API별 호출 상한 (기본 900, 허브 쿼터 1,000)")
    f.add_argument("--days", help="일 단위 자료를 달마다 이 날짜만 받아요. 예: 1,9,17,25 또는 1-7 (쿼터 절약)")
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글이 깨지지 않게

    settings = get_settings()
    if args.cmd == "build-data":
        from .data.warehouse import WarehouseMissing

        try:
            print(_build_data(settings, args.mode or settings.data_mode, generate=not args.no_generate))
        except WarehouseMissing as e:
            print(e)
            return 1
        return 0
    if args.cmd == "export-csv":
        from pathlib import Path

        from .data.warehouse import WarehouseMissing, export_csv

        mode = args.mode or settings.data_mode
        out = Path(args.out) if args.out else settings.export_dir(mode)
        try:
            done = export_csv(settings, mode, out)
        except WarehouseMissing as e:
            print(e)
            return 1
        for table, n, size in done:
            print(f"  - {table:<28} {n:>9,}행  {size / 1e6:7.2f}MB")
        print(f"CSV {len(done)}개를 {out} 에 내보냈어요. 합계 {sum(s for _, _, s in done) / 1e6:.1f}MB")
        if mode != "synthetic":
            print("주의: 허브·센터 자료는 재배포할 수 없어요. 이 폴더는 저장소에 올리지 않아요.")
        return 0
    if args.cmd == "fetch-hub":
        from .data.hub_client import fetch_all

        return fetch_all(settings, tables=args.table, start=args.start, end=args.end, max_calls=args.max_calls,
                         days=args.days)

    if args.cmd == "serve":
        import threading
        import webbrowser

        import uvicorn
        from fastapi import HTTPException

        from .api import create_app

        host, port = args.host or settings.api_host, args.port or settings.api_port
        if args.prepare:
            from .data.warehouse import WarehouseMissing, warehouse_exists

            if not warehouse_exists(settings, ["synthetic"])["synthetic"]:
                print("샘플 데이터 창고가 없어 먼저 만들어요. 1~2분 걸려요.")
                try:
                    print(_build_data(settings, "synthetic"))
                except WarehouseMissing as e:  # 창고 없이도 서버는 띄워요. 화면이 안내를 보여 줘요
                    print(f"주의: {e}")
        app = create_app(settings=settings, data_mode=args.data, llm_mode=args.llm)
        try:
            svc = app.state.meomul.service()
            print(f"데이터: {svc.agent.ctx.wh.data_badge} · LLM: {svc.status()['llm_label']}" + (f" ({svc.llm_note})" if svc.llm_note else ""))
        except HTTPException as e:  # 데이터 창고가 없어도 서버는 띄워요. 화면은 /api/health 로 안내를 받아요
            print(f"주의: {e.detail['message']}")  # type: ignore[index]
        print(f"머물멍 API: http://{host}:{port}" + (f"  (API 문서: http://{host}:{port}/docs)" if settings.api_docs else ""))
        if host not in ("127.0.0.1", "localhost"):
            print(f"주의: {host} 에서 접속을 받아요. 로그인 기능이 없으니 접속 범위를 좁혀 쓰세요 "
                  "(컨테이너라면 ports 를 127.0.0.1 로 열고, 아니면 믿을 수 있는 망에서만 쓰세요).")
        if args.open:
            threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    from .service import AgentService

    svc = AgentService.create(getattr(args, "data", None), getattr(args, "llm", None))
    if args.cmd == "status":
        print(json.dumps(svc.status(), ensure_ascii=False, indent=2, default=str))
        return 0
    session = svc.agent.session()
    session.cloud_consent = bool(getattr(args, "yes_cloud", False))
    if svc.llm_note:
        print(f"LLM: {svc.llm_note}")
    if args.cmd == "ask":
        result = svc.agent.ask(args.text, session)
    else:
        card = svc.agent.understand(f"{args.text} 처음부터 끝까지", session)
        result = svc.agent.run_chain(card.query, session, with_report=args.report)
    if args.json:
        print(result.model_dump_json(indent=1))
        return 0
    if isinstance(result, ChainResult):
        print(f"=== {result.place_name} · 처음부터 끝까지 ({result.elapsed:.2f}초) ===")
        for a in result.answers:
            _print_answer(a, args.verbose)
        if result.report_path:
            print(f"\n제안서: {result.report_path}")
    else:
        _print_answer(result, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
