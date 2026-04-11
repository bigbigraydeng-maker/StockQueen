"""Lab 后台：官网博客 JSON 登记与 HTML 骨架生成（需 git push 后静态站才对外可见）。"""

from __future__ import annotations

import html as html_module
import json
import re
from pathlib import Path
from typing import Any

SLUG_EN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}$")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def blog_posts_path() -> Path:
    return repo_root() / "site" / "data" / "blog-posts.json"


def list_blog_html_files() -> list[str]:
    d = repo_root() / "site" / "blog"
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir() if p.suffix.lower() == ".html" and p.is_file()
    )


def load_blog_posts() -> dict[str, Any]:
    path = blog_posts_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def register_blog_post(entry: dict[str, Any]) -> dict[str, Any]:
    """在 blog-posts.json 头部插入一条（不创建 HTML 文件）。"""
    required = (
        "title_zh", "title_en", "summary_zh", "summary_en",
        "url_zh", "url_en", "published_at",
    )
    for k in required:
        if not entry.get(k):
            raise ValueError(f"missing_field:{k}")
    path = blog_posts_path()
    data = load_blog_posts()
    posts: list = data.setdefault("posts", [])
    row = {k: entry[k] for k in required}
    posts.insert(0, row)
    data["last_updated"] = str(entry["published_at"])[:10]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"ok": True, "total_posts": len(posts)}


def _page(title: str, published_at: str, body_inner: str, lang: str) -> str:
    idx = "-zh" if lang == "zh" else ""
    html_lang = "zh-CN" if lang == "zh" else "en"
    nav_home = "首页" if lang == "zh" else "Home"
    nav_blog = "博客" if lang == "zh" else "Blog"
    t_esc = html_module.escape(title)
    hint = (
        "在仓库中编辑本文件正文后执行 git push，静态站点即可更新。"
        if lang == "zh"
        else "Edit this file in the repo and git push to update the static site."
    )
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{t_esc} | StockQueen</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>body{{font-family:Inter,sans-serif}}</style>
</head>
<body class="bg-[#0b0f19] text-white min-h-screen">
<nav class="border-b border-gray-800 p-4">
  <a href="../index{idx}.html" class="text-cyan-400 text-sm">{nav_home}</a>
  · <a href="./index{idx}.html" class="text-cyan-400 text-sm">{nav_blog}</a>
</nav>
<header class="pt-8 px-4 max-w-3xl mx-auto">
  <p class="text-xs text-gray-500">{html_module.escape(published_at)}</p>
  <h1 class="text-2xl font-bold text-white mt-2">{t_esc}</h1>
</header>
<article class="px-4 pb-20 max-w-3xl mx-auto space-y-6 text-gray-300 leading-relaxed">
  <p class="text-sm text-gray-500">{hint}</p>
  {body_inner}
</article>
<footer class="border-t border-gray-800 py-8 mt-12 text-center text-xs text-gray-500">© StockQueen</footer>
</body></html>
"""


def write_blog_stub_pair(
    *,
    slug_en: str,
    title_zh: str,
    title_en: str,
    intro_zh: str,
    intro_en: str,
    published_at: str,
) -> tuple[str, str]:
    """写入 site/blog/{{slug_en}}-zh.html 与 site/blog/{{slug_en}}.html 极简骨架。"""
    if not SLUG_EN_RE.match(slug_en):
        raise ValueError("invalid_slug_en")
    blog_dir = repo_root() / "site" / "blog"
    blog_dir.mkdir(parents=True, exist_ok=True)
    path_zh = blog_dir / f"{slug_en}-zh.html"
    path_en = blog_dir / f"{slug_en}.html"
    inner_zh = f'<p class="text-gray-300">{html_module.escape(intro_zh)}</p>'
    inner_en = f'<p class="text-gray-300">{html_module.escape(intro_en)}</p>'
    path_zh.write_text(
        _page(title_zh, published_at, inner_zh, "zh"), encoding="utf-8"
    )
    path_en.write_text(
        _page(title_en, published_at, inner_en, "en"), encoding="utf-8"
    )
    return str(path_zh.relative_to(repo_root())), str(path_en.relative_to(repo_root()))
