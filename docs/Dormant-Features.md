---
name: 休眠特性
description: 存在于代码库但未激活的功能模块
type: reference
created: 2026-03-19
tags: [dormant, inactive, disabled]
---

# 休眠特性（DORMANT）

> 这些代码**存在于代码库中**，但当前**未被任何调度器、路由或服务调用**。

## 1. Feishu 长连接备选实现

| 项 | 值 |
|---|---|
| **文件** | `app/services/feishu_long_connection.py` |
| **状态** | 🟡 DORMANT |
| **原因** | `feishu_event_service.py` 内部有自己的长连接实现，此文件是早期独立版本 |
| **可激活** | 当前实现出问题时切换引用即可 |

## 2. OpenClaw 客户端

| 项 | 值 |
|---|---|
| **文件** | `app/services/notification_service.py` 中被注释的行 |
| **状态** | 🟡 DORMANT |
| **原因** | 临时禁用 `# self.openclaw = OpenClawClient()` |
| **可激活** | 取消注释即可 |

## 3. Rotation Overview 参数

| 项 | 值 |
|---|---|
| **文件** | `app/services/rotation_service.py:1866` |
| **代码** | `overview=None, # DISABLED: look-ahead bias` |
| **状态** | 🟡 DORMANT |
| **原因** | 回测中发现 look-ahead bias，禁用以保证数据纯净 |
| **可激活** | V5验证后，如确认无偏差可恢复 |

---

## 如何检测新的休眠代码

Claude 扫描方法：
1. 搜索 `# DISABLED`, `# TODO`, `# FIXME`
2. 搜索被注释的 `import` 或函数调用
3. 搜索 `app/services/` 中没有被任何 `from app.services` 导入的文件
4. 搜索 `app/routers/` 中没有在 `main.py` 挂载的路由器
