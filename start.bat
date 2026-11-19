@echo off
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
if "%PORT%"=="" set PORT=7860
if "%HOST%"=="" set HOST=127.0.0.1
echo Starting on %HOST%:%PORT%
python -m uvicorn backend.main:app --host %HOST% --port %PORT%
pause
