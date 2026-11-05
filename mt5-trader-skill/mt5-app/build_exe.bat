@echo off
REM Double-click this on Windows to build dist\mt5trader.exe
setlocal
cd /d "%~dp0"

echo ============================================
echo   mt5-trader-skill : building mt5trader.exe
echo ============================================
echo.

python build_exe.py
set CODE=%ERRORLEVEL%

echo.
if "%CODE%"=="0" (
  echo Done. L'exe f: %~dp0dist\mt5trader.exe
  echo Jarreb: dist\mt5trader.exe doctor
) else (
  echo Build failed with exit code %CODE%.
  echo Ila `python` ma kaynch: installi Python 3.8+ 64-bit mn python.org w 3awed.
)
echo.
pause
