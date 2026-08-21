#!/usr/bin/env python3

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


S_TYPES = {
    "government_official", "regulator_official", "association_official",
    "academic_primary", "research_report_primary", "company_official",
    "enterprise_internal",
}
A_TYPES = {"media_original"}
B_TYPES = {"vertical_media_original", "expert_original", "competitor_official"}
C_TYPES = {"aggregator", "portal_self_media", "advertorial", "directory_or_review", "unknown"}
ALL_TYPES = S_TYPES | A_TYPES | B_TYPES | C_TYPES
CORE_PRIMARY_TYPES = {"number", "forecast", "company_action", "quote", "definition", "policy"}
VALID_ORIGINALITY = {"original", "reprint", "summary", "unknown"}
VALID_ROLES = {"fact_source", "landscape_only"}
DEFAULT_ROLE = "fact_source"
VALID_DEPTHS = ("scan", "research", "writing")
# Rejection is cheap, acceptance is expensive. Only the writing depth pays full price.
DEPTH_DEFAULTS = {
    "scan": {"candidates": 8, "visited": 0, "accepted": 0, "channels": 1, "registry_publishers": 0},
    "research": {"candidates": 10, "visited": 5, "accepted": 3, "channels": 2, "registry_publishers": 2},
    "writing": {"candidates": 12, "visited": 8, "accepted": 5, "channels": 2, "registry_publishers": 3},
}
LOW_QUALITY_HOSTS = {
    "news.10jqka.com.cn", "m.10jqka.com.cn", "tianqi.csdn.net",
    "saasruanjian.com", "www.saasruanjian.com",
}


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def valid_url(value):
    try:
        parsed = urlsplit(value or "")
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def host_of(value):
    try:
        return urlsplit(value or "").netloc.lower().split(":")[0]
    except ValueError:
        return ""


def valid_date(value):
    if not value:
        return False
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except ValueError:
        return bool(re.match(r"^20\d{2}-\d{2}-\d{2}$", str(value)))


def url_level_reject(url):
    """Rules that need only the URL, so they can run on a search-result list
    before any page is opened. Rejection is cheap; acceptance stays expensive."""
    host = host_of(url)
    path = urlsplit(url).path.lower() if valid_url(url) else ""
    if host in LOW_QUALITY_HOSTS:
        return "known aggregation, distribution, or low-authority host"
    if host.endswith("163.com") and "/dy/" in path:
        return "portal self-media path"
    if host.endswith("sohu.com") and re.match(r"^/a/\d+_\d+", path):
        return "portal distributed-content path"
    if host == "new.qq.com" and "/rain/" in path:
        return "portal feed page; original publisher not established"
    if host == "weixin.sogou.com":
        return "Sogou redirect link; resolve to the real mp.weixin.qq.com URL first"
    return ""


def forced_c_reason(item, final_url):
    reason = url_level_reject(final_url)
    if reason:
        return reason
    if item.get("source_type") in C_TYPES:
        return f"source_type={item.get('source_type')} is discovery-only"
    return ""


def grade_for(item):
    source_type = item.get("source_type", "unknown")
    originality = item.get("originality", "unknown")
    if source_type not in ALL_TYPES:
        return "C", "invalid or unknown source_type"
    if originality not in VALID_ORIGINALITY:
        return "C", "invalid originality"
    if source_type in C_TYPES:
        return "C", f"{source_type} is discovery-only"
    if source_type in S_TYPES:
        if source_type == "enterprise_internal":
            return "S", "enterprise first-party material"
        if originality != "original":
            return "C", "primary source type is not the original page"
        return "S", "primary/original source"
    if source_type in A_TYPES:
        if originality != "original":
            return "C", "A-grade media must be original reporting"
        return "A", "independent original reporting"
    if source_type in B_TYPES:
        if originality not in {"original", "summary"}:
            return "C", "B-grade source cannot be an untraced reprint"
        return "B", "supplementary professional or competitor source"
    return "C", "unclassified"


def audit_result(item):
    reasons = []
    final_url = item.get("final_url") or item.get("url")
    if not item.get("id"):
        reasons.append("missing id")
    if item.get("visited") is not True:
        reasons.append("page was not actually visited")
    if item.get("access") != "open":
        reasons.append("page is not openly accessible")
    if not valid_url(final_url):
        reasons.append("missing valid final URL")
    if not item.get("title"):
        reasons.append("missing page title")
    if not item.get("publisher"):
        reasons.append("missing publisher")
    if not valid_date(item.get("published_at")):
        reasons.append("missing or invalid publication date")
    evidence = item.get("content_evidence") or []
    if not isinstance(evidence, list) or not any(str(x).strip() for x in evidence):
        reasons.append("missing page-level content evidence")

    grade, grade_reason = grade_for(item)
    forced = forced_c_reason(item, final_url)
    if forced:
        grade = "C"
        grade_reason = forced

    role = item.get("role") or DEFAULT_ROLE
    if role not in VALID_ROLES:
        reasons.append(f"invalid role={role}")

    if item.get("platform") == "wechat":
        if host_of(final_url) != "mp.weixin.qq.com":
            reasons.append("final URL is not a WeChat article")
        if not all(item.get(key) for key in ("verified_title", "verified_publisher")):
            reasons.append("missing verified WeChat title/publisher")
        if role == "landscape_only":
            # Evidence about how peers frame a topic, not a factual claim.
            # Resolved URL + title + publisher + date is enough; no full body read.
            if item.get("verification") not in {"verified", "resolved"}:
                reasons.append("WeChat landscape source needs a resolved original URL")
        else:
            if item.get("verification") != "verified":
                reasons.append("WeChat fact source was not verified against the original article")
            if not item.get("verified_published_at"):
                reasons.append("missing verified WeChat date")
            if int(item.get("body_length") or 0) <= 0:
                reasons.append("WeChat body was not readable")

    accepted = grade in {"S", "A", "B"} and not reasons
    normalized = dict(item)
    normalized["final_url"] = final_url
    normalized["role"] = role
    normalized["quality_grade"] = grade
    normalized["grade_reason"] = grade_reason
    normalized["accepted"] = accepted
    normalized["rejection_reasons"] = reasons + ([] if grade != "C" else [grade_reason])
    return normalized


def independent_publishers(items):
    return {str(item.get("publisher", "")).strip().lower() for item in items if item.get("publisher")}


def registry_entries(registry):
    """Flatten the per-industry source registry into publisher names and domains.
    The registry says what is worth retrieving; it never says what counts as evidence."""
    names, hosts = set(), set()
    entry_count = 0
    for layer in ("fixed", "dynamic"):
        for entry in registry.get(layer) or []:
            entry_count += 1
            name = str(entry.get("name", "")).strip().lower()
            if name:
                names.add(name)
            for domain in entry.get("domains") or []:
                host = str(domain).strip().lower().lstrip(".")
                if host:
                    hosts.add(host)
    return names, hosts, entry_count


def matches_registry(item, names, hosts):
    publisher = str(item.get("publisher", "")).strip().lower()
    if publisher and publisher in names:
        return True
    verified = str(item.get("verified_publisher", "")).strip().lower()
    if verified and verified in names:
        return True
    host = host_of(item.get("final_url") or item.get("url"))
    return any(host == entry or host.endswith("." + entry) for entry in hosts)


def build(raw):
    audited = [audit_result(item) for item in raw.get("results", [])]
    accepted = [item for item in audited if item["accepted"]]
    rejected = [item for item in audited if not item["accepted"]]
    by_id = {item["id"]: item for item in accepted if item.get("id")}

    claim_audit = []
    for claim in raw.get("claim_ledger", []):
        linked = [by_id[sid] for sid in claim.get("source_ids", []) if sid in by_id]
        # Landscape-only sources are evidence about how peers write, never about facts.
        landscape_ids = [item["id"] for item in linked if item.get("role") == "landscape_only"]
        sources = [item for item in linked if item.get("role") != "landscape_only"]
        grades = [source["quality_grade"] for source in sources]
        has_s = "S" in grades
        a_sources = [source for source in sources if source["quality_grade"] == "A"]
        has_two_independent_a = len(independent_publishers(a_sources)) >= 2
        needs_primary = bool(claim.get("core")) and claim.get("claim_type") in CORE_PRIMARY_TYPES
        passed = bool(sources) and (has_s or has_two_independent_a if needs_primary else True)
        if landscape_ids:
            passed = False
        claim_audit.append({
            **claim,
            "accepted_source_ids": [source["id"] for source in sources],
            "rejected_landscape_source_ids": landscape_ids,
            "grades": grades,
            "passed": passed,
            "reason": ("landscape-only sources cannot support a claim; cite the original instead"
                       if landscape_ids else
                       "covered by primary/independent evidence" if passed else
                       "core fact requires one S source or two independent A sources" if needs_primary else
                       "no accepted source"),
        })

    enterprise_ids = {item.get("id") for item in raw.get("enterprise_materials", [])
                      if item.get("id") and item.get("authorized_for_publication") is True}
    topic_audit = []
    for topic in raw.get("selected_topics", []):
        sources = [by_id[sid] for sid in topic.get("source_ids", []) if sid in by_id]
        grades = {source["quality_grade"] for source in sources}
        has_enterprise = bool(enterprise_ids.intersection(topic.get("enterprise_material_ids", [])))
        strong_requested = topic.get("recommendation") == "strong"
        strong_ready = "S" in grades and "A" in grades and has_enterprise
        topic_audit.append({
            **topic,
            "strong_ready": strong_ready,
            "passed": (strong_ready if strong_requested else True),
            "reason": ("strong evidence structure complete" if strong_ready else
                       "strong recommendation requires S + independent A + authorized enterprise material"),
        })

    requirements = raw.get("requirements", {})
    depth = str(raw.get("depth") or requirements.get("depth") or "writing").strip().lower()
    if depth not in VALID_DEPTHS:
        depth = "writing"
    defaults = DEPTH_DEFAULTS[depth]

    wechat_required = requirements.get("wechat_research_required", False) is True and depth != "scan"
    # Any accepted WeChat source already cleared the bar for its own role.
    verified_wechat = [item for item in accepted if item.get("platform") == "wechat"]
    min_articles = int(requirements.get("min_verified_wechat_articles", 3))
    min_publishers = int(requirements.get("min_verified_wechat_publishers", 2))
    wechat_publishers = independent_publishers(verified_wechat)
    wechat_ready = (not wechat_required or
                    (len(verified_wechat) >= min_articles and
                     len(wechat_publishers) >= min_publishers))

    min_candidates = int(requirements.get("min_candidates", defaults["candidates"]))
    min_visited = int(requirements.get("min_visited_results", defaults["visited"]))
    min_accepted = int(requirements.get("min_accepted_sources", defaults["accepted"]))
    min_channels = int(requirements.get("min_discovery_channels", defaults["channels"]))
    candidate_count = len(raw.get("candidate_pool", []))
    visited_count = sum(1 for item in raw.get("results", []) if item.get("visited") is True)
    discovery_channels = {item.get("channel") for item in raw.get("queries", []) if item.get("channel")}

    registry_names, registry_hosts, registry_size = registry_entries(raw.get("source_registry", {}))
    registry_hits = [item for item in accepted
                     if matches_registry(item, registry_names, registry_hosts)]
    registry_publishers = independent_publishers(registry_hits)
    # You cannot hit a list that does not exist. Requiring registry coverage when no
    # registry was supplied would be a gate nobody can pass, so cap it by the list size.
    min_registry_publishers = min(
        int(requirements.get("min_registry_publishers", defaults["registry_publishers"])),
        registry_size,
    )

    coverage_ready = (candidate_count >= min_candidates and visited_count >= min_visited
                      and len(accepted) >= min_accepted and len(discovery_channels) >= min_channels
                      and len(registry_publishers) >= min_registry_publishers)

    core_claims_ready = all(item["passed"] for item in claim_audit if item.get("core"))
    strong_topics_ready = all(item["passed"] for item in topic_audit)
    has_s = any(item["quality_grade"] == "S" for item in accepted)
    has_a = any(item["quality_grade"] == "A" for item in accepted)
    tool_attempts = raw.get("tool_attempts", [])
    webbridge_claimed_unavailable = any(
        item.get("tool") == "kimi-webbridge" and item.get("status") == "unavailable"
        for item in tool_attempts
    )
    webbridge_attempt_proven = any(
        item.get("tool") == "kimi-webbridge" and item.get("attempted") is True
        and item.get("command") and item.get("error")
        for item in tool_attempts
    )
    tool_log_ready = not webbridge_claimed_unavailable or webbridge_attempt_proven

    scan_ready = tool_log_ready and coverage_ready
    research_ready = (has_s and has_a and core_claims_ready and strong_topics_ready
                      and tool_log_ready and coverage_ready)
    writing_ready = research_ready and wechat_ready

    missing = []
    if candidate_count < min_candidates:
        missing.append(f"候选池 {candidate_count}/{min_candidates}")
    if visited_count < min_visited:
        missing.append(f"实际读取 {visited_count}/{min_visited}")
    if len(accepted) < min_accepted:
        missing.append(f"采纳来源 {len(accepted)}/{min_accepted}")
    if len(discovery_channels) < min_channels:
        missing.append(f"发现渠道 {len(discovery_channels)}/{min_channels}")
    if len(registry_publishers) < min_registry_publishers:
        missing.append(f"名单命中 {len(registry_publishers)}/{min_registry_publishers} 家")
    if depth != "scan":
        if not has_s:
            missing.append("缺 1 个 S 级原始来源")
        if not has_a:
            missing.append("缺 1 个独立 A 级来源")
        for item in claim_audit:
            if item.get("core") and not item["passed"]:
                missing.append(f"核心事实待回溯：{item.get('id')}")
        for item in topic_audit:
            if not item["passed"]:
                missing.append(f"强推荐证据不足：{item.get('title')}")
    if wechat_required and not wechat_ready:
        missing.append(f"公众号 {len(verified_wechat)}/{min_articles} 篇、"
                       f"{len(wechat_publishers)}/{min_publishers} 个号")
    if not tool_log_ready:
        missing.append("声明工具不可用但没有留下命令与错误")

    return {
        "status": "ok",
        "depth": depth,
        "research_brief": raw.get("research_brief", {}),
        "requirements": requirements,
        "capability": raw.get("capability", {}),
        "material_note": raw.get("material_note", {}),
        "queries": raw.get("queries", []),
        "tool_attempts": tool_attempts,
        "candidate_count": candidate_count,
        "missing": missing,
        "coverage_audit": {
            "candidates": candidate_count,
            "visited_results": visited_count,
            "accepted_sources": len(accepted),
            "discovery_channels": sorted(discovery_channels),
            "registry_size": registry_size,
            "registry_hit_publishers": sorted(registry_publishers),
            "minimums": {
                "candidates": min_candidates,
                "visited_results": min_visited,
                "accepted_sources": min_accepted,
                "discovery_channels": min_channels,
                "registry_publishers": min_registry_publishers,
            },
            "passed": coverage_ready,
        },
        "accepted_sources": accepted,
        "rejected_sources": rejected,
        "claim_audit": claim_audit,
        "topic_audit": topic_audit,
        "wechat_audit": {
            "required": wechat_required,
            "verified_articles": len(verified_wechat),
            "verified_publishers": len(independent_publishers(verified_wechat)),
            "min_articles": min_articles,
            "min_publishers": min_publishers,
            "passed": wechat_ready,
        },
        "gate": {
            "depth": depth,
            "has_s": has_s,
            "has_a": has_a,
            "core_claims_ready": core_claims_ready,
            "strong_topics_ready": strong_topics_ready,
            "tool_log_ready": tool_log_ready,
            "coverage_ready": coverage_ready,
            "scan_ready": scan_ready,
            "research_ready": research_ready,
            "writing_ready": writing_ready,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Normalize and audit editorial research sources")
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out")
    parser.add_argument("--depth", choices=VALID_DEPTHS,
                        help="override the depth recorded in raw_sources.json")
    parser.add_argument("--interim", action="store_true",
                        help="report what is still missing without writing sources.json")
    args = parser.parse_args()
    raw = read_json(args.raw)
    if args.depth:
        raw["depth"] = args.depth
    result = build(raw)

    if args.interim:
        print(json.dumps({
            "status": "interim",
            "depth": result["depth"],
            "accepted": len(result["accepted_sources"]),
            "missing": result["missing"],
            "next_action": (result["missing"][0] if result["missing"]
                            else "覆盖已达标，可以继续核验与写作"),
        }, ensure_ascii=False))
        return

    if not args.out:
        parser.error("--out is required unless --interim is used")
    write_json(args.out, result)
    print(json.dumps({
        "status": result["status"],
        "depth": result["depth"],
        "accepted": len(result["accepted_sources"]),
        "rejected": len(result["rejected_sources"]),
        "missing": result["missing"],
        "scan_ready": result["gate"]["scan_ready"],
        "research_ready": result["gate"]["research_ready"],
        "writing_ready": result["gate"]["writing_ready"],
        "out": str(Path(args.out).resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
