"""
StockQueen 破浪 - API Key 管理 Router

GET  /admin/apikeys              → 主页面（查看所有第三方 API Key 状态）
POST /admin/apikeys/update       → 更新单个 Key（写入 .env）
POST /admin/apikeys/test/{group} → 测试某组 API 连通性
"""

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.middleware.auth import require_admin
from app.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["apikeys"])
templates = Jinja2Templates(directory="app/templates")

# ── API Key 分组定义 ──────────────────────────────────────────────────────
# 每组: group_id, label, keys[]
# 每个 key: env_name, label, is_secret(是否需要遮罩)
API_KEY_GROUPS = [
    {
        "id": "supabase",
        "label": "Supabase 数据库",
        "icon": "🗄️",
        "keys": [
            {"env": "SUPABASE_URL", "label": "URL", "secret": False},
            {"env": "SUPABASE_SERVICE_KEY", "label": "Service Key", "secret": True},
            {"env": "SUPABASE_ANON_KEY", "label": "Anon Key", "secret": True},
        ],
    },
    {
        "id": "massive",
        "label": "Massive (行情数据)",
        "icon": "📈",
        "keys": [
            {"env": "MASSIVE_API_KEY", "label": "API Key", "secret": True},
        ],
    },
    {
        "id": "tiger",
        "label": "Tiger Open API (券商)",
        "icon": "🐯",
        "keys": [
            {"env": "TIGER_ID", "label": "Tiger ID", "secret": False},
            {"env": "TIGER_ACCOUNT", "label": "Account", "secret": False},
            {"env": "TIGER_PRIVATE_KEY", "label": "Private Key (PEM)", "secret": True},
            {"env": "TIGER_SANDBOX", "label": "沙盒模式", "secret": False},
        ],
    },
    {
        "id": "deepseek",
        "label": "DeepSeek AI",
        "icon": "🤖",
        "keys": [
            {"env": "DEEPSEEK_API_KEY", "label": "API Key", "secret": True},
            {"env": "DEEPSEEK_MODEL", "label": "Model", "secret": False},
            {"env": "DEEPSEEK_BASE_URL", "label": "Base URL", "secret": False},
        ],
    },
    {
        "id": "openai",
        "label": "OpenAI (RAG Embedding)",
        "icon": "🧠",
        "keys": [
            {"env": "OPENAI_API_KEY", "label": "API Key", "secret": True},
            {"env": "OPENAI_BASE_URL", "label": "Base URL", "secret": False},
            {"env": "EMBEDDING_MODEL", "label": "Embedding Model", "secret": False},
            {"env": "OPENAI_CHAT_MODEL", "label": "Chat Model", "secret": False},
        ],
    },
    {
        "id": "stripe",
        "label": "Stripe (支付)",
        "icon": "💳",
        "keys": [
            {"env": "STRIPE_SECRET_KEY", "label": "Secret Key", "secret": True},
            {"env": "STRIPE_WEBHOOK_SECRET", "label": "Webhook Secret", "secret": True},
        ],
    },
    {
        "id": "resend",
        "label": "Resend (Newsletter)",
        "icon": "📧",
        "keys": [
            {"env": "RESEND_API_KEY", "label": "API Key", "secret": True},
            {"env": "RESEND_AUDIENCE_ID", "label": "Audience ID", "secret": False},
        ],
    },
    {
        "id": "feishu",
        "label": "飞书 (通知)",
        "icon": "🔔",
        "keys": [
            {"env": "FEISHU_APP_ID", "label": "App ID", "secret": False},
            {"env": "FEISHU_APP_SECRET", "label": "App Secret", "secret": True},
            {"env": "FEISHU_RECEIVE_ID", "label": "Receive ID", "secret": False},
        ],
    },
    {
        "id": "twilio",
        "label": "Twilio (短信)",
        "icon": "📱",
        "keys": [
            {"env": "TWILIO_ACCOUNT_SID", "label": "Account SID", "secret": False},
            {"env": "TWILIO_AUTH_TOKEN", "label": "Auth Token", "secret": True},
            {"env": "TWILIO_PHONE_FROM", "label": "发送号码", "secret": False},
            {"env": "TWILIO_PHONE_TO", "label": "接收号码", "secret": False},
        ],
    },
    {
        "id": "misc",
        "label": "其他",
        "icon": "⚙️",
        "keys": [
            {"env": "ALPHA_VANTAGE_KEY", "label": "Alpha Vantage Key (已废弃)", "secret": True},
            {"env": "OBSIDIAN_VAULT_KEY", "label": "Obsidian Vault Key", "secret": True},
            {"env": "OPENCLAW_WEBHOOK_URL", "label": "OpenClaw Webhook URL", "secret": False},
            {"env": "ADMIN_API_KEY", "label": "Admin API Key", "secret": True},
        ],
    },
]


def _mask_value(val: str, secret: bool) -> str:
    """遮罩敏感值，保留首尾各4字符"""
    if not val:
        return ""
    if not secret:
        return val
    if len(val) <= 12:
        return val[:3] + "***" + val[-2:]
    return val[:4] + "***" + val[-4:]


def _get_env_value(env_name: str) -> str:
    """从当前进程环境变量获取值"""
    return os.environ.get(env_name, "")


def _build_groups_data() -> list[dict]:
    """构建页面展示数据"""
    groups = []
    for g in API_KEY_GROUPS:
        keys = []
        configured_count = 0
        for k in g["keys"]:
            raw = _get_env_value(k["env"])
            configured = bool(raw)
            if configured:
                configured_count += 1
            keys.append({
                "env": k["env"],
                "label": k["label"],
                "secret": k["secret"],
                "configured": configured,
                "masked": _mask_value(raw, k["secret"]),
                "raw_length": len(raw),
            })
        groups.append({
            "id": g["id"],
            "label": g["label"],
            "icon": g["icon"],
            "keys": keys,
            "configured": configured_count,
            "total": len(keys),
            "all_ok": configured_count == len(keys),
        })
    return groups


# ── 主页面 ────────────────────────────────────────────────────────────────

@router.get("/admin/apikeys", response_class=HTMLResponse)
async def apikeys_page(request: Request, _auth=Depends(require_admin)):
    groups = _build_groups_data()
    total_keys = sum(g["total"] for g in groups)
    configured_keys = sum(g["configured"] for g in groups)
    return templates.TemplateResponse("apikeys.html", {
        "request": request,
        "is_guest": False,
        "groups": groups,
        "total_keys": total_keys,
        "configured_keys": configured_keys,
    })


# ── 更新 Key（写入 .env） ─────────────────────────────────────────────────

@router.post("/admin/apikeys/update")
async def update_key(request: Request, _auth=Depends(require_admin)):
    form = await request.form()
    env_name = str(form.get("env_name", "")).strip()
    new_value = str(form.get("new_value", "")).strip()

    if not env_name or not re.match(r"^[A-Z_]+$", env_name):
        return HTMLResponse(
            '<span class="text-red-400 text-xs">无效的环境变量名</span>',
            status_code=400,
        )

    # 验证 env_name 在我们的白名单中
    allowed = {k["env"] for g in API_KEY_GROUPS for k in g["keys"]}
    if env_name not in allowed:
        return HTMLResponse(
            '<span class="text-red-400 text-xs">不允许修改此变量</span>',
            status_code=403,
        )

    # 1) 更新进程内环境变量（立即生效）
    os.environ[env_name] = new_value

    # 2) 更新 .env 文件（持久化）
    env_path = Path(".env")
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^{re.escape(env_name)}=.*$", re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(f"{env_name}={new_value}", content)
        else:
            content = content.rstrip("\n") + f"\n{env_name}={new_value}\n"
        env_path.write_text(content, encoding="utf-8")
    else:
        env_path.write_text(f"{env_name}={new_value}\n", encoding="utf-8")

    logger.info(f"API Key updated: {env_name} (by admin)")

    # 返回更新后的状态 badge
    is_secret = any(
        k["secret"] for g in API_KEY_GROUPS for k in g["keys"] if k["env"] == env_name
    )
    masked = _mask_value(new_value, is_secret) if new_value else ""
    configured = bool(new_value)

    html = f"""
    <div class="flex items-center gap-2">
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs
            {'bg-green-900/30 text-green-400 border border-green-700/30' if configured else 'bg-red-900/30 text-red-400 border border-red-700/30'}">
            {'已配置' if configured else '未配置'}
        </span>
        <span class="text-xs text-gray-400 font-mono">{masked}</span>
        <span class="text-green-400 text-xs ml-2">✓ 已保存</span>
    </div>
    """
    return HTMLResponse(html)


# ── 连通性测试 ─────────────────────────────────────────────────────────────

@router.post("/admin/apikeys/test/{group_id}", response_class=HTMLResponse)
async def test_connection(group_id: str, request: Request, _auth=Depends(require_admin)):
    """测试指定服务组的 API 连通性"""
    testers = {
        "supabase": _test_supabase,
        "massive": _test_massive,
        "deepseek": _test_deepseek,
        "openai": _test_openai,
        "feishu": _test_feishu,
        "resend": _test_resend,
    }

    tester = testers.get(group_id)
    if not tester:
        return HTMLResponse(
            '<span class="text-gray-500 text-xs">此服务暂不支持连通性测试</span>'
        )

    try:
        ok, msg = await tester()
    except Exception as e:
        ok, msg = False, str(e)[:100]

    if ok:
        html = (
            f'<span class="inline-flex items-center gap-1 px-2 py-1 rounded text-xs '
            f'bg-green-900/30 text-green-400 border border-green-700/30">'
            f'✓ 连通正常 — {msg}</span>'
        )
    else:
        html = (
            f'<span class="inline-flex items-center gap-1 px-2 py-1 rounded text-xs '
            f'bg-red-900/30 text-red-400 border border-red-700/30">'
            f'✗ 连接失败 — {msg}</span>'
        )
    return HTMLResponse(html)


# ── 各服务测试函数 ─────────────────────────────────────────────────────────

async def _test_supabase() -> tuple[bool, str]:
    from app.database import get_db
    db = get_db()
    result = db.table("regime_history").select("id", count="exact").limit(1).execute()
    return True, f"regime_history 有 {result.count} 条记录"


async def _test_massive() -> tuple[bool, str]:
    import httpx
    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        return False, "Key 未配置"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.massive.tech/v1/stock/profile",
            params={"symbol": "AAPL"},
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code == 200:
        return True, "AAPL profile OK"
    return False, f"HTTP {resp.status_code}"


async def _test_deepseek() -> tuple[bool, str]:
    import httpx
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not key:
        return False, "Key 未配置"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code == 200:
        return True, "模型列表获取成功"
    return False, f"HTTP {resp.status_code}"


async def _test_openai() -> tuple[bool, str]:
    import httpx
    key = os.environ.get("OPENAI_API_KEY", "")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not key:
        return False, "Key 未配置"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code == 200:
        return True, "模型列表获取成功"
    return False, f"HTTP {resp.status_code}"


async def _test_feishu() -> tuple[bool, str]:
    import httpx
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        return False, "App ID 或 Secret 未配置"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
    data = resp.json()
    if data.get("code") == 0:
        return True, "tenant_access_token 获取成功"
    return False, data.get("msg", f"code={data.get('code')}")


async def _test_resend() -> tuple[bool, str]:
    import httpx
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        return False, "Key 未配置"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.resend.com/domains",
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code == 200:
        domains = resp.json().get("data", [])
        return True, f"{len(domains)} 个域名"
    return False, f"HTTP {resp.status_code}"
