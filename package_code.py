"""
StockQueen 代码打包脚本
"""
import zipfile
import os
from datetime import datetime

def package_code():
    zip_name = f'StockQueen_Code_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    
    print(f"开始打包 StockQueen 代码...")
    print(f"目标文件: {zip_name}")
    
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 添加app目录
        print("\n添加 app/ 目录...")
        for root, dirs, files in os.walk('app'):
            for file in files:
                if not file.endswith('.pyc') and not file.endswith('.pyo'):
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, 'StockQueen')
                    zipf.write(file_path, arcname)
                    print(f"  {arcname}")
        
        # 添加其他重要文件
        print("\n添加其他重要文件...")
        important_files = [
            'database/schema.sql',
            'backtest_historical.py',
            'requirements.txt',
            '.env.example',
            'README.md',
            'PROJECT_SUMMARY.md'
        ]
        
        for file in important_files:
            if os.path.exists(file):
                arcname = os.path.join('StockQueen', file)
                zipf.write(file, arcname)
                print(f"  {arcname}")
    
    size_mb = os.path.getsize(zip_name) / 1024 / 1024
    print(f"\n✓ 打包完成!")
    print(f"  文件: {zip_name}")
    print(f"  大小: {size_mb:.2f} MB")
    print(f"\n包含内容:")
    print(f"  - app/ 目录（所有Python源代码）")
    print(f"  - database/schema.sql")
    print(f"  - backtest_historical.py（回测脚本）")
    print(f"  - requirements.txt（依赖包）")
    print(f"  - .env.example（配置模板）")
    print(f"  - README.md（项目说明）")
    print(f"  - PROJECT_SUMMARY.md（项目总结）")

if __name__ == "__main__":
    package_code()
