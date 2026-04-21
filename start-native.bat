@echo off
REM ============================================================
REM  ITR-1 RAG Agent — Native Launcher
REM  Starts all 5 services concurrently using the Python supervisor.
REM  To stop, press Ctrl+C or run stop-native.bat
REM ============================================================

set PROJECT_ROOT=%~dp0
set PYTHON=%PROJECT_ROOT%.venv311\Scripts\python.exe

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found. 
    exit /b 1
)

echo Starting supervisor script...
"%PYTHON%" "%PROJECT_ROOT%run_all.py"
