"""
Entraînement RF + LSTM sur le dataset réel DATASET01.csv
Mine KCC Kamoto — Surveillance H2S uniquement (4 capteurs)

Usage : python train_from_real_data.py
"""
import os, sys, json, warnings, shutil
import numpy as np
import pandas as pd
import joblib
warnings.filterwarnings("ignore")

ROOT      = os.path.dirname(os.path.abspath(__file__))
MODELS    = os.path.join(ROOT, "models")
DATASET   = r"D:\TFC_2026 (2)\Mr. RUPHIN\final\SYSTEME SMART\2024-393-1\2024-393-1\data\DATASET01.csv"

# ── Features H2S uniquement (pas T, pas H) ───────────────────────
RF_FEATURES   = ["Sensor1[ppm]", "Sensor2[ppm]", "Sensor3[ppm]", "Sensor4[ppm]"]
LSTM_WINDOW   = 60          # 60 secondes de contexte temporel
LSTM_FEATURES = ["H2S_mean"] # prediction sur moyenne H2S
N_BANK        = 80          # echantillons par classe dans sample_bank

RISK_LABELS  = {0: "NORMAL", 1: "MODERE", 2: "DANGEREUX"}

np.random.seed(42)

# ================================================================
# 1. CHARGEMENT ET PREPARATION DES DONNEES
# ================================================================
def load_data():
    print("[DATA] Chargement DATASET01.csv ...")
    df = pd.read_csv(DATASET, on_bad_lines='skip')

    # Valeurs aberrantes (Sensor4 peut avoir valeurs negatives)
    for c in RF_FEATURES:
        df[c] = df[c].clip(lower=0)

    # Feature H2S_mean = moyenne des 4 capteurs
    df["H2S_mean"] = df[RF_FEATURES].mean(axis=1).round(4)

    print(f"  Lignes : {len(df):,}  |  Colonnes : {list(df.columns)}")
    print(f"  Labels : {dict(df['Labels'].value_counts().sort_index())}")
    return df


# ================================================================
# 2. RANDOM FOREST — classification (classes 0/1/2)
# ================================================================
def train_rf(df: pd.DataFrame):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import StratifiedShuffleSplit
    from sklearn.metrics import (classification_report, confusion_matrix,
                                  accuracy_score, roc_auc_score)

    print("\n[RF] Preparation du jeu d'entrainement ...")
    X = df[RF_FEATURES].values
    y = df["Labels"].values

    # Sous-echantillonnage stratifie pour equilibrer les classes
    # 150 000 par classe (450 000 total — dataset equilibre)
    N_PER_CLASS = 120_000
    idx_list = []
    for cls in [0, 1, 2]:
        idx_cls = np.where(y == cls)[0]
        chosen  = np.random.choice(idx_cls, min(N_PER_CLASS, len(idx_cls)), replace=False)
        idx_list.append(chosen)
    idx_balanced = np.concatenate(idx_list)
    np.random.shuffle(idx_balanced)

    X_bal = X[idx_balanced]
    y_bal = y[idx_balanced]
    print(f"  Dataset equilibre : {len(X_bal):,} echantillons | classes : {dict(zip(*np.unique(y_bal, return_counts=True)))}")

    # Split 80/20 stratifie
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.20, random_state=42)
    tr_idx, te_idx = next(sss.split(X_bal, y_bal))
    X_train, X_test = X_bal[tr_idx], X_bal[te_idx]
    y_train, y_test = y_bal[tr_idx], y_bal[te_idx]
    print(f"  Train : {len(X_train):,}  |  Test : {len(X_test):,}")

    print("[RF] Entrainement Random Forest (500 arbres) ...")
    rf = RandomForestClassifier(
        n_estimators   = 500,
        max_depth       = 25,
        min_samples_leaf= 2,
        class_weight    = "balanced",
        random_state    = 42,
        n_jobs          = -1,
    )
    rf.fit(X_train, y_train)

    # Evaluation
    y_pred = rf.predict(X_test)
    acc    = accuracy_score(y_test, y_pred)
    print(f"\n  Accuracy test : {acc*100:.2f}%")
    print("\n  Rapport de classification :")
    print(classification_report(y_test, y_pred,
                                target_names=["NORMAL","MODERE","DANGEREUX"]))

    # AUC multiclasse
    y_proba = rf.predict_proba(X_test)
    auc = roc_auc_score(y_test, y_proba, multi_class='ovr', average='macro')
    print(f"  AUC-ROC macro (One-vs-Rest) : {auc:.4f}")

    # Importance des features
    print("\n  Importance des features (H2S uniquement) :")
    for f, imp in sorted(zip(RF_FEATURES, rf.feature_importances_), key=lambda x: -x[1]):
        bar = "=" * int(imp * 40)
        print(f"    {f:18s} {imp:.4f}  [{bar}]")

    return rf, X_test, y_test, y_pred, y_proba


# ================================================================
# 3. LSTM — prediction de la concentration H2S future
# ================================================================
def train_lstm(df: pd.DataFrame):
    import tensorflow as tf
    tf.get_logger().setLevel("ERROR")
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

    print("\n[LSTM] Construction des sequences temporelles ...")
    series = df["H2S_mean"].values.astype(np.float32)

    # Normalisation Min-Max sur H2S_mean
    h2s_min, h2s_max = series.min(), series.max()
    series_norm = (series - h2s_min) / (h2s_max - h2s_min + 1e-8)

    # Sauvegarde des parametres de normalisation
    scaler_params = {"h2s_min": float(h2s_min), "h2s_max": float(h2s_max)}

    # Construction sequences : X=(t-60..t-1), y=t (prochaine seconde)
    # Sous-echantillonnage : 80 000 sequences pour acceleration
    print(f"  Serie H2S normalisee : min={h2s_min:.3f} max={h2s_max:.3f}")

    step = max(1, (len(series_norm) - LSTM_WINDOW) // 80_000)
    Xs, ys = [], []
    for i in range(0, len(series_norm) - LSTM_WINDOW - 1, step):
        Xs.append(series_norm[i : i + LSTM_WINDOW])
        ys.append(series_norm[i + LSTM_WINDOW])

    X_seq = np.array(Xs, dtype=np.float32).reshape(-1, LSTM_WINDOW, 1)
    y_seq = np.array(ys, dtype=np.float32)
    print(f"  Sequences : {len(X_seq):,}  shape={X_seq.shape}")

    # Split 80/20
    n_train = int(len(X_seq) * 0.80)
    X_tr, X_te = X_seq[:n_train], X_seq[n_train:]
    y_tr, y_te = y_seq[:n_train], y_seq[n_train:]

    # Architecture LSTM
    print("[LSTM] Construction du modele ...")
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(LSTM_WINDOW, 1)),
        Dropout(0.20),
        BatchNormalization(),
        LSTM(32, return_sequences=False),
        Dropout(0.15),
        Dense(16, activation="relu"),
        Dense(1, activation="linear"),   # Regression H2S
    ])
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])
    model.summary()

    callbacks = [
        EarlyStopping(patience=5, restore_best_weights=True, verbose=1),
        ReduceLROnPlateau(patience=3, factor=0.5, verbose=0),
    ]

    print("[LSTM] Entrainement ...")
    history = model.fit(
        X_tr, y_tr,
        validation_data=(X_te, y_te),
        epochs=40,
        batch_size=512,
        callbacks=callbacks,
        verbose=1,
    )

    # Evaluation
    y_pred_norm = model.predict(X_te, verbose=0).flatten()
    # Denormalisation
    y_pred_real = y_pred_norm * (h2s_max - h2s_min) + h2s_min
    y_test_real = y_te        * (h2s_max - h2s_min) + h2s_min

    mae  = np.mean(np.abs(y_pred_real - y_test_real))
    rmse = np.sqrt(np.mean((y_pred_real - y_test_real) ** 2))
    r2   = 1 - np.sum((y_test_real - y_pred_real)**2) / np.sum((y_test_real - y_test_real.mean())**2)
    print(f"\n  MAE  : {mae:.4f} ppm")
    print(f"  RMSE : {rmse:.4f} ppm")
    print(f"  R²   : {r2:.4f}")

    return model, history, scaler_params, y_test_real, y_pred_real


# ================================================================
# 4. SAMPLE BANK — echantillons representatifs par classe
# ================================================================
def build_sample_bank(df: pd.DataFrame, rf) -> dict:
    print("\n[BANK] Construction du sample bank ...")
    bank = {"0": [], "1": [], "2": []}

    for cls in [0, 1, 2]:
        sub = df[df["Labels"] == cls]
        # Echantillons aleatoires valides RF
        candidates = sub.sample(min(N_BANK * 10, len(sub)), random_state=42)
        for _, row in candidates.iterrows():
            if len(bank[str(cls)]) >= N_BANK:
                break
            feat = [row[f] for f in RF_FEATURES]
            X_r  = pd.DataFrame([feat], columns=RF_FEATURES)
            pred = int(rf.predict(X_r)[0])
            if pred == cls:
                # Stocker [S1, S2, S3, S4, Humidity, Temperature]
                # (on garde H/T dans le bank pour le format existant du dashboard)
                bank[str(cls)].append([
                    round(row["Sensor1[ppm]"], 3),
                    round(row["Sensor2[ppm]"], 3),
                    round(row["Sensor3[ppm]"], 3),
                    round(row["Sensor4[ppm]"], 3),
                    round(float(row.get("Humidity[%]", 45.0)), 1),
                    round(float(row.get("Temperature[C]", 23.0)), 1),
                ])

        # Complement si manquant
        while len(bank[str(cls)]) < N_BANK:
            row = sub.sample(1, random_state=len(bank[str(cls)])).iloc[0]
            bank[str(cls)].append([
                round(row["Sensor1[ppm]"], 3), round(row["Sensor2[ppm]"], 3),
                round(row["Sensor3[ppm]"], 3), round(row["Sensor4[ppm]"], 3),
                round(float(row.get("Humidity[%]", 45.0)), 1),
                round(float(row.get("Temperature[C]", 23.0)), 1),
            ])

        h2s_m = [(b[0]+b[1]+b[2]+b[3])/4 for b in bank[str(cls)]]
        print(f"  Classe {cls}: {len(bank[str(cls)])} echantillons | "
              f"H2S_moy=[{min(h2s_m):.2f}-{max(h2s_m):.2f}] ppm")

    return bank


# ================================================================
# 5. SAUVEGARDE DES MODELES
# ================================================================
def save_models(rf, lstm_model, scaler_params, bank):
    os.makedirs(MODELS, exist_ok=True)

    # Backup
    for fname in ["rf_model.pkl", "lstm_weights.weights.h5",
                  "scaler_x.pkl", "scaler_y.pkl", "sample_bank.json"]:
        src = os.path.join(MODELS, fname)
        if os.path.exists(src):
            shutil.copy2(src, src + ".bak")

    # RF
    rf_path = os.path.join(MODELS, "rf_model.pkl")
    joblib.dump(rf, rf_path)
    print(f"[SAVE] RF : {rf_path}")

    # LSTM weights
    lstm_path = os.path.join(MODELS, "lstm_weights.weights.h5")
    lstm_model.save_weights(lstm_path)
    print(f"[SAVE] LSTM weights : {lstm_path}")

    # Scalers (compatibilite serveur) : on stocke min/max H2S dans scaler_y
    from sklearn.preprocessing import MinMaxScaler
    sc_y = MinMaxScaler()
    sc_y.fit(np.array([[scaler_params["h2s_min"]], [scaler_params["h2s_max"]]]))
    joblib.dump(sc_y, os.path.join(MODELS, "scaler_y.pkl"))

    sc_x = MinMaxScaler()
    sc_x.fit(np.zeros((2, 6)))  # dummy pour compatibilite
    joblib.dump(sc_x, os.path.join(MODELS, "scaler_x.pkl"))
    print(f"[SAVE] Scalers sauvegardes")

    # Sauvegarde parametres LSTM
    with open(os.path.join(MODELS, "lstm_params.json"), "w") as f:
        json.dump({
            "h2s_min": scaler_params["h2s_min"],
            "h2s_max": scaler_params["h2s_max"],
            "window": LSTM_WINDOW,
            "features": LSTM_FEATURES,
        }, f, indent=2)

    # Sample bank
    bank_path = os.path.join(MODELS, "sample_bank.json")
    with open(bank_path, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] Sample bank : {bank_path}")

    print("\n[SAVE] Tous les modeles sauvegardes.")


# ================================================================
# 6. MISE A JOUR h2s_engine.py
# ================================================================
def update_engine():
    engine_path = os.path.join(ROOT, "server", "h2s_engine.py")
    with open(engine_path, "r", encoding="utf-8") as f:
        code = f.read()

    new_features = '["Sensor1[ppm]", "Sensor2[ppm]", "Sensor3[ppm]", "Sensor4[ppm]"]'
    old_features = '["Sensor1[ppm]", "Sensor2[ppm]", "Sensor3[ppm]", "Sensor4[ppm]", "Humidity[%]", "Temperature[C]"]'

    if old_features in code:
        code = code.replace(old_features, new_features)
        with open(engine_path, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"[ENGINE] Features mises a jour : {engine_path}")
    else:
        print(f"[ENGINE] features deja a jour ou format different")


# ================================================================
# 7. MAIN
# ================================================================
def main():
    print("=" * 65)
    print("  Entraînement RF + LSTM — Dataset réel KCC H2S")
    print("=" * 65)

    # 1. Chargement
    df = load_data()

    # 2. RF
    rf, X_test, y_test, y_pred, y_proba = train_rf(df)

    # 3. LSTM
    lstm_model, history, scaler_params, y_test_real, y_pred_real = train_lstm(df)

    # 4. Sample bank
    bank = build_sample_bank(df, rf)

    # 5. Sauvegarde
    save_models(rf, lstm_model, scaler_params, bank)

    # 6. Mise a jour moteur
    update_engine()

    print("\n" + "=" * 65)
    print("  Entrainement termine. Redemarrez run_server.py")
    print("=" * 65)

    # Retourner les resultats pour le notebook
    return df, rf, lstm_model, history, X_test, y_test, y_pred, y_proba, y_test_real, y_pred_real, scaler_params


if __name__ == "__main__":
    main()
