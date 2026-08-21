#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


MATERIAL_NOTE_HEADING = "材料说明"


def validate(sources, mode, report_path=None, article_path=None):
    errors = []
    warnings = []
    gate = sources.get("gate", {})

    if mode == "writing":
        if not gate.get("writing_ready"):
            errors.append("writing gate failed: source and/or WeChat research is incomplete")
    elif mode == "research":
        if not gate.get("research_ready"):
            warnings.append("research coverage is incomplete; only a limitation-marked research output is allowed")
    elif not gate.get("scan_ready"):
        warnings.append("scan coverage is incomplete; every lead must stay marked as unverified")

    # The scan depth buys speed by refusing to draw conclusions, so it is not held
    # to the evidence bar. Anything above it is.
    if mode != "scan":
        if not gate.get("has_s"):
            errors.append("missing accepted S-grade primary source")
        if not gate.get("has_a"):
            errors.append("missing accepted independent A-grade source")
        if not gate.get("core_claims_ready"):
            errors.append("one or more core claims lack primary/independent evidence")
        if not gate.get("strong_topics_ready"):
            errors.append("one or more strong recommendations lack S + A + enterprise evidence")
        if not gate.get("coverage_ready"):
            coverage = sources.get("coverage_audit", {})
            errors.append(
                "research funnel coverage failed: "
                f"candidates={coverage.get('candidates', 0)}, visited={coverage.get('visited_results', 0)}, "
                f"accepted={coverage.get('accepted_sources', 0)}, "
                f"channels={len(coverage.get('discovery_channels', []))}, "
                f"registry_publishers={len(coverage.get('registry_hit_publishers', []))}"
            )
    if not gate.get("tool_log_ready"):
        errors.append("tool was declared unavailable without a recorded attempt and error")

    wechat = sources.get("wechat_audit", {})
    if mode == "writing" and not wechat.get("required"):
        errors.append("writing mode cannot disable the required WeChat competitor research gate")
    if mode == "writing" and wechat.get("required") and not wechat.get("passed"):
        errors.append(
            f"WeChat gate failed: {wechat.get('verified_articles', 0)}/{wechat.get('min_articles', 0)} articles, "
            f"{wechat.get('verified_publishers', 0)}/{wechat.get('min_publishers', 0)} publishers"
        )

    report_text = ""
    if report_path:
        path = Path(report_path)
        if not path.exists():
            errors.append("research report file does not exist")
        else:
            report_text = path.read_text(encoding="utf-8")
            if MATERIAL_NOTE_HEADING not in report_text:
                errors.append("report is missing the 「材料说明」 section")
            if not gate.get("writing_ready") and re.search(r"强推荐|满足强推荐|门禁完成", report_text):
                errors.append("report claims strong recommendation/gate completion while writing gate failed")
            if mode == "scan" and "待验证" not in report_text:
                errors.append("scan output must mark every lead as 待验证")

    if article_path:
        path = Path(article_path)
        if path.exists() and not gate.get("writing_ready"):
            errors.append("article draft exists although writing gate failed")
        elif mode == "writing" and gate.get("writing_ready") and not path.exists():
            warnings.append("writing gate passed but article draft has not been created yet")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Hard gate before editorial writing")
    parser.add_argument("--sources", required=True)
    parser.add_argument("--mode", choices=("scan", "research", "writing"), default="writing")
    parser.add_argument("--report")
    parser.add_argument("--article")
    args = parser.parse_args()
    sources = read_json(args.sources)
    errors, warnings = validate(sources, args.mode, args.report, args.article)
    payload = {
        "passed": not errors,
        "mode": args.mode,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
