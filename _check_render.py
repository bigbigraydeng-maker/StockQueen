import urllib.request, ssl, os, json
from dotenv import load_dotenv
load_dotenv()

render_key = os.getenv("RENDER_API_KEY") or ""
print("RENDER_API_KEY:", "found" if render_key else "NOT SET - 无法自动触发")

if not render_key:
    print("\n需要在 .env 中设置 RENDER_API_KEY 才能用 API 触发部署")
    exit(0)

ctx = ssl.create_default_context()

# 获取服务列表
req = urllib.request.Request(
    "https://api.render.com/v1/services?limit=10",
    headers={"Authorization": "Bearer " + render_key, "Accept": "application/json"}
)
with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
    services = json.loads(r.read())

target_svc = None
for item in services:
    svc = item.get("service", {})
    name = svc.get("name", "")
    print(f"  {name}  id={svc.get('id')}  autoDeploy={svc.get('autoDeploy')}  branch={svc.get('branch')}")
    if "stockqueen" in name.lower():
        target_svc = svc

if target_svc:
    svc_id = target_svc.get("id")
    print(f"\n找到服务: {target_svc.get('name')} (id={svc_id})")

    # 获取最近部署记录
    req2 = urllib.request.Request(
        f"https://api.render.com/v1/services/{svc_id}/deploys?limit=3",
        headers={"Authorization": "Bearer " + render_key, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req2, context=ctx, timeout=10) as r2:
        deploys = json.loads(r2.read())

    print("\n最近部署记录:")
    for d in deploys:
        dep = d.get("deploy", {})
        print(f"  id={dep.get('id')}  status={dep.get('status')}  createdAt={dep.get('createdAt')}  commit={dep.get('commit', {}).get('id', '')[:7]}")
