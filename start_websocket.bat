@echo off
chcp 65001 >nul
echo ==========================================
echo  StockQueen V1 - WebSocket Launcher
echo ==========================================
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
) else (
    echo [1/4] Virtual environment found
)

echo.
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo [3/4] Installing dependencies...
pip install -q websockets websocket-client
pip install -q -r requirements.txt

echo.
echo [4/4] Configuration complete!
echo.
echo ==========================================
echo  Choose an option:
echo ==========================================
echo.
echo 1. Start StockQueen with WebSocket
echo 2. Test WebSocket connection only
echo 3. Open API documentation
echo.
set /p choice="Enter your choice (1-3): "

if "%choice%"=="1" (
    echo.
    echo 🚀 Starting StockQueen with WebSocket support...
    echo 📡 WebSocket URL: wss://openapi-sandbox.itiger.com:443/ws
    echo 📊 API Documentation: http://localhost:8000/docs
    echo.
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
)

if "%choice%"=="2" (
    echo.
    echo 🧪 Testing WebSocket connection...
    echo ⏳ This will take about 60 seconds
    echo.
    python test_websocket.py
    echo.
    pause
)

if "%choice%"=="3" (
    echo.
    echo 📖 Opening API documentation...
    start http://localhost:8000/docs
    echo.
    pause
)

echo.
echo 👋 Goodbye!