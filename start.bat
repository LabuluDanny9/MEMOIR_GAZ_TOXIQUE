@echo off
title KCC GazMonitor — Surveillance H2S/CO
color 0A
chcp 65001 > nul

echo.
echo  =========================================================
echo   KCC GazMonitor   Mine Kamoto, Kolwezi, Lualaba, RDC
echo  =========================================================
echo.

:: Python
set PYTHON=C:\Users\labul\AppData\Local\Programs\Python\Python310\python.exe
if not exist "%PYTHON%" (
    where python > nul 2>&1
    if %errorlevel% == 0 (set PYTHON=python) else (
        echo  [ERREUR] Python introuvable.
        pause & exit /b 1
    )
)
echo  [OK] Python trouve

:: Dependances
"%PYTHON%" -c "import flask, flask_socketio, flask_cors, waitress" > nul 2>&1
if %errorlevel% neq 0 (
    echo  [INSTALL] Installation des dependances...
    "%PYTHON%" -m pip install -q flask flask-socketio flask-cors waitress zeroconf
)
echo  [OK] Dependances OK

:: Nettoyer ancien portproxy (5000) puis rediriger 80 -> 8080
netsh interface portproxy show v4tov4 2>nul | findstr "8080" > nul 2>&1
if %errorlevel% neq 0 (
    echo  [RESEAU] Configuration acces port 80 -^> 8080...
    powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Process cmd -ArgumentList '/c netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0 & netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=8080 connectaddress=127.0.0.1 & netsh advfirewall firewall add rule name=GazMonitorHTTP80 dir=in action=allow protocol=TCP localport=80 profile=any' -Verb RunAs" 2>nul
    timeout /t 3 /nobreak > nul
)
echo  [OK] Port 80 configure

:: Pare-feu port 8080
netsh advfirewall firewall show rule name="GazMonitor Port 8080" > nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="GazMonitor Port 8080" dir=in action=allow protocol=TCP localport=8080 profile=any > nul 2>&1
)

:: IP reseau
for /f "tokens=2 delims=:" %%a in ('ipconfig 2^>nul ^| findstr "IPv4" ^| findstr /v "127.0" ^| findstr /v "169.254"') do (
    set RAW_IP=%%a
    goto :gotip
)
:gotip
set IP=%RAW_IP: =%

echo.
echo  =========================================================
echo   Dashboard reseau  : http://%IP%        (port 80)
echo   Dashboard direct  : http://%IP%:8080
echo   Dashboard local   : http://localhost:8080
echo   Nom DNS local     : http://gazmonitor.local
echo   API ESP32         : POST http://%IP%:8080/api/sensor_data
echo  =========================================================
echo.
echo  Tout le monde sur ce reseau peut voir le tableau de bord
echo  en tapant : http://%IP%   (ou http://%IP%:8080)
echo.

timeout /t 3 /nobreak > nul
start "" "http://localhost:8080"

cd /d "%~dp0"
"%PYTHON%" run_server.py %*
pause
