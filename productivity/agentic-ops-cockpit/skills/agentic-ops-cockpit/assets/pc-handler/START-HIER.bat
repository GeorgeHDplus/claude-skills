@echo off
REM Agentic Ops Cockpit — PC-Handler Launcher
REM Laeuft bewusst mit NORMALEN USER-RECHTEN. NICHT als Admin starten
REM (Guard: User-Rechte reichen; Admin ist ein Anti-Pattern).
setlocal
cd /d "%~dp0"

if not exist "%~dp0config.json" (
  echo config.json fehlt.
  echo Kopiere config.example.json nach config.json und trage deine Werte ein.
  echo   copy config.example.json config.json
  echo.
  pause
  exit /b 1
)

REM PowerShell 7 (pwsh) bevorzugen, sonst Windows PowerShell 5.1.
where pwsh >nul 2>&1
if %errorlevel%==0 (
  set "PS=pwsh"
) else (
  set "PS=powershell"
)

echo Starte Cockpit-Handler mit %PS% ...
%PS% -NoProfile -ExecutionPolicy Bypass -File "%~dp0cockpit-handler.ps1"

if errorlevel 1 (
  echo.
  echo Handler wurde mit einem Fehler beendet. Fenster bleibt zur Diagnose offen.
  pause
)
endlocal
