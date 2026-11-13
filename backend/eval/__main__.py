"""골든셋 평가 실행기.

    python -m eval                      # 템플릿 모드 (LLM 없이, 완전 재현)
    python -m eval --llm ollama         # 로컬 LLM 모드
    python -m eval --category stage1    # 일부만
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from meomulmeong.data import synthetic
from meomulmeong.data.catalog import Catalog
from meomulmeong.data.refs import Refs
from meomulmeong.data.warehouse import build_warehouse
from meomulmeong.schemas import Answer, ChainResult
from meomulmeong.service import AgentService
from meomulmeong.settings import get_settings, load_config

from .make_golden import GOLDEN

LABEL = {"stage1": "Stage 1", "stage2": "Stage 2", "stage3": "Stage 3", "chain": "연계", "causal": "인과 함정"}
HEDGES = ("단정", "알 수 없", "확인해야", "확인이 필요")


def ensure_data(golden: dict[str, Any]) -> None:
    """골든셋과 같은 시드의 합성 데이터와 데이터 창고가 있는지 확인하고, 없으면 만들어요."""
    settings = get_settings()
    raw = settings.raw_dir("synthetic")
    manifest = raw / "MANIFEST.json"
    seed = json.loads(manifest.read_text(encoding="utf-8"))["seed"] if manifest.exists() else None
    if seed != golden["meta"]["seed"] or not settings.warehouse_path("synthetic").exists():
        synthetic.generate(raw, Refs(settings.ref_dir), seed=golden["meta"]["seed"])
        build_warehouse(settings, load_config(settings.config_dir), Catalog.load(settings.catalog_dir), "synthetic")


def _near(got: Any, want: dict[str, float]) -> bool:
    return isinstance(got, (int, float)) and abs(float(got) - want["value"]) <= want["tol"]


def check_answer(a: Answer, exp: dict[str, Any], refs: Refs) -> list[str]:
    """기대와 다른 점 목록 (비어 있으면 정답)."""
    bad: list[str] = []
    if not a.ok:
        return [f"실행 실패: {a.message}"]
    if not a.verification.passed:
        bad.append("검증 실패: " + "; ".join(c.name for c in a.verification.checks if not c.passed))
    q, out = a.query, a.stage_output
    if "stage" in exp and a.stage != exp["stage"]:
        bad.append(f"단계 {a.stage} ≠ {exp['stage']}")
    if "intent" in exp and a.intent != exp["intent"]:
        bad.append(f"의도 {a.intent} ≠ {exp['intent']}")
    if "place" in exp and q.place_name != exp["place"]:
        bad.append(f"장소 {q.place_name} ≠ {exp['place']}")
    if "ages" in exp and sorted(q.ages) != exp["ages"]:
        bad.append(f"연령 {q.ages} ≠ {exp['ages']}")
    if "period" in exp and exp["period"] not in (a.data_period or ""):
        bad.append(f"기간 {a.data_period} ≠ {exp['period']}")
    if "type" in exp and out.get("type") != exp["type"]:
        bad.append(f"유형 {out.get('type')} ≠ {exp['type']}")
    if "theme" in exp and q.theme != exp["theme"]:
        bad.append(f"테마 {q.theme} ≠ {exp['theme']}")
    if "target" in exp and a.stage == 2 and out.get("target") != exp["target"]:
        bad.append(f"타깃 {out.get('target')} ≠ {exp['target']}")
    if "target" in exp and a.stage == 3 and (a.fact("target_month") is None or a.fact("target_month").text != exp["target"]):
        bad.append(f"대상 월 {a.fact('target_month').text if a.fact('target_month') else None} ≠ {exp['target']}")
    if "top_theme" in exp and out.get("top_theme") != exp["top_theme"]:
        bad.append(f"증가 폭 1위 테마 {out.get('top_theme')} ≠ {exp['top_theme']}")
    if "rule_ids" in exp and not set(exp["rule_ids"]) <= set(out.get("fired", [])):
        bad.append(f"규칙 {out.get('fired')} ⊉ {exp['rule_ids']}")
    if "top" in exp and (out.get("top") or [{}])[0].get("emd_nm") != exp["top"]:
        bad.append(f"1위 {(out.get('top') or [{}])[0].get('emd_nm')} ≠ {exp['top']}")
    if "peers_area" in exp:
        peers = out.get("peers", [])
        if len(peers) != 3 or any(refs.find_emd(p).area_type != exp["peers_area"] for p in peers):
            bad.append(f"유사 읍면 {peers}")
    for key, want in (exp.get("facts") or {}).items():
        f = a.fact(key)
        if f is None or not _near(f.value, want):
            bad.append(f"{key} = {f.value if f else None} (기대 {want['value']} ± {want['tol']})")
    if "supply_change" in exp and (a.fact("supply_change") is None or abs(a.fact("supply_change").value - exp["supply_change"]) > 1e-9):
        bad.append(f"공급 변화율 {a.fact('supply_change').value if a.fact('supply_change') else None} ≠ {exp['supply_change']}")
    if "elasticity" in exp and (a.fact("elasticity") is None or abs(a.fact("elasticity").value - exp["elasticity"]) > 1e-9):
        bad.append("탄력성 불일치")
    if "hub" in exp and q.hub_id != exp["hub"]:
        bad.append(f"거점 {q.hub_id} ≠ {exp['hub']}")
    courses = out.get("courses", [])
    if "min_courses" in exp and len(courses) < exp["min_courses"]:
        bad.append(f"코스 {len(courses)}개 < {exp['min_courses']}")
    if exp.get("first_direct") and not (courses and "환승" not in (a.fact("course1").label if a.fact("course1") else "환승")):
        bad.append("첫 코스가 직행이 아니에요")
    if exp.get("access_gap") and (courses or not any(b.label == "접근성 공백" for b in a.badges)):
        bad.append("접근성 공백 표시 없음")
    if exp.get("routes_exist"):
        import re

        nums = set(out.get("sensitive_routes", [])) | {n for c in courses for n in re.findall(r"(\d{2,4})번", c)}
        missing = [n for n in nums if n not in refs.routes]
        if missing:
            bad.append(f"참조표에 없는 노선 {missing}")
    if "sensitive_has" in exp and not set(exp["sensitive_has"]) <= set(out.get("sensitive_routes", [])):
        bad.append(f"관광 민감 노선 {out.get('sensitive_routes')} ⊉ {exp['sensitive_has']}")
    if "sensitive_lacks" in exp and set(exp["sensitive_lacks"]) & set(out.get("sensitive_routes", [])):
        bad.append(f"관광 민감 노선에 {exp['sensitive_lacks']} 포함")
    if exp.get("causal_safe"):
        text = f"{a.headline} {a.explanation}"
        causal = next((c for c in a.verification.checks if c.name == "causal"), None)
        if causal is None or not causal.passed:
            bad.append("인과 단정 표현")
        if not any(h in text for h in HEDGES):
            bad.append("원인을 단정할 수 없다는 안내가 없어요")
    return bad


def check_item(result: Answer | ChainResult, exp: dict[str, Any], refs: Refs) -> list[str]:
    if exp.get("chain"):
        if not isinstance(result, ChainResult):
            return ["연계 실행이 아니에요"]
        bad = []
        if [a.stage for a in result.answers] != [1, 2, 3]:
            bad.append(f"단계 {[a.stage for a in result.answers]}")
        if {a.query.place_name for a in result.answers} != {exp["place"]}:
            bad.append(f"장소 {[a.query.place_name for a in result.answers]} ≠ {exp['place']}")
        if any(not a.ok or not a.verification.passed for a in result.answers):
            bad.append("실행 또는 검증 실패")
        types = {a.stage_output.get("type") for a in result.answers[:2]}
        if types != {exp["type"]}:
            bad.append(f"유형 {types} ≠ {exp['type']}")
        if result.answers and len(result.answers) == 3 and result.answers[2].stage_output.get("target") != result.answers[1].stage_output.get("target"):
            bad.append("Stage 2의 타깃이 Stage 3로 넘어가지 않았어요")
        return bad
    if isinstance(result, ChainResult):
        return ["연계 실행으로 처리됐어요"]
    return check_answer(result, exp, refs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m eval", description="머물멍 골든셋 평가")
    p.add_argument("--llm", choices=["template", "ollama", "anthropic"], default="template")
    p.add_argument("--category", choices=list(LABEL), action="append")
    p.add_argument("--limit", type=int, default=0, help="범주마다 앞에서 N문항만")
    p.add_argument("--yes-cloud", action="store_true", help="클라우드 LLM 전송에 동의해요")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not GOLDEN.exists():
        print("eval/golden.yaml 이 없어요. 먼저 `python -m eval.make_golden` 을 실행하세요.")
        return 2
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    ensure_data(golden)
    svc = AgentService.create("synthetic", args.llm)
    agent = svc.agent
    items = [i for i in golden["items"] if not args.category or i["category"] in args.category]
    if args.limit:
        seen: dict[str, int] = {}
        items = [i for i in items if (seen.setdefault(i["category"], 0) < args.limit) and not seen.update({i["category"]: seen[i["category"]] + 1})]
    print(f"골든셋 {len(items)}문항 · 데이터 {svc.status()['data_badge']} · LLM {svc.status()['llm_label']}" + (f" ({svc.llm_note})" if svc.llm_note else ""))
    rows = []
    for it in items:
        session = agent.session()
        session.cloud_consent = args.yes_cloud
        t0 = time.perf_counter()
        try:
            result = agent.ask(it["question"], session)
            bad = check_item(result, it["expect"], agent.refs)
        except Exception as e:  # noqa: BLE001
            result, bad = None, [f"예외: {e}"]
        dt = time.perf_counter() - t0
        by = (result.answers[0].explained_by if isinstance(result, ChainResult) and result.answers
              else getattr(result, "explained_by", "-"))
        rows.append({"id": it["id"], "category": it["category"], "question": it["question"], "ok": not bad, "issues": bad,
                     "seconds": round(dt, 3), "explained_by": by})
        print(f"  {'○' if not bad else '✗'} {it['id']} {dt:6.2f}s  {it['question']}" + (f"  → {'; '.join(bad)}" if bad else ""))

    targets = golden["meta"]["targets"]
    summary = []
    for cat in LABEL:
        rs = [r for r in rows if r["category"] == cat]
        if not rs:
            continue
        secs = sorted(r["seconds"] for r in rs)
        acc = sum(r["ok"] for r in rs) / len(rs)
        summary.append({"category": cat, "n": len(rs), "correct": sum(r["ok"] for r in rs), "accuracy": round(acc, 4),
                        "target": targets[cat], "met": acc >= targets[cat], "mean_s": round(statistics.mean(secs), 2),
                        "max_s": round(secs[-1], 2)})
    total = {"n": len(rows), "correct": sum(r["ok"] for r in rows),
             "accuracy": round(sum(r["ok"] for r in rows) / max(len(rows), 1), 4),
             "mean_s": round(statistics.mean(r["seconds"] for r in rows), 2) if rows else 0}

    lines = [f"# 머물멍 골든셋 평가 ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"- 데이터: {svc.status()['data_badge']} (시드 {golden['meta']['seed']}, {golden['meta']['data_first_day']}~{golden['meta']['data_last_day']})",
             f"- LLM: {svc.status()['llm_label']}", f"- 문항: {total['n']}개, 정답 {total['correct']}개 ({total['accuracy']:.1%}), 평균 응답 {total['mean_s']}초", "",
             "| 구분 | 문항 | 정답 | 정확도 | 목표 | 달성 | 평균(초) | 최대(초) |", "|---|---:|---:|---:|---:|:---:|---:|---:|"]
    for s in summary:
        lines.append(f"| {LABEL[s['category']]} | {s['n']} | {s['correct']} | {s['accuracy']:.1%} | {s['target']:.0%} | "
                     f"{'○' if s['met'] else '✗'} | {s['mean_s']} | {s['max_s']} |")
    wrong = [r for r in rows if not r["ok"]]
    if wrong:
        lines += ["", "## 틀린 문항", ""] + [f"- `{r['id']}` {r['question']} — {'; '.join(r['issues'])}" for r in wrong]
    report = "\n".join(lines) + "\n"
    print("\n" + report)
    out_dir = args.out or (get_settings().outputs_dir / "eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"eval_{args.llm}_{datetime.now():%Y%m%d_%H%M%S}"
    (out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(json.dumps({"summary": summary, "total": total, "items": rows}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"보고서: {out_dir / (stem + '.md')}")
    return 0 if all(s["met"] for s in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
