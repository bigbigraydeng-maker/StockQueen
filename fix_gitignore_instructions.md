# 修复 Car Scout Gitignore 步骤

## 问题
`database/vehicles.json` 被 .gitignore 排除，导致 Render 网站没有数据。

## 解决方案

### 步骤1：修改 .gitignore

编辑文件：`C:\Users\Zhong\.openclaw\workspace-car-scout-toyota\.gitignore`

找到这一行：
```
# Database (auto-generated)
database/vehicles.json
```

改为：
```
# Database (auto-generated)
# database/vehicles.json  <-- 注释掉或删除这一行
```

### 步骤2：添加并提交 vehicles.json

在终端中运行：

```bash
cd C:\Users\Zhong\.openclaw\workspace-car-scout-toyota

# 添加 vehicles.json
git add database/vehicles.json

# 提交
git commit -m "Add vehicles database to git for Render deployment"

# 推送
git push origin main
```

### 步骤3：验证

等待 Render 自动部署（约2分钟），然后访问：
https://car-scout.onrender.com/

应该能看到车辆数据了。

---

## 注意事项

- vehicles.json 包含所有车辆数据，会同步到 GitHub
- 文件可能较大（包含图片URL等），但应该没问题
- 以后每次运行 auto-sync.js 后需要 git push 才能更新网站
