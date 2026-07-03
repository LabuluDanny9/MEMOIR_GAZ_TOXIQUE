@echo off
title Reseau Serveur GazMonitor (point d'acces)
color 0B
chcp 65001 > nul

echo.
echo  ============================================================
echo   Creation du reseau WiFi du serveur GazMonitor
echo   L'ESP32 s'y connectera AUTOMATIQUEMENT
echo  ============================================================
echo.
echo   Nom du reseau (SSID) : GazMonitor-Net
echo   Mot de passe         : gazmonitor2026
echo.

:: Active le partage de connexion (Mobile Hotspot) via PowerShell + WinRT
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ssid='GazMonitor-Net'; $pass='gazmonitor2026';" ^
  "try {" ^
  "  netsh wlan set hostednetwork mode=allow ssid=$ssid key=$pass | Out-Null;" ^
  "  $r = netsh wlan start hostednetwork;" ^
  "  Write-Host $r;" ^
  "} catch { Write-Host 'Methode hostednetwork indisponible.' }"

echo.
echo  ------------------------------------------------------------
echo   Si le reseau n'a pas demarre ci-dessus, activez le
echo   "Point d'acces sans fil mobile" de Windows manuellement :
echo     Parametres ^> Reseau et Internet ^> Point d'acces mobile
echo     - Nom du reseau : GazMonitor-Net
echo     - Mot de passe  : gazmonitor2026
echo  ------------------------------------------------------------
echo.
echo   IP du serveur sur ce reseau : 192.168.137.1
echo   (l'ESP32 utilise cette adresse automatiquement)
echo.
echo   Laissez cette fenetre ouverte. Lancez ensuite start.bat
echo.
pause
