#!/usr/bin/env python3
"""
下载 NotoSansSC 字体到 app/static/fonts/
在 Render buildCommand 中调用，确保 PIL 能渲染中文。
"""
import pathlib
import sys
import urllib.request

FONTS_DIR = pathlib.Path("app/static/fonts")
FONTS_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://raw.githubusercontent.com/googlefonts/noto-cjk/main/Sans/SubsetOTF/SC"
FONTS = {
    "NotoSansSC-Bold.otf":    f"{BASE}/NotoSansSC-Bold.otf",
    "NotoSansSC-Regular.otf": f"{BASE}/NotoSansSC-Regular.otf",
}

for fname, url in FONTS.items():
    dest = FONTS_DIR / fname
    if dest.exists() and dest.stat().st_size > 50_000:
        print(f"[skip]  {fname}  ({dest.stat().st_size // 1024} KB)")
        continue
    print(f"[dl]    {fname}  ← {url}")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"[ok]    {fname}  ({dest.stat().st_size // 1024} KB)")
    except Exception as e:
        print(f"[fail]  {fname}: {e}", file=sys.stderr)
