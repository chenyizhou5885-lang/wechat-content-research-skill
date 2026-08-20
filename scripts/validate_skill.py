#!/usr/bin/env python3

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def frontmatter(text):
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return ""
    return text.split("\n---\n", 1)[0][4:]


def main():
    errors = []
    skill_path = ROOT / "SKILL.md"
    if not skill_path.exists():
        errors.append("SKILL.md missing")
        skill_text = ""
    else:
        skill_text = skill_path.read_text(encoding="utf-8")

    header = frontmatter(skill_text)
    for field in ("name", "description", "category", "version", "author"):
        if not re.search(rf"(?m)^{re.escape(field)}\s*:", header):
            errors.append(f"frontmatter missing {field}")
    version = re.search(r"(?m)^version:\s*([^\s]+)", header)
    if version and not re.fullmatch(r"\d+\.\d+\.\d+", version.group(1).strip('"\'')):
        errors.append("version is not semantic x.y.z")

    required = [
        ROOT / "references" / "source-pipeline.md",
        ROOT / "references" / "source-quality.md",
        ROOT / "templates" / "raw_sources.json",
        ROOT / "scripts" / "build_sources.py",
        ROOT / "scripts" / "validate_research.py",
        ROOT / "scripts" / "search-wechat.js",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"required file missing: {path.relative_to(ROOT)}")

    template = ROOT / "templates" / "raw_sources.json"
    if template.exists():
        try:
            json.loads(template.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            errors.append(f"invalid raw_sources template: {error}")

    for path in (ROOT / "scripts").glob("*.py"):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as error:
            errors.append(f"Python syntax error in {path.name}: {error}")

    node_script = ROOT / "scripts" / "search-wechat.js"
    if node_script.exists():
        check = subprocess.run(["node", "--check", str(node_script)], capture_output=True, text=True)
        if check.returncode != 0:
            errors.append(f"Node syntax error: {check.stderr.strip()}")

    all_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    )
    user_home_pattern = re.escape("/" + "Users/") + r"[^/\s]+/"
    if re.search(user_home_pattern, all_text):
        errors.append("package contains a user-specific absolute path")
    if re.search(r"(?i)(api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"][A-Za-z0-9_-]{16,}", all_text):
        errors.append("package may contain a hard-coded credential")

    markdown_files = [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        targets = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
        targets += re.findall(r"@((?:references|templates)/[A-Za-z0-9._/-]+)", text)
        for target in targets:
            if "://" in target or target.startswith("#"):
                continue
            resolved = (path.parent / target).resolve() if not target.startswith(("references/", "templates/")) else (ROOT / target).resolve()
            if not resolved.exists():
                errors.append(f"broken local reference in {path.relative_to(ROOT)}: {target}")

    payload = {"passed": not errors, "errors": errors, "root": str(ROOT)}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
