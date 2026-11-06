@echo off
REM Passerelle REST MT5 (a lancer sur le PC Windows ou le terminal MT5 est installe)
REM Usage : start_bridge.bat MA_CLE_API [PORT]
setlocal
cd /d "%~dp0"
set KEY=%1
if "%KEY%"=="" set KEY=change-moi
set PORT=%2
if "%PORT%"=="" set PORT=8765
if exist "dist\TraderDesk.exe" (
  dist\TraderDesk.exe --bridge --api-key %KEY% --port %PORT% --host 0.0.0.0
) else (
  py -3 run.py --bridge --api-key %KEY% --port %PORT% --host 0.0.0.0
)
pause
