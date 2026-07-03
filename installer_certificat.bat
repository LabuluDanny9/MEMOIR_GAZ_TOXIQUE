@echo off
title GazMonitor Pro — Installation du certificat HTTPS
color 0B
chcp 65001 > nul

echo.
echo  ============================================================
echo   GazMonitor Pro — Certificat HTTPS de confiance
echo   Elimine le message "Non securise" dans Chrome et Edge
echo  ============================================================
echo.

set CERT=%~dp0ssl\cert.pem

if not exist "%CERT%" (
  echo  [!] Certificat introuvable : %CERT%
  echo      Demarrez d'abord run_server.py pour le generer.
  pause
  exit /b 1
)

echo  Installation dans le magasin Windows (Chrome / Edge)...
certutil -addstore -user -f "Root" "%CERT%"

if %errorlevel%==0 (
  echo.
  echo  [OK] Certificat installe. Redemarrez Chrome ou Edge.
  echo       Le cadenas VERT apparaitra a la prochaine connexion.
) else (
  echo.
  echo  [!] Echec certutil. Essayez en tant qu'administrateur.
  echo      Clic droit sur ce fichier > Executer en tant qu'administrateur
)

echo.
echo  ============================================================
echo   FIREFOX — procedure manuelle :
echo  ============================================================
echo   1. Ouvrez Firefox
echo   2. Menu hamburger (≡) > Parametres > Confidentialite et securite
echo   3. Section "Certificats" > Afficher les certificats
echo   4. Onglet "Autorites" > Importer...
echo   5. Selectionnez : %CERT%
echo   6. Cochez "Faire confiance a cette AC pour identifier des sites web"
echo   7. OK — redemarrez Firefox
echo  ============================================================
echo.
pause
