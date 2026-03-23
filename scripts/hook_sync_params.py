#!/usr/bin/env python3
"""
PostToolUse hook: 当 Claude 编辑核心参数文件后，自动运行 sync_core_params.py
从 stdin 读取 hook JSON，检查文件路径是否匹配。
"""
import sys
import json
import subprocess
import os

TARGETS = [
    "app/config/rotation_watchlist.py",
    "app/services/multi_factor_scorer.py",
    "app/services/portfolio_manager.py",
    "app/services/mean_reversion_service.py",
    "app/services/event_driven_service.py",
]

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    file_path = (
        data.get("tool_input", {}).get("file_path", "")
        or data.get("tool_response", {}).get("filePath", "")
    )
    # Normalize backslashes
    file_path = file_path.replace("\\", "/")

    if not any(file_path.endswith(t) for t in TARGETS):
        return

    # Run sync script
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sync_script = os.path.join(project_root, "scripts", "sync_core_params.py")
    result = subprocess.run(
        [sys.executable, sync_script],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    # Output hook response
    if result.returncode == 0:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"[auto-sync] params snapshot updated after editing {file_path.split('/')[-1]}"
            }
        }))
    else:
        print(json.dumps({
            "systemMessage": f"[auto-sync] sync_core_params.py failed: {result.stderr[:200]}"
        }))


if __name__ == "__main__":
    main()
