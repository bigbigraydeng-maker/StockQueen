@echo off
REM StockQueen V1 - Startup Script (Windows)

echo 👑 StockQueen V1 - Starting...

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Check if .env exists
if not exist ".env" (
    echo ⚠️  Warning: .env file not found!
    echo Creating .env from .env.example...
    copy .env.example .env
    echo Please edit .env with your API keys before running the application.
    pause
    exit /b 1
)

REM Start the application
echo Starting FastAPI server...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
