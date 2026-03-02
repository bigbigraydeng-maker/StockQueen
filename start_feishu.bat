@echo off
chcp 65001 >nul
echo ==========================================
echo  StockQueen - Feishu Event Connection
echo ==========================================
echo.
echo App ID: cli_a92adfa4a478dbc2
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
) else (
    echo [1/3] Virtual environment found
)

echo.
echo [2/3] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo [3/3] Installing dependencies...
pip install -q websockets
pip install -q -r requirements.txt 2>nul

echo.
echo ==========================================
echo  Choose an option:
echo ==========================================
echo.
echo 1. Start StockQueen with Feishu Connection
echo 2. Test Feishu Connection Only
echo 3. Check Configuration
echo.
set /p choice="Enter your choice (1-3): "

if "%choice%"=="1" (
    echo.
    echo 🚀 Starting StockQueen...
    echo 📱 Feishu App ID: cli_a92adfa4a478dbc2
    echo 🔌 Connecting to: wss://ws.feishu.cn/ws
    echo.
    echo Press Ctrl+C to stop
    echo.
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
)

if "%choice%"=="2" (
    echo.
    echo 🧪 Testing Feishu Connection...
    echo ⏳ This will test the WebSocket connection
    echo.
    python test_feishu_connection.py
    echo.
    pause
)

if "%choice%"=="3" (
    echo.
    echo 📋 Current Configuration:
    echo.
    echo [Feishu]
    for /f "tokens=1,2 delims==" %%a in ('type .env ^| findstr "FEISHU"') do (
        if "%%a"=="FEISHU_APP_SECRET" (
            echo %%a=%%b... (hidden)
        ) else (
            echo %%a=%%b
        )
    )
    echo.
    pause
)

echo.
echo 👋 Goodbye!