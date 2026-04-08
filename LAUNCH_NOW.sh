#!/bin/bash
# 铃铛策略最终启动脚本

echo "=========================================="
echo "铃铛策略（盘中30分钟）启动序列"
echo "=========================================="
echo ""

# 1. 代码推送
echo "[1/3] 推送代码到 main..."
git add -A
git commit -m "feat(intraday): 启用AUTO_EXECUTE，准备模拟盘测试

- 30分钟交易频率
- P0风控完整（维持率、日亏、日冲、自动减仓）
- Tiger模拟账户已配置
- 实时监控系统就绪

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"

git push origin main

echo "✓ 代码已推送"
echo ""

# 2. 验证
echo "[2/3] 最终验证..."
python3 scripts/launch_intraday.py

if [ $? -ne 0 ]; then
    echo "ERROR: 验证失败，请检查上面的错误"
    exit 1
fi

echo ""
echo "✓ 所有验证通过"
echo ""

# 3. 启动指南
echo "[3/3] 启动指南"
echo "=========================================="
echo ""
echo "现在你需要做的："
echo ""
echo "1. 打开 Dashboard:"
echo "   http://localhost:8000/dashboard"
echo ""
echo "2. 等待下一个 30 分钟整点（EDT）:"
echo "   10:00, 10:30, 11:00, 11:30, ... 16:00"
echo ""
echo "3. 首轮评分会自动触发，如果有信号会自动下单"
echo ""
echo "4. 监控这些指标:"
echo "   - 维持率 (> 50% 安全)"
echo "   - 日内 P&L"
echo "   - 活跃头寸数"
echo "   - 日冲计数"
echo ""
echo "5. 如需紧急停止:"
echo "   编辑 app/config/intraday_config.py"
echo "   改 AUTO_EXECUTE = False"
echo ""
echo "=========================================="
echo "🎉 铃铛启动完毕！祝交易顺利！"
echo "=========================================="
