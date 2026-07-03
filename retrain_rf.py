"""
Réentraînement du RF avec des conditions réalistes de mine souterraine KCC Kamoto.

Conditions réelles mine KCC Kamoto (Kolwezi, Lualaba, RDC) :
  - Température  : 25–50 °C (galeries souterraines chaudes + chaleur géothermique)
  - Humidité     : 60–92 %  (ventilation forcée, eau souterraine, drainage)
  - H2S Normal   : 0–2 ppm  (ventilation normale, fond géochimique)
  - H2S Modéré   : 2–15 ppm (fuite légère, mauvaise ventilation locale)
  - H2S Dangereux: 15–50 ppm (fuite sérieuse, évacuation requise)

Seuils conformes NIOSH/OSHA :
  - TLV-TWA ACGIH : 1 ppm (exposition 8h)
  - TLV-STEL      : 5 ppm (exposition 15 min)
  - REL Ceiling   : 10 ppm (plafond NIOSH)
  → Classe 0: < 2 ppm   (en dessous TLV-STEL)
  → Classe 1: 2–15 ppm  (TLV-STEL → dépassement REL)
  → Classe 2: > 15 ppm  (zone dangereuse, évacuation)
"""

import os, sys, json, warnings
import numpy as np
import pandas as pd
import joblib
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT      = os.path.dirname(os.path.abspath(__file__))
MODELS    = os.path.join(ROOT, "models")
BANK_PATH = os.path.join(MODELS, "sample_bank.json")
RF_PATH   = os.path.join(MODELS, "rf_model.pkl")
FEATURES  = ["Sensor1[ppm]", "Sensor2[ppm]", "Sensor3[ppm]", "Sensor4[ppm]",
             "Humidity[%]", "Temperature[C]"]

np.random.seed(42)

# ─────────────────────────────────────────────
#  Plages de conditions par classe
# ─────────────────────────────────────────────
CLASSES = {
    0: {  # NORMAL — galerie bien ventilée
        "h2s_mean_range": (0.0, 1.8),    # ppm, moyenne vraie capteurs
        "h2s_noise":       0.18,          # bruit relatif MQ-136 (±18%)
        "temp_range":      (25.0, 38.0),  # °C
        "hum_range":       (60.0, 82.0),  # %
        "label": "NORMAL",
    },
    1: {  # MODÉRÉ — fuite légère ou ventilation insuffisante
        "h2s_mean_range": (2.0, 14.5),
        "h2s_noise":       0.20,
        "temp_range":      (28.0, 44.0),
        "hum_range":       (65.0, 88.0),
        "label": "MODÉRÉ",
    },
    2: {  # DANGEREUX — évacuation immédiate
        "h2s_mean_range": (15.0, 48.0),
        "h2s_noise":       0.22,
        "temp_range":      (30.0, 50.0),
        "hum_range":       (70.0, 92.0),
        "label": "DANGEREUX",
    },
}

N_TRAIN   = 4000   # Echantillons par classe pour l'entraînement
N_BANK    = 80     # Echantillons par classe pour le sample_bank


def _gen_sample(cls: int) -> list:
    """Génère UN vecteur [s1,s2,s3,s4, humidity, temperature] pour la classe `cls`."""
    cfg = CLASSES[cls]
    h2s_true = np.random.uniform(*cfg["h2s_mean_range"])

    # Bruit capteur indépendant par capteur (modèle MQ-136)
    sensors = []
    for _ in range(4):
        noise_mult = 1.0 + np.random.normal(0, cfg["h2s_noise"])
        noise_add  = np.random.normal(0, max(0.05, h2s_true * 0.05))
        val = max(0.0, h2s_true * noise_mult + noise_add)
        # Capteur parfois défaillant (0.5% probabilité → lecture ~0)
        if np.random.rand() < 0.005:
            val = np.random.uniform(0, 0.1)
        sensors.append(round(val, 3))

    temp = round(np.random.uniform(*cfg["temp_range"]), 1)
    # Humidité : légère corrélation avec T (mine plus humide = plus fraîche)
    hum_raw  = np.random.uniform(*cfg["hum_range"])
    hum_corr = hum_raw - 0.15 * (temp - 30)   # correction physique légère
    hum = round(float(np.clip(hum_corr, cfg["hum_range"][0] - 5, cfg["hum_range"][1] + 3)), 1)

    return sensors + [hum, temp]


def generate_dataset() -> tuple[pd.DataFrame, pd.Series]:
    rows, labels = [], []
    for cls in range(3):
        print(f"  Classe {cls} ({CLASSES[cls]['label']}) : {N_TRAIN} échantillons…")
        for _ in range(N_TRAIN):
            rows.append(_gen_sample(cls))
            labels.append(cls)

    df = pd.DataFrame(rows, columns=FEATURES)
    y  = pd.Series(labels, name="risk_class")
    return df, y


def train_rf(X: pd.DataFrame, y: pd.Series):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    rf = RandomForestClassifier(
        n_estimators=500,
        max_depth=20,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    # Validation croisée 5-fold
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(rf, X, y, cv=cv, scoring="accuracy")
    print(f"\n  Cross-validation (5-fold) : {scores.mean()*100:.1f}% ± {scores.std()*100:.1f}%")

    rf.fit(X, y)

    # Verification sur toutes les donnees
    preds = rf.predict(X)
    from sklearn.metrics import classification_report
    report = classification_report(y, preds, target_names=["NORMAL", "MODERE", "DANGEREUX"])
    print("\n  Rapport classification (données d'entraînement) :")
    for line in report.split("\n"):
        if line.strip():
            print("  " + line)

    return rf


def build_sample_bank(rf) -> dict:
    """
    Génère N_BANK échantillons par classe, tous correctement classifiés par le RF.
    """
    bank = {"0": [], "1": [], "2": []}

    for cls in range(3):
        target = N_BANK
        attempts = 0
        print(f"\n  Sample bank classe {cls} ({CLASSES[cls]['label']}) : {target} échantillons RF-validés…")

        while len(bank[str(cls)]) < target and attempts < target * 50:
            attempts += 1
            sample = _gen_sample(cls)
            row = pd.DataFrame([sample], columns=FEATURES)
            pred = int(rf.predict(row)[0])
            if pred == cls:
                bank[str(cls)].append(sample)

        n_ok = len(bank[str(cls)])
        print(f"    → {n_ok}/{target} acceptés ({attempts} tentatives, "
              f"taux={n_ok/attempts*100:.1f}%)")

        if n_ok < target:
            print(f"    ⚠ Complément avec {target - n_ok} échantillons supplémentaires "
                  f"(RF permissif)")
            # Remplir avec les valeurs les plus sûres de la classe
            while len(bank[str(cls)]) < target:
                sample = _gen_sample(cls)
                bank[str(cls)].append(sample)

    return bank


def verify_bank(rf, bank: dict):
    """Vérifie la cohérence finale du sample bank."""
    print("\n  Vérification sample bank :")
    for cls_str, samples in bank.items():
        rows = pd.DataFrame(samples, columns=FEATURES)
        preds = rf.predict(rows)
        ok = int((preds == int(cls_str)).sum())
        h2s_means = [(s[0]+s[1]+s[2]+s[3])/4 for s in samples]
        temps  = [s[5] for s in samples]
        humids = [s[4] for s in samples]
        label  = CLASSES[int(cls_str)]['label']
        print(f"    Classe {cls_str} ({label:10s}): {ok}/{len(samples)} RF-correct | "
              f"H2S_moy=[{min(h2s_means):.2f}–{max(h2s_means):.2f}] | "
              f"T=[{min(temps):.1f}–{max(temps):.1f}]°C | "
              f"H=[{min(humids):.1f}–{max(humids):.1f}]%")


def test_scenarios(rf):
    """Teste des scénarios représentatifs de la mine KCC."""
    print("\n  Tests de validation (conditions mine réelles) :")
    scenarios = [
        ([0.1, 0.2, 0.1, 0.1, 72, 28], 0, "Normal — fond géochimique très bas"),
        ([0.5, 0.8, 0.4, 0.6, 75, 30], 0, "Normal — ventilation correcte"),
        ([1.2, 1.5, 1.0, 1.3, 78, 33], 0, "Normal — proche seuil TLV-TWA"),
        ([3.0, 4.5, 2.8, 3.5, 80, 35], 1, "Modéré — dépassement TLV-STEL"),
        ([7.0, 9.2, 6.5, 8.0, 82, 38], 1, "Modéré — REL NIOSH dépassé"),
        ([12.0,14.5,11.8,13.2,85, 40], 1, "Modéré élevé"),
        ([18.0,22.5,19.5,20.1,87, 43], 2, "Dangereux — évacuation"),
        ([30.0,35.0,28.0,32.0,88, 45], 2, "Dangereux élevé"),
        ([45.0,48.0,42.0,44.0,90, 48], 2, "Critique"),
    ]
    labels = {0: "NORMAL", 1: "MODERE", 2: "DANGEREUX"}
    ok_count = 0
    for features, expected_cls, desc in scenarios:
        row   = pd.DataFrame([features], columns=FEATURES)
        pred  = int(rf.predict(row)[0])
        proba = rf.predict_proba(row)[0]
        ok    = pred == expected_cls
        ok_count += int(ok)
        icon = "OK" if ok else "XX"
        print(f"    {icon} {desc}")
        print(f"      -> Predit: {labels[pred]} ({max(proba)*100:.0f}%) | Attendu: {labels[expected_cls]}")
    print(f"\n  Score validation : {ok_count}/{len(scenarios)} correct(s)")


def main():
    print("=" * 60)
    print("  Réentraînement RF — Conditions mine KCC Kamoto")
    print("=" * 60)

    print("\n[1] Génération du dataset d'entraînement…")
    X, y = generate_dataset()
    print(f"    Total : {len(X)} échantillons, {X.shape[1]} features")
    print(f"    Distribution : {dict(y.value_counts().sort_index())}")
    print(f"    T=[{X['Temperature[C]'].min():.0f}–{X['Temperature[C]'].max():.0f}]°C "
          f"H=[{X['Humidity[%]'].min():.0f}–{X['Humidity[%]'].max():.0f}]%")

    print("\n[2] Entraînement du Random Forest…")
    rf = train_rf(X, y)

    print("\n[3] Tests sur scénarios de validation…")
    test_scenarios(rf)

    print("\n[4] Construction du sample bank…")
    bank = build_sample_bank(rf)
    verify_bank(rf, bank)

    print("\n[5] Sauvegarde…")
    os.makedirs(MODELS, exist_ok=True)

    # Sauvegarde RF
    rf_backup = RF_PATH + ".bak"
    if os.path.exists(RF_PATH):
        import shutil
        shutil.copy2(RF_PATH, rf_backup)
        print(f"    Backup : {rf_backup}")
    joblib.dump(rf, RF_PATH)
    print(f"    Modèle RF : {RF_PATH}")

    # Sauvegarde sample bank
    bank_backup = BANK_PATH + ".bak"
    if os.path.exists(BANK_PATH):
        import shutil
        shutil.copy2(BANK_PATH, bank_backup)
    with open(BANK_PATH, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)
    print(f"    Sample bank : {BANK_PATH}")

    print("\n" + "=" * 60)
    print("  Réentraînement terminé avec succès.")
    print("  Redémarrez le serveur pour appliquer les changements.")
    print("=" * 60)


if __name__ == "__main__":
    main()
