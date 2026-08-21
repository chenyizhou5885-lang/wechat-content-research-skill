#!/usr/bin/env python3

"""Drop hopeless candidates before any page is opened.

Rejection is cheap and rule-based; acceptance stays expensive. Run this on a
raw search-result list so the crawl budget is spent on pages that can actually
become evidence, instead of discovering after a full read that the page was a
portal self-media repost.

Input: JSON list, or {"candidates": [...]}, each item with at least a url.
       Optional per item: title, publisher, published_at, snippet.
Output: {"keep": [...], "drop": [...], "stats": {...}}

A kept candidate is not an accepted source. It has merely earned the cost of
being opened.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_sources import url_level_reject, valid_date, valid_url  # noqa: E402


def load_candidates(path):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        for key in ("candidates", "articles", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return []
    return payload if isinstance(payload, list) else []


def load_profile(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def publisher_of(item):
    for key in ("publisher", "source", "account", "verified_publisher"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return ""


def drop_reason(item, cutoff, blocked_publishers, require_date):
    url = item.get("final_url") or item.get("url") or ""
    if not valid_url(url):
        return "missing or malformed URL"

    reason = url_level_reject(url)
    if reason:
        return reason

    publisher = publisher_of(item).lower()
    if publisher and publisher in blocked_publishers:
        return "publisher marked 「不要」 in the calibration samples"

    published_at = item.get("published_at") or item.get("datetime") or ""
    if published_at and valid_date(str(published_at)[:10]):
        try:
            stamp = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
        except ValueError:
            stamp = None
        if stamp is not None:
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp < cutoff:
                return f"published {stamp.date()}, outside the freshness window"
    elif require_date:
        return "no parseable publication date"

    return ""


def prefilter(candidates, days=365, profile=None, require_date=True):
    profile = profile or {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    blocked = {str(name).strip().lower()
               for name in profile.get("blocked_publishers", []) or []}
    preferred = {str(name).strip().lower()
                 for name in profile.get("preferred_publishers", []) or []}

    keep, drop = [], []
    for item in candidates:
        reason = drop_reason(item, cutoff, blocked, require_date)
        if reason:
            drop.append({**item, "drop_reason": reason})
            continue
        entry = dict(item)
        entry["registry_or_preferred"] = publisher_of(item).lower() in preferred
        keep.append(entry)

    keep.sort(key=lambda entry: not entry["registry_or_preferred"])
    return {
        "keep": keep,
        "drop": drop,
        "stats": {
            "input": len(candidates),
            "kept": len(keep),
            "dropped": len(drop),
            "preferred_hits": sum(1 for entry in keep if entry["registry_or_preferred"]),
            "window_days": days,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Reject candidates before opening pages")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--out")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--profile", help="calibration_profile.json from ingest_calibration.py")
    parser.add_argument("--allow-missing-date", action="store_true",
                        help="keep undated candidates as leads instead of dropping them")
    args = parser.parse_args()

    result = prefilter(load_candidates(args.candidates), days=args.days,
                       profile=load_profile(args.profile),
                       require_date=not args.allow_missing_date)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps(result["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()
