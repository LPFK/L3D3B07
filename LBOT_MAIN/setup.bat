@echo off
REM ==============================================
REM Script de nettoyage et setup - L3D3B07
REM ==============================================

echo ==========================================
echo   L3D3B07 - Nettoyage et Setup
echo ==========================================
echo.

echo [1/4] Nettoyage des virtualenvs...
rmdir /s /q L3D3BOT 2>nul
rmdir /s /q dashboard\dashboard 2>nul
rmdir /s /q venv 2>nul
rmdir /s /q .venv 2>nul
echo       OK

echo [2/4] Nettoyage des fichiers compiles...
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
del /s /q *.pyc 2>nul
echo       OK

echo [3/4] Creation du virtualenv...
python -m venv venv
echo       OK

echo [4/4] Installation des dependances...
call venv\Scripts\pip install -r requirements.txt
call venv\Scripts\pip install -r dashboard\requirements.txt
echo       OK

echo.
echo ==========================================
echo   Setup termine!
echo ==========================================
echo.
echo Prochaines etapes:
echo.
echo 1. Copie .env.exemple vers .env:
echo    copy .env.exemple .env
echo.
echo 2. Remplis le fichier .env avec tes tokens
echo.
echo 3. Lance le bot:
echo    venv\Scripts\python bot.py
echo.
echo 4. Lance le dashboard (dans un autre terminal):
echo    cd dashboard
echo    ..\venv\Scripts\python app.py
echo.
pause
