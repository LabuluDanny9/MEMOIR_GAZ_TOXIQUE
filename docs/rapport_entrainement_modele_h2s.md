# Rapport complet d'entrainement du modele H2S

Projet : Systeme intelligent de surveillance de gaz H2S par ESP32, Flask et Dashboard Web.  
Date de generation : 01/07/2026 11:40  
Notebook associe : `C:\Users\labul\gas_monitoring_system\gas_monitoring_system\notebooks\modele_h2s_complet.ipynb`

## Resume

Le systeme utilise un capteur MQ-136 pour mesurer le H2S. Le modele deploye repose sur deux composants : un Random Forest pour classifier le niveau de danger et un LSTM pour predire l'evolution future de la concentration H2S. La variable principale est `C_H2S_fusion_ppm`. Dans le prototype actuel a capteur unique, cette variable est equivalente a `h2s_ppm`.

## Donnees et variables

Le fichier de metadonnees du modele indique 654 440 lignes propres pour l'entrainement historique. Le jeu local `data/gas_data.csv` contient 8000 lignes et sert au notebook de demonstration. La colonne `co_ppm`, lorsqu'elle existe dans un ancien fichier, est ignoree.

## Seuils de classification

- NORMAL : H2S < 10 ppm
- MODERE : 10 <= H2S < 20 ppm
- DANGEREUX : H2S >= 20 ppm

## Resultats Random Forest

- Accuracy test : 100.00 %
- Balanced accuracy test : 100.00 %
- F1 macro test : 100.00 %
- Importance de `C_H2S_fusion_ppm` : 1.0

## Resultats LSTM

- Fenetre temporelle : 60 mesures
- Horizon : 50 pas
- MAE test : 2.263 ppm
- RMSE test : 4.935 ppm
- R2 test : 0.186

## Conclusion

Le modele est coherent avec le prototype H2S uniquement. Random Forest assure la classification instantanee du danger, tandis que LSTM fournit une estimation de tendance future. Les limites principales sont le desequilibre des classes, la dependance aux seuils et la necessite de recalibrer le capteur MQ-136 sur des mesures terrain reelles.
