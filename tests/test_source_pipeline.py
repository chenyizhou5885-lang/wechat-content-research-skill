import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_sources = load_module("build_sources", ROOT / "scripts" / "build_sources.py")
validate_research = load_module("validate_research", ROOT / "scripts" / "validate_research.py")


def source(index, grade_type, publisher, platform="web"):
    item = {
        "id": f"src-{index}",
        "title": f"Source {index}",
        "publisher": publisher,
        "source_type": grade_type,
        "originality": "original",
        "published_at": "2026-08-01",
        "url": f"https://example{index}.com/article",
        "final_url": f"https://example{index}.com/article",
        "visited": True,
        "access": "open",
        "author": publisher,
        "platform": platform,
        "verification": "verified",
        "content_evidence": [f"Concrete evidence {index}"],
    }
    if platform == "wechat":
        item.update({
            "source_type": "competitor_official",
            "final_url": f"https://mp.weixin.qq.com/s/test{index}",
            "verified_title": f"Source {index}",
            "verified_publisher": publisher,
            "verified_published_at": "2026-08-01",
            "body_length": 1200,
        })
    return item


def valid_raw():
    results = [
        source(1, "company_official", "Company"),
        source(2, "media_original", "Independent Media"),
        source(3, "research_report_primary", "Research Institute"),
        source(4, "vertical_media_original", "Vertical Media"),
        source(5, "expert_original", "Expert"),
        source(6, "competitor_official", "Peer A", "wechat"),
        source(7, "competitor_official", "Peer B", "wechat"),
        source(8, "competitor_official", "Peer C", "wechat"),
    ]
    return {
        "research_brief": {"topic": "Agent deployment"},
        "requirements": {
            "wechat_research_required": True,
            "min_verified_wechat_articles": 3,
            "min_verified_wechat_publishers": 2,
            "min_candidates": 12,
            "min_visited_results": 8,
            "min_accepted_sources": 5,
            "min_discovery_channels": 2,
        },
        "queries": [
            {"query": "official research", "channel": "web_search"},
            {"query": "peer WeChat", "channel": "sogou_weixin"},
        ],
        "tool_attempts": [],
        "candidate_pool": [{"name": f"candidate-{i}"} for i in range(12)],
        "enterprise_materials": [{"id": "enterprise-1", "authorized_for_publication": True}],
        "results": results,
        "claim_ledger": [{
            "id": "claim-1", "claim": "Company action", "claim_type": "company_action",
            "core": True, "source_ids": ["src-1", "src-2"],
        }],
        "selected_topics": [{
            "title": "Strong topic", "recommendation": "strong",
            "source_ids": ["src-1", "src-2"], "enterprise_material_ids": ["enterprise-1"],
        }],
    }


class SourcePipelineTests(unittest.TestCase):
    def test_valid_research_passes_writing_gate(self):
        built = build_sources.build(valid_raw())
        self.assertTrue(built["gate"]["writing_ready"], built)
        self.assertTrue(built["coverage_audit"]["passed"])
        self.assertTrue(built["wechat_audit"]["passed"])

    def test_portal_and_aggregation_pages_are_rejected(self):
        raw = valid_raw()
        bad = source(9, "media_original", "Unknown Account")
        bad["final_url"] = "https://www.163.com/dy/article/ABC.html"
        raw["results"].append(bad)
        built = build_sources.build(raw)
        rejected = {item["id"]: item for item in built["rejected_sources"]}
        self.assertIn("src-9", rejected)
        self.assertEqual(rejected["src-9"]["quality_grade"], "C")

    def test_unverified_wechat_does_not_complete_gate(self):
        raw = valid_raw()
        for item in raw["results"]:
            if item["platform"] == "wechat":
                item["verification"] = "failed"
        built = build_sources.build(raw)
        self.assertFalse(built["wechat_audit"]["passed"])
        self.assertFalse(built["gate"]["writing_ready"])

    def test_unproven_unavailable_tool_claim_fails(self):
        raw = valid_raw()
        raw["tool_attempts"] = [{
            "tool": "kimi-webbridge", "attempted": False, "status": "unavailable",
            "command": "", "error": "",
        }]
        built = build_sources.build(raw)
        self.assertFalse(built["gate"]["tool_log_ready"])
        self.assertFalse(built["gate"]["research_ready"])

    def test_recorded_failure_is_honest_but_wechat_gate_still_blocks_writing(self):
        raw = valid_raw()
        raw["tool_attempts"] = [{
            "tool": "kimi-webbridge", "attempted": True, "status": "unavailable",
            "command": "kimi-webbridge start", "error": "connection refused",
        }]
        for item in raw["results"]:
            if item["platform"] == "wechat":
                item["verification"] = "failed"
        built = build_sources.build(raw)
        self.assertTrue(built["gate"]["tool_log_ready"])
        self.assertFalse(built["gate"]["writing_ready"])

    def test_validator_rejects_article_and_strong_claim_when_gate_failed(self):
        raw = valid_raw()
        raw["results"] = raw["results"][:5]
        built = build_sources.build(raw)
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "research-report.md"
            article = Path(directory) / "article-draft.md"
            report.write_text("# 报告\n\n选题 A（强推荐）：满足强推荐门槛。", encoding="utf-8")
            article.write_text("draft", encoding="utf-8")
            errors, _ = validate_research.validate(built, "writing", report, article)
        self.assertTrue(any("writing gate failed" in item for item in errors))
        self.assertTrue(any("article draft exists" in item for item in errors))
        self.assertTrue(any("claims strong recommendation" in item for item in errors))

    def test_writing_cannot_disable_wechat_gate(self):
        raw = valid_raw()
        raw["requirements"]["wechat_research_required"] = False
        built = build_sources.build(raw)
        errors, _ = validate_research.validate(built, "writing")
        self.assertTrue(any("cannot disable" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
