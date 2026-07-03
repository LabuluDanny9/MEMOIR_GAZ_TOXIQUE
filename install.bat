@echo off
chcp 65001 >nul
title Installation — Système Surveillance Gaz Toxiques

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   INSTALLATION — Surveillance Gaz Toxiques v2.0     ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Vérifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Python n'est pas installé ou pas dans le PATH.
    echo  Téléchargez Python 3.10+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER% détecté

:: Créer l'environnement virtuel
echo.
echo  [1/4] Création de l'environnement virtuel...
if not exist venv (
    python -m venv venv
    echo  [OK] Environnement virtuel créé dans .\venv
) else (
    echo  [OK] Environnement virtuel existant trouvé
)

:: Activer venv et installer dépendances
echo.
echo  [2/4] Installation des dépendances Python...
echo        (cela peut prendre 2-5 minutes selon la connexion)
echo.
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo  [ERREUR] L'installation des dépendances a échoué.
    echo  Vérifiez votre connexion internet et réessayez.
    pause
    exit /b 1
)

echo.
echo  [OK] Dépendances installées avec succès

:: Créer les répertoires nécessaires
echo.
echo  [3/4] Création de la structure des répertoires...
if not exist models  mkdir models
if not exist logs    mkdir logs
if not exist data    mkdir data

:: Entraîner les modèles ML
echo.
echo  [4/4] Entraînement des modèles ML (Random Forest + LSTM)...
echo        (peut prendre 5-15 minutes selon votre PC)
echo.
python -c "
import sys
sys.path.insert(0,'.')
from data.generate_dataset import generate_dataset
from server.ml_models import RandomForestDangerClassifier, LSTMGasPredictor

print('  Génération du dataset (3000 enregistrements)...')
df = generate_dataset(3000)

print('  Entraînement Random Forest...')
rf = RandomForestDangerClassifier()
rf.train(df)

print('  Entraînement LSTM...')
lstm = LSTMGasPredictor()
lstm.train(df)

print('  Modèles sauvegardés dans ./models/')
"

if errorlevel 1 (
    echo.
    echo  [AVERTISSEMENT] L'entraînement a échoué.
    echo  Le serveur pourra quand même démarrer et entraînera
    echo  automatiquement les modèles au premier lancement.
)

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║              INSTALLATION TERMINÉE !                 ║
╠══════════════════════════════════════════════════════╣
echo  ║  Pour démarrer le système :                          ║
echo  ║    Double-cliquez sur  start.bat                     ║
echo  ║  Ou avec simulation ESP32 :                          ║
echo  ║    Double-cliquez sur  start_demo.bat                ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
pause
