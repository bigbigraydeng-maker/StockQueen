#!/usr/bin/env python3
"""
实时监控飞书消息事件（简化版）
"""

import time
import os

if __name__ == "__main__":
    log_file = "stockqueen.log"
    
    if not os.path.exists(log_file):
        print(f"错误：日志文件 {log_file} 不存在")
        exit(1)
    
    print("=" * 60)
    print("实时监控飞书消息事件")
    print("=" * 60)
    print(f"监控文件: {log_file}")
    print()
    print("现在请在飞书中给机器人发送消息...")
    print("如果收到消息事件，会在这里显示")
    print()
    print("按 Ctrl+C 停止监控")
    print("=" * 60)
    print()
    
    # 获取文件大小
    file_size = os.path.getsize(log_file)
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            # 跳到文件末尾
            f.seek(file_size)
            
            while True:
                line = f.readline()
                if line:
                    # 检查是否包含关键信息
                    if any(keyword in line for keyword in ['收到飞书消息', 'im.message.receive', 'Chat ID', 'Sender ID', 'Error handling message']):
                        print(line.strip())
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n监控已停止")
