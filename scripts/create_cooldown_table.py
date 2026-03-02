#!/usr/bin/env python3
"""
创建 signal_cooldowns 表
在 Supabase 中执行 SQL 创建冷却期记录表
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db

SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS signal_cooldowns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10) NOT NULL,
    triggered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

SQL_CREATE_INDEX_1 = """
CREATE INDEX IF NOT EXISTS idx_signal_cooldowns_ticker 
    ON signal_cooldowns(ticker);
"""

SQL_CREATE_INDEX_2 = """
CREATE INDEX IF NOT EXISTS idx_signal_cooldowns_triggered_at 
    ON signal_cooldowns(triggered_at);
"""

def create_cooldown_table():
    """创建 signal_cooldowns 表"""
    print("=" * 80)
    print("创建 signal_cooldowns 表")
    print("=" * 80)
    print()
    
    try:
        db = get_db()
        
        # 尝试直接执行 SQL
        print("1. 创建 signal_cooldowns 表...")
        
        # 使用 Supabase 的 SQL 编辑器 API
        import requests
        
        from app.config import settings
        
        url = settings.supabase_url
        key = settings.supabase_service_key
        
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        
        # 尝试通过 pg_execute 执行 SQL
        sql = SQL_CREATE_TABLE + SQL_CREATE_INDEX_1 + SQL_CREATE_INDEX_2
        
        # 方法1: 尝试使用 supabase-py 的 raw query
        try:
            # 先尝试直接插入测试，如果表不存在会报错
            result = db.table("signal_cooldowns").select("*").limit(1).execute()
            print("   ✅ 表已存在")
            return
        except Exception as e:
            if "Could not find the table" in str(e):
                print("   表不存在，需要创建")
            else:
                print(f"   检查表时出错: {e}")
        
        # 方法2: 使用 REST API 直接执行 SQL
        print("\n2. 通过 Supabase REST API 创建表...")
        
        # 使用 /rest/v1/ 端点尝试创建
        response = requests.post(
            f"{url}/rest/v1/rpc/pg_execute",
            headers=headers,
            json={"query": sql}
        )
        
        if response.status_code == 200:
            print("   ✅ 表创建成功")
        else:
            print(f"   ⚠️ pg_execute 不可用: {response.status_code}")
            raise Exception(f"pg_execute failed: {response.text}")
        
    except Exception as e:
        print(f"\n❌ 自动创建失败: {e}")
        print("\n" + "=" * 80)
        print("请手动在 Supabase Dashboard 中执行以下 SQL:")
        print("=" * 80)
        print()
        print(SQL_CREATE_TABLE)
        print(SQL_CREATE_INDEX_1)
        print(SQL_CREATE_INDEX_2)
        print()
        print("=" * 80)
        print("操作步骤:")
        print("1. 登录 https://supabase.com/dashboard")
        print("2. 选择你的项目")
        print("3. 点击左侧 'SQL Editor'")
        print("4. 点击 'New query'")
        print("5. 粘贴上面的 SQL")
        print("6. 点击 'Run'")
        print("=" * 80)

if __name__ == "__main__":
    create_cooldown_table()
