"""
在本地或 CI 中对 Supabase Postgres 执行 SQL 迁移文件。
需要环境变量 DATABASE_URL（Supabase 控制台 → Project Settings → Database → Connection string → URI）。
勿将 DATABASE_URL 提交到 git。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def _strip_line_comments(sql: str) -> str:
    lines = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def main() -> int:
    _load_dotenv()
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL")
    if not url:
        print(
            "错误: 未设置 DATABASE_URL。\n"
            "请在 .env 中添加（Supabase → Settings → Database → Connection string → URI，\n"
            "使用 Session mode 或 Direct connection，含 postgres 用户密码）。\n"
            "然后运行: python scripts/apply_supabase_migration.py [sql文件路径]",
            file=sys.stderr,
        )
        return 1

    sql_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "supabase" / "migrations" / "20260402120000_intraday_momentum_tracking.sql"
    )
    if not sql_path.is_file():
        print(f"错误: 找不到文件 {sql_path}", file=sys.stderr)
        return 1

    raw = sql_path.read_text(encoding="utf-8")
    sql = _strip_line_comments(raw)
    if not sql:
        print("错误: 无有效 SQL 语句", file=sys.stderr)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("错误: 请安装 psycopg2-binary: pip install psycopg2-binary", file=sys.stderr)
        return 1

    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()

    print(f"完成: {sql_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
