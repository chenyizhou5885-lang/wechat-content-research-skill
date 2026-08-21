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


prefilter_candidates = load_module(
    "prefilter_candidates", ROOT / "scripts" / "prefilter_candidates.py")
detect_capability = load_module(
    "detect_capability", ROOT / "scripts" / "detect_capability.py")


def registry():
    return {
        "fixed": [
            {"name": "Peer A", "domains": ["peer-a.com"]},
            {"name": "Independent Media", "domains": ["example2.com"]},
            {"name": "Research Institute", "domains": ["example3.com"]},
        ],
        "dynamic": [],
    }


class RoleAndDepthTests(unittest.TestCase):
    def test_landscape_wechat_source_needs_no_body_read(self):
        raw = valid_raw()
        item = source(9, "competitor_official", "Peer D", "wechat")
        item["role"] = "landscape_only"
        item["verification"] = "resolved"
        item["body_length"] = 0
        item.pop("verified_published_at")
        raw["results"].append(item)
        built = build_sources.build(raw)
        accepted = {entry["id"] for entry in built["accepted_sources"]}
        self.assertIn("src-9", accepted)

    def test_fact_source_wechat_still_needs_body_read(self):
        raw = valid_raw()
        item = source(9, "competitor_official", "Peer D", "wechat")
        item["body_length"] = 0
        raw["results"].append(item)
        built = build_sources.build(raw)
        rejected = {entry["id"]: entry for entry in built["rejected_sources"]}
        self.assertIn("src-9", rejected)
        self.assertIn("WeChat body was not readable",
                      rejected["src-9"]["rejection_reasons"])

    def test_landscape_source_cannot_support_a_claim(self):
        raw = valid_raw()
        item = source(9, "competitor_official", "Peer D", "wechat")
        item["role"] = "landscape_only"
        item["verification"] = "resolved"
        raw["results"].append(item)
        raw["claim_ledger"][0]["source_ids"] = ["src-1", "src-9"]
        built = build_sources.build(raw)
        claim = built["claim_audit"][0]
        self.assertFalse(claim["passed"])
        self.assertEqual(claim["rejected_landscape_source_ids"], ["src-9"])
        self.assertFalse(built["gate"]["writing_ready"])

    def test_scan_depth_does_not_require_s_and_a_grades(self):
        raw = valid_raw()
        raw["depth"] = "scan"
        raw["requirements"] = {"wechat_research_required": True}
        raw["results"] = [source(1, "aggregator", "Aggregator")]
        raw["claim_ledger"] = []
        raw["selected_topics"] = []
        built = build_sources.build(raw)
        self.assertEqual(built["depth"], "scan")
        self.assertTrue(built["gate"]["scan_ready"], built["missing"])
        self.assertFalse(built["gate"]["research_ready"])
        self.assertFalse(built["wechat_audit"]["required"])

    def test_writing_depth_keeps_the_full_evidence_bar(self):
        raw = valid_raw()
        raw["requirements"] = {"wechat_research_required": True}
        raw["results"] = [source(1, "aggregator", "Aggregator")]
        built = build_sources.build(raw)
        self.assertFalse(built["gate"]["writing_ready"])
        self.assertIn("缺 1 个 S 级原始来源", built["missing"])


class RegistryCoverageTests(unittest.TestCase):
    def test_absent_registry_does_not_create_an_unpassable_gate(self):
        built = build_sources.build(valid_raw())
        self.assertEqual(built["coverage_audit"]["registry_size"], 0)
        self.assertEqual(
            built["coverage_audit"]["minimums"]["registry_publishers"], 0)
        self.assertTrue(built["gate"]["writing_ready"])

    def test_registry_hits_are_counted_by_publisher_and_domain(self):
        raw = valid_raw()
        raw["source_registry"] = registry()
        built = build_sources.build(raw)
        hits = built["coverage_audit"]["registry_hit_publishers"]
        self.assertIn("peer a", hits)
        self.assertIn("independent media", hits)
        self.assertIn("research institute", hits)
        self.assertTrue(built["gate"]["writing_ready"], built["missing"])

    def test_registry_requirement_reports_the_shortfall(self):
        raw = valid_raw()
        raw["source_registry"] = registry()
        raw["results"] = [entry for entry in raw["results"]
                          if entry["publisher"] not in ("Peer A", "Research Institute")]
        raw["requirements"]["min_accepted_sources"] = 3
        raw["requirements"]["min_visited_results"] = 5
        built = build_sources.build(raw)
        self.assertFalse(built["coverage_audit"]["passed"])
        self.assertTrue(any(item.startswith("名单命中") for item in built["missing"]),
                        built["missing"])

    def test_registry_membership_does_not_upgrade_a_grade(self):
        raw = valid_raw()
        raw["source_registry"] = {"fixed": [{"name": "Aggregator",
                                            "domains": ["aggregator.example"]}]}
        item = source(9, "aggregator", "Aggregator")
        item["final_url"] = "https://aggregator.example/post"
        raw["results"].append(item)
        built = build_sources.build(raw)
        rejected = {entry["id"]: entry for entry in built["rejected_sources"]}
        self.assertIn("src-9", rejected)
        self.assertEqual(rejected["src-9"]["quality_grade"], "C")


class ScanValidatorTests(unittest.TestCase):
    def test_scan_report_must_mark_leads_unverified(self):
        raw = valid_raw()
        raw["depth"] = "scan"
        built = build_sources.build(raw)
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-report.md"
            report.write_text("# 材料说明\n本轮只看了搜索摘要。\n", encoding="utf-8")
            errors, _ = validate_research.validate(built, "scan", str(report))
        self.assertIn("scan output must mark every lead as 待验证", errors)

    def test_report_must_carry_the_material_note(self):
        built = build_sources.build(valid_raw())
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-report.md"
            report.write_text("# 调研结论\n正文\n", encoding="utf-8")
            errors, _ = validate_research.validate(built, "writing", str(report))
        self.assertIn("report is missing the 「材料说明」 section", errors)


class PrefilterTests(unittest.TestCase):
    def test_portal_and_redirect_links_are_dropped_before_opening(self):
        candidates = [
            {"url": "https://www.163.com/dy/article/ABC.html", "published_at": "2026-08-01"},
            {"url": "https://weixin.sogou.com/link?url=abc", "published_at": "2026-08-01"},
            {"url": "https://mp.weixin.qq.com/s/keep", "published_at": "2026-08-01"},
        ]
        result = prefilter_candidates.prefilter(candidates)
        self.assertEqual(result["stats"]["kept"], 1)
        self.assertEqual(result["keep"][0]["url"], "https://mp.weixin.qq.com/s/keep")

    def test_stale_and_undated_candidates_are_dropped(self):
        candidates = [
            {"url": "https://example.com/old", "published_at": "2019-01-01"},
            {"url": "https://example.com/undated"},
        ]
        result = prefilter_candidates.prefilter(candidates)
        self.assertEqual(result["stats"]["kept"], 0)
        reasons = " ".join(item["drop_reason"] for item in result["drop"])
        self.assertIn("outside the freshness window", reasons)
        self.assertIn("no parseable publication date", reasons)

    def test_calibration_profile_blocks_and_prefers_publishers(self):
        candidates = [
            {"url": "https://example.com/a", "publisher": "Padded Account",
             "published_at": "2026-08-01"},
            {"url": "https://example.com/b", "publisher": "Good Media",
             "published_at": "2026-08-01"},
            {"url": "https://example.com/c", "publisher": "Neutral",
             "published_at": "2026-08-01"},
        ]
        profile = {"blocked_publishers": ["Padded Account"],
                   "preferred_publishers": ["Good Media"]}
        result = prefilter_candidates.prefilter(candidates, profile=profile)
        self.assertEqual(result["stats"]["kept"], 2)
        self.assertEqual(result["keep"][0]["publisher"], "Good Media")
        self.assertEqual(result["drop"][0]["publisher"], "Padded Account")


class CapabilityDetectionTests(unittest.TestCase):
    def test_search_only_tier_when_nothing_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = detect_capability.detect(tmp)
        self.assertEqual(report["tier"], "search_only")
        self.assertTrue(report["ask_user_to_configure"])
        self.assertTrue(any("无法按账号" in item for item in report["limits"]))

    def test_user_supplied_tier_when_calibration_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "calibration.csv").write_text("链接\n", encoding="utf-8")
            report = detect_capability.detect(tmp)
        self.assertEqual(report["tier"], "user_supplied")
        self.assertFalse(report["ask_user_to_configure"])

    def test_detection_never_exposes_credential_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = detect_capability.detect(tmp)
        self.assertNotIn("secret", json.dumps(report).lower())
        self.assertEqual(report["mp_data_source"]["env_names"], [])
