@echo off
REM Stop all ITR-1 services
echo Stopping all ITR-1 services...

REM Kill processes by window title
taskkill /FI "WINDOWTITLE eq DocParser-8002*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq RAGService-8001*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AgentOrch-8000*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq APIGateway-3001*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Frontend-3000*" /F >nul 2>&1

REM Also kill by port (fallback)
for %%p in (3000 3001 8000 8001 8002) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
        taskkill /PID %%a /F >nul 2>&1
    )
)

echo.
echo All services stopped.
