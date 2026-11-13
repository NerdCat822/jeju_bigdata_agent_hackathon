"""골든셋: 파일 구성과 채점기가 맞는지, 범주별 첫 문항이 통과하는지 확인해요 (전체 평가는 `python -m eval`)."""

import yaml

from eval.__main__ import check_item
from eval.expected import Expected
from eval.make_golden import GOLDEN, build


def test_golden_file_matches_generator(settings, manifest):
    saved = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    assert saved["meta"]["n_items"] == 60
    assert saved["meta"]["counts"] == {"stage1": 20, "stage2": 15, "stage3": 15, "chain": 5, "causal": 5}
    assert saved["meta"]["seed"] == manifest["seed"]
    fresh = build(settings)  # 같은 시드면 누구나 같은 기대값을 얻어요
    assert [i["expect"] for i in fresh["items"]] == [i["expect"] for i in saved["items"]]


def test_expected_values_agree_with_sql(agent, settings, refs):
    """pandas 로 다시 계산한 값과 에이전트의 SQL 지표가 같아야 해요."""
    from meomulmeong.tools import stage1

    exp = Expected(settings.raw_dir("synthetic"), settings.ref_dir)
    rows, _, _ = stage1.metrics_all(agent.ctx.new_request(), [20, 30], stage1._req(None, None))
    for r in rows[::6]:
        e = exp.s1([r["emd_nm"]])
        assert abs(e["youth_resd_chg"] - r["youth_resd_chg"]) < 1e-9, r["emd_nm"]
        assert abs(e["visit_chg"] - r["visit_chg"]) < 1e-9 and e["type"] == r["type"] and e["small"] == r["small"]


def test_first_item_of_each_category_passes(agent):
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    seen = set()
    for item in golden["items"]:
        if item["category"] in seen:
            continue
        seen.add(item["category"])
        result = agent.ask(item["question"], agent.session())
        assert check_item(result, item["expect"], agent.refs) == [], item["id"]


def test_checker_detects_wrong_answers(agent):
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    item = next(i for i in golden["items"] if i["id"] == "S1-01")
    result = agent.ask("구좌읍 청년 인구 진단", agent.session())  # 다른 읍면동의 답
    problems = check_item(result, item["expect"], agent.refs)
    assert any("장소" in p for p in problems) and any("youth_resd_chg" in p for p in problems)
