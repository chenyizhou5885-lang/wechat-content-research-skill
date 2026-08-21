#!/usr/bin/env python3

"""Detect which retrieval tier this run can actually reach.

Runs silently at the start of a task. It only checks whether a capability is
present; it never reads, prints or stores credential values. Nothing here is
written to disk.

Tiers, best first:
  mp_data_source  a WeChat data connector is configured (account-scoped lookup)
  user_supplied   the operator provided calibration samples or imported articles
  search_only     host WebSearch/WebFetch plus the bundled Sogou recall
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


# Only the variable names are inspected, never their values.
MP_DATA_SOURCE_ENV = (
    "WCR_MP_PROVIDER",
    "WCR_MP_ENDPOINT",
    "NEWRANK_API_KEY",
    "HONGHU_API_KEY",
)


def env_present(names):
    return sorted(name for name in names if str(os.environ.get(name, "")).strip())


def binary_available(name):
    return shutil.which(name) is not None


def lark_cli_state(check_auth=False):
    """Feishu is a WorkBuddy CLI connector, so lark-cli may exist but be logged out.

    The login probe costs a few seconds of network round-trips, and the tier does not
    depend on it, so it stays opt-in. Only the calibration table needs to know.
    """
    if not binary_available("lark-cli"):
        return {"installed": False, "authenticated": False,
                "hint": "在 WorkBuddy 连接器里连接飞书后即可自动建表，否则改用 CSV"}
    if not check_auth:
        return {"installed": True, "authenticated": None,
                "hint": "登录状态未探测，需要建表时加 --check-lark"}
    try:
        probe = subprocess.run(["lark-cli", "doctor"], capture_output=True,
                               text=True, timeout=15)
        authenticated = probe.returncode == 0
    except (OSError, subprocess.SubprocessError):
        authenticated = False
    return {
        "installed": True,
        "authenticated": authenticated,
        "hint": ("" if authenticated else "lark-cli 已安装但未登录，跑 lark-cli auth login 或改用 CSV"),
    }


def user_material_present(task_dir):
    root = Path(task_dir)
    candidates = ("calibration.csv", "calibration_samples.csv",
                  "calibration_profile.json", "imported_articles.json")
    return sorted(name for name in candidates if (root / name).exists())


def detect(task_dir, check_lark=False):
    provider_env = env_present(MP_DATA_SOURCE_ENV)
    materials = user_material_present(task_dir)
    if provider_env:
        tier = "mp_data_source"
    elif materials:
        tier = "user_supplied"
    else:
        tier = "search_only"

    limits = []
    if tier != "mp_data_source":
        limits.append("无法按账号列出某个公众号的历史文章，只能靠多组关键词提高命中率")
    lark = lark_cli_state(check_auth=check_lark)
    if not lark["installed"]:
        limits.append("校准表格无法自动创建与回填，需要改用 CSV")
    elif lark["authenticated"] is False:
        limits.append("lark-cli 未登录，校准表格需要先登录或改用 CSV")

    return {
        "tier": tier,
        "mp_data_source": {"configured": bool(provider_env), "env_names": provider_env},
        "user_materials": materials,
        "lark_cli": lark,
        "node": {"available": binary_available("node")},
        "webbridge": {"available": binary_available("kimi-webbridge")},
        "limits": limits,
        "ask_user_to_configure": tier == "search_only",
    }


def main():
    parser = argparse.ArgumentParser(description="Detect the retrieval tier for this run")
    parser.add_argument("--task-dir", default=".")
    parser.add_argument("--check-lark", action="store_true",
                        help="also probe lark-cli login state (adds a few seconds)")
    args = parser.parse_args()
    print(json.dumps(detect(args.task_dir, check_lark=args.check_lark),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
