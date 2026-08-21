"""Guard the wiring between SKILL.md, the templates and the scripts.

The previous round shipped working scripts that nothing called. These tests fail
if the pipeline description, the template fields and the script flags drift apart
again.
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
RAW_TEMPLATE = json.loads((ROOT / "templates" / "raw_sources.json").read_text(encoding="utf-8"))
REGISTRY_TEMPLATE = json.loads(
    (ROOT / "templates" / "source_registry.json").read_text(encoding="utf-8"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_sources = load_module("bs_wiring", ROOT / "scripts" / "build_sources.py")


class FrontmatterTests(unittest.TestCase):
    def test_version_is_declared(self):
        self.assertRegex(SKILL, re.compile(r"^version: 0\.7\.\d+$", re.M))

    def test_write_tool_is_declared(self):
        # The pipeline creates raw_sources.json, research-report.md and article-draft.md.
        match = re.search(r"^allowed-tools:\s*(.+)$", SKILL, re.M)
        self.assertIsNotNone(match)
        tools = {item.strip() for item in match.group(1).split(",")}
        self.assertIn("Write", tools)
        self.assertIn("WebFetch", tools)


class PipelineWiringTests(unittest.TestCase):
    def test_pipeline_calls_every_new_script(self):
        for script in ("detect_capability.py", "prefilter_candidates.py",
                       "build_sources.py", "validate_research.py"):
            self.assertIn(script, SKILL, f"SKILL.md never invokes {script}")

    def test_pipeline_mentions_interim_budget_check(self):
        self.assertIn("--interim", SKILL)

    def test_pipeline_offers_all_three_depths(self):
        for depth in build_sources.VALID_DEPTHS:
            self.assertIn(f"`{depth}`", SKILL, f"depth {depth} is not documented")

    def test_material_note_is_required_in_outputs(self):
        self.assertIn("材料说明", SKILL)

    def test_new_references_are_linked_and_exist(self):
        for name in ("source-tiers.md", "targeted-retrieval.md"):
            self.assertIn(f"references/{name}", SKILL, f"{name} is not linked")
            self.assertTrue((ROOT / "references" / name).exists())

    def test_registry_does_not_claim_to_grant_evidence_status(self):
        targeted = (ROOT / "references" / "targeted-retrieval.md").read_text(encoding="utf-8")
        self.assertIn("不代表够格", targeted)

    def test_account_scoped_lookup_limit_is_disclosed(self):
        # Wording may change; the disclosure itself must not disappear.
        self.assertRegex(SKILL, r"(搜不到|没搜到)不等于")

    def test_onboarding_offers_options_instead_of_open_questions(self):
        invite = SKILL[SKILL.index("### 邀请开始"):SKILL.index("## 构建信源组合")]
        self.assertIn("给选项让用户挑", invite)
        # The opening choice must map onto the depth tiers.
        for depth in ("scan", "research", "writing"):
            self.assertIn(f"`{depth}`", invite)

    def test_option_first_principle_is_stated(self):
        self.assertIn("少问，多给选项", SKILL)
        self.assertIn("能自己查的不要问", SKILL)

    def test_research_coordinates_section_survived(self):
        self.assertIn("开始前先建立研究坐标", SKILL)
        self.assertIn("暂定判断", SKILL)

    def test_consent_sensitive_items_are_still_asked(self):
        self.assertIn("必须问", SKILL)


class TemplateTests(unittest.TestCase):
    def test_template_carries_every_field_the_builder_reads(self):
        for key in ("depth", "capability", "material_note", "source_registry"):
            self.assertIn(key, RAW_TEMPLATE, f"template is missing {key}")

    def test_template_depth_is_valid(self):
        self.assertIn(RAW_TEMPLATE["depth"], build_sources.VALID_DEPTHS)

    def test_template_no_longer_hardcodes_depth_scaled_minimums(self):
        # These now come from DEPTH_DEFAULTS; pinning them in the template would
        # silently re-impose writing-level cost on the scan depth.
        for key in ("min_candidates", "min_visited_results",
                    "min_accepted_sources", "min_discovery_channels"):
            self.assertNotIn(key, RAW_TEMPLATE["requirements"],
                             f"{key} should be left to the depth defaults")

    def test_template_builds_without_error(self):
        built = build_sources.build(dict(RAW_TEMPLATE))
        self.assertEqual(built["status"], "ok")
        self.assertFalse(built["gate"]["writing_ready"])
        self.assertTrue(built["missing"])

    def test_registry_template_has_the_three_layers(self):
        for layer in ("fixed", "dynamic", "nominated"):
            self.assertIn(layer, REGISTRY_TEMPLATE)

    def test_registry_template_is_readable_by_the_builder(self):
        names, hosts, size = build_sources.registry_entries(REGISTRY_TEMPLATE)
        self.assertEqual(size, len(REGISTRY_TEMPLATE["fixed"]))
        self.assertTrue(names)
        self.assertTrue(hosts)

    def test_registry_template_warns_against_grade_inflation(self):
        self.assertIn("不决定", REGISTRY_TEMPLATE["_help"]["important"])


class WechatDocTests(unittest.TestCase):
    def setUp(self):
        self.doc = (ROOT / "references" / "wechat-search.md").read_text(encoding="utf-8")

    def test_roles_are_documented_with_their_verification_depth(self):
        self.assertIn("fact_source", self.doc)
        self.assertIn("landscape_only", self.doc)

    def test_landscape_role_is_barred_from_claims(self):
        self.assertIn("不能支撑任何 claim", self.doc)

    def test_shell_pages_must_not_count_as_verified(self):
        self.assertIn("请在微信客户端打开", self.doc)

    def test_self_hosted_rss_scraping_is_not_recommended(self):
        self.assertIn("不得推荐自建 RSS", self.doc)


if __name__ == "__main__":
    unittest.main()
