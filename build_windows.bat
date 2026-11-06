@echo off
REM ============================================================
REM  TraderDesk — compilation de l'application Windows .exe
REM  Double-cliquez sur ce fichier sur un PC Windows avec Python 3.10+
REM  Le resultat sera : dist\TraderDesk.exe
REM ============================================================
setlocal
cd /d "%~dp0"
echo.
echo  [1/3] Verification de Python...
py -3 --version || (echo Python 3 introuvable. Installez-le sur https://python.org & pause & exit /b 1)

echo  [2/3] Installation de PyInstaller...
py -3 -m pip install --upgrade pip pyinstaller || (echo Echec pip & pause & exit /b 1)

echo  [3/3] Compilation de TraderDesk.exe ...
py -3 -m PyInstaller --noconfirm --clean TraderDesk.spec || (echo Echec PyInstaller & pause & exit /b 1)

echo.
echo  ============================================================
echo   TERMINE : dist\TraderDesk.exe
echo   Double-cliquez dessus : le dashboard s'ouvre dans le navigateur.
echo   Pour la passerelle MT5 :
echo     dist\TraderDesk.exe --bridge --api-key VOTRE_CLE --port 8765
echo  ============================================================
echo.
pause
