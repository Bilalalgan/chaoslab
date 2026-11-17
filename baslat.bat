@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChaosLab Sunucu - kapatinca sunucu durur
if not exist ".venv\Scripts\python.exe" (
    echo [ChaosLab] .venv yok, kuruluyor...
    python -m venv .venv || (echo Python bulunamadi. & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)
start "" /b cmd /c "timeout /t 3 /nobreak >NUL & start http://127.0.0.1:8000"
echo [ChaosLab] http://127.0.0.1:8000  -  Kapatmak icin bu pencereyi kapat (veya Ctrl+C).
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
