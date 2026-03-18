"""
Generate changelog.json from git log.

Usage:
    python scripts/generate_changelog.py              # default 90 days
    python scripts/generate_changelog.py --days 30    # last 30 days

Reads git log, categorizes commits, filters sensitive info,
and writes site/data/changelog.json for dashboard + public website.
"""

import argparse
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime

# --- Sensitive info filters ---

SKIP_PATTERNS = [
    re.compile(r"^Merge ", re.IGNORECASE),
    re.compile(r"^Co-Authored-By:", re.IGNORECASE),
]

SENSITIVE_WORDS = re.compile(
    r"api[_\s]?key|password|secret|token|credential|\.env|"
    r"service[_\s]?key|private[_\s]?key",
    re.IGNORECASE,
)

REDACT_MAP = [
    (re.compile(r"\bSupabase\b", re.IGNORECASE), "database"),
    (re.compile(r"\bTiger\b", re.IGNORECASE), "broker"),
    (re.compile(r"\bcache_store\b"), "data cache"),
    (re.compile(r"\bbt_fundamentals\b"), "fundamentals cache"),
    (re.compile(r"\bsb-access-token\b"), "auth token"),
    (re.compile(r"\bsb-refresh-token\b"), "refresh token"),
    (re.compile(r"\bSUPABASE_\w+\b"), "DB config"),
    (re.compile(r"\bTIGER_\w+\b"), "broker config"),
    (re.compile(r"\bADMIN_API_KEY\b"), "admin key"),
]

# --- Category detection ---

PREFIX_MAP = {
    "feat": "feature",
    "feature": "feature",
    "fix": "bugfix",
    "bugfix": "bugfix",
    "docs": "docs",
    "doc": "docs",
    "refactor": "improvement",
    "chore": "improvement",
    "test": "test",
    "perf": "improvement",
    "style": "improvement",
    "ci": "improvement",
}


def detect_category(message: str) -> str:
    match = re.match(r"^(\w+)[\(:]", message)
    if match:
        prefix = match.group(1).lower()
        return PREFIX_MAP.get(prefix, "improvement")
    lower = message.lower()
    if "fix" in lower or "bug" in lower:
        return "bugfix"
    if "add" in lower or "new" in lower:
        return "feature"
    return "improvement"


def clean_message(message: str) -> str:
    """Remove conventional commit prefix and redact sensitive terms."""
    # Strip prefix like "feat: " or "fix(scope): "
    cleaned = re.sub(r"^\w+(\([^)]*\))?\s*:\s*", "", message)

    # Apply redaction map
    for pattern, replacement in REDACT_MAP:
        cleaned = pattern.sub(replacement, cleaned)

    # Capitalize first letter
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned


def should_skip(message: str) -> bool:
    """Check if commit should be excluded."""
    for pattern in SKIP_PATTERNS:
        if pattern.search(message):
            return True
    if SENSITIVE_WORDS.search(message):
        return True
    return False


def _parse_git_log_output(stdout: str) -> list:
    """Parse git log output lines into entry dicts."""
    entries = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append({
                "hash": parts[0],
                "date": parts[1],
                "message": parts[2],
            })
    return entries


def get_git_log(days: int, repo_dir: str) -> list:
    """Get git log entries for the last N days, with fallback."""
    # Check git depth first
    depth_check = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, cwd=repo_dir, encoding="utf-8",
    )
    commit_count = int(depth_check.stdout.strip()) if depth_check.returncode == 0 else 0
    print(f"DEBUG: git repo has {commit_count} commits available")

    cmd = [
        "git", "log",
        f"--since={days} days ago",
        "--pretty=format:%h|%ad|%s",
        "--date=short",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=repo_dir, encoding="utf-8"
    )
    if result.returncode != 0:
        print(f"ERROR: git log failed: {result.stderr}")
        return []

    entries = _parse_git_log_output(result.stdout)
    print(f"DEBUG: git log --since={days}d returned {len(entries)} entries")

    # Fallback: if --since returned nothing but we have commits, try without date filter
    if not entries and commit_count > 0:
        print("WARN: --since returned 0 entries, falling back to last 200 commits")
        fallback_cmd = [
            "git", "log", "-200",
            "--pretty=format:%h|%ad|%s",
            "--date=short",
        ]
        fallback = subprocess.run(
            fallback_cmd, capture_output=True, text=True, cwd=repo_dir, encoding="utf-8"
        )
        if fallback.returncode == 0:
            entries = _parse_git_log_output(fallback.stdout)
            print(f"DEBUG: fallback returned {len(entries)} entries")

    return entries


def generate_changelog(days: int = 90) -> dict:
    """Generate changelog data from git log."""
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entries = get_git_log(days, repo_dir)

    # Group by date
    by_date = defaultdict(list)
    for entry in entries:
        msg = entry["message"]
        if should_skip(msg):
            continue

        by_date[entry["date"]].append({
            "hash": entry["hash"],
            "category": detect_category(msg),
            "message": clean_message(msg),
            "detail": msg,
        })

    # Sort dates descending
    sorted_dates = sorted(by_date.keys(), reverse=True)

    changelog = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "entries": [
            {"date": date, "changes": by_date[date]}
            for date in sorted_dates
            if by_date[date]  # skip empty dates
        ],
    }

    return changelog


def main():
    parser = argparse.ArgumentParser(description="Generate changelog from git log")
    parser.add_argument("--days", type=int, default=90, help="Number of days (default: 90)")
    args = parser.parse_args()

    changelog = generate_changelog(args.days)

    # Write to site/data/changelog.json
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_path = os.path.join(repo_dir, "site", "data", "changelog.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(changelog, f, ensure_ascii=False, indent=2)

    total = sum(len(e["changes"]) for e in changelog["entries"])
    print(f"Generated changelog: {len(changelog['entries'])} days, {total} commits")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
