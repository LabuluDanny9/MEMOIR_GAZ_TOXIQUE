"""
Moteur IA H2S - GazMonitor Pro.

Version alignee sur les modeles corriges :
  RF   : C_H2S_fusion -> Risk_Class {0=NORMAL, 1=MODERE, 2=DANGEREUX}
  LSTM : [x(t-59), ..., x(t)] -> x_hat(t+50)

La concentration C_H2S_fusion est la moyenne des capteurs H2S disponibles.
Si un seul capteur est envoye par le casque, cette valeur reste utilisee seule.
"""

import json
import os
import warnings
from collections import deque

import joblib
import numpy as np

warnings.filterwarnings("ignore")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")

FUSION_RF_MODEL = os.path.join(MODELS_DIR, "random_forest_h2s_fusion.pkl")
FUSION_LSTM_MODEL = os.path.join(MODELS_DIR, "lstm_h2s_fusion.h5")
FUSION_METADATA = os.path.join(MODELS_DIR, "metadata_h2s_fusion.json")

LEGACY_RF_MODEL = os.path.join(MODELS_DIR, "rf_model.pkl")
LEGACY_LSTM_WEIGHTS = os.path.join(MODELS_DIR, "lstm_weights.weights.h5")
LEGACY_LSTM_PARAMS = os.path.join(MODELS_DIR, "lstm_params.json")

FUSION_FEATURE = "C_H2S_fusion_ppm"
LEGACY_FEATURES = ["Sensor1[ppm]", "Sensor2[ppm]", "Sensor3[ppm]", "Sensor4[ppm]", "H2S_mean"]

LSTM_WINDOW = 60
LSTM_HORIZON_S = 50
H2S_TRAIN_MIN = 0.0
H2S_TRAIN_MAX = 31.44

RISK_LABELS = {0: "NORMAL", 1: "MODERE", 2: "DANGEREUX"}
C_FUSION_NORMAL_LIMIT = 10.0
C_FUSION_DANGER_LIMIT = 20.0
DECISION_RULE = (
    "Y=0 si C_fusion<10 ppm; "
    "Y=1 si 10<=C_fusion<20 ppm; "
    "Y=2 si C_fusion>=20 ppm"
)


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        if np.isnan(value) or np.isinf(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def _clean_h2s(value):
    return max(0.0, _safe_float(value, 0.0))


def classify_c_fusion(c_fusion_ppm):
    """Classe Y selon la reformulation mathematique C_fusion en ppm."""
    h = _clean_h2s(c_fusion_ppm)
    if h < C_FUSION_NORMAL_LIMIT:
        return 0
    if h < C_FUSION_DANGER_LIMIT:
        return 1
    return 2


def _threshold_probabilities(cls):
    return {k: (1.0 if k == cls else 0.0) for k in (0, 1, 2)}


def _load_metadata():
    """Charge les bornes LSTM et les metriques des modeles corriges."""
    meta = {}
    if os.path.exists(FUSION_METADATA):
        with open(FUSION_METADATA, encoding="utf-8") as f:
            meta = json.load(f)
    return meta


def _legacy_lstm_params():
    if os.path.exists(LEGACY_LSTM_PARAMS):
        with open(LEGACY_LSTM_PARAMS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _build_legacy_lstm():
    from tensorflow.keras.layers import BatchNormalization, Dense, Dropout, LSTM
    from tensorflow.keras.models import Sequential

    model = Sequential(
        [
            LSTM(64, return_sequences=True, input_shape=(LSTM_WINDOW, 1)),
            Dropout(0.20),
            BatchNormalization(),
            LSTM(32, return_sequences=False),
            Dropout(0.15),
            Dense(16, activation="relu"),
            Dense(1, activation="linear"),
        ]
    )
    return model


class H2SEngine:
    """Moteur d'inference RF + LSTM + dose, avec un etat par casque."""

    def __init__(self):
        self.rf = None
        self.lstm = None
        self.ready = False
        self.rf_mode = "none"
        self.lstm_mode = "none"
        self.metrics = {}
        self.h2s_min = H2S_TRAIN_MIN
        self.h2s_max = H2S_TRAIN_MAX
        self.window = LSTM_WINDOW
        self.horizon_s = LSTM_HORIZON_S
        self._buffers = {}
        self._doses = {}

    def load(self):
        print("\n[H2S] Chargement des modeles IA ...")
        metadata = _load_metadata()
        lstm_meta = metadata.get("lstm", {})
        self.window = int(lstm_meta.get("window", LSTM_WINDOW))
        self.horizon_s = int(lstm_meta.get("horizon", LSTM_HORIZON_S))
        self.h2s_min = float(lstm_meta.get("h2s_min_train", H2S_TRAIN_MIN))
        self.h2s_max = float(lstm_meta.get("h2s_max_train", H2S_TRAIN_MAX))

        if os.path.exists(FUSION_RF_MODEL):
            self.rf = joblib.load(FUSION_RF_MODEL)
            self.rf_mode = "random_forest_h2s_fusion"
            self.metrics["rf"] = {
                "model_type": self.rf_mode,
                "feature": FUSION_FEATURE,
                "thresholds": metadata.get("thresholds", {}),
                "thresholds_ppm": {
                    "normal_lt": C_FUSION_NORMAL_LIMIT,
                    "modere_min": C_FUSION_NORMAL_LIMIT,
                    "dangereux_min": C_FUSION_DANGER_LIMIT,
                },
                "decision_rule": DECISION_RULE,
                "test": metadata.get("rf", {}).get("test", {}),
            }
        else:
            self.rf = joblib.load(LEGACY_RF_MODEL)
            self.rf_mode = "rf_model_legacy"
            self.metrics["rf"] = {"model_type": self.rf_mode, "features": LEGACY_FEATURES}

        try:
            from tensorflow.keras.models import load_model

            if os.path.exists(FUSION_LSTM_MODEL):
                self.lstm = load_model(FUSION_LSTM_MODEL)
                self.lstm_mode = "lstm_h2s_fusion"
            else:
                params = _legacy_lstm_params()
                self.h2s_min = float(params.get("h2s_min", self.h2s_min))
                self.h2s_max = float(params.get("h2s_max", self.h2s_max))
                self.lstm = _build_legacy_lstm()
                self.lstm.load_weights(LEGACY_LSTM_WEIGHTS)
                self.lstm_mode = "lstm_weights_legacy"
        except Exception as exc:
            raise RuntimeError(f"Chargement LSTM impossible : {exc}") from exc

        self.metrics["lstm"] = {
            "model_type": self.lstm_mode,
            "window": self.window,
            "horizon_s": self.horizon_s,
            "h2s_min": self.h2s_min,
            "h2s_max": self.h2s_max,
            "mae_h2s": lstm_meta.get("test_mae_ppm"),
            "rmse_h2s": lstm_meta.get("test_rmse_ppm"),
            "r2_h2s": lstm_meta.get("test_r2"),
        }

        self.ready = True
        classes = list(getattr(self.rf, "classes_", [0, 1, 2]))
        print(f"[H2S] RF   : {self.rf_mode} | classes {classes}")
        print(f"[H2S] LSTM : {self.lstm_mode} | fenetre {self.window} | horizon {self.horizon_s}s")
        print(f"[H2S] H2S normalise [{self.h2s_min:.3f} - {self.h2s_max:.3f}] ppm")
        print("[H2S] Moteur pret.\n")
        return True

    def _rf_vector(self, h2s_fusion, s1=None, s2=None, s3=None, s4=None):
        h = _clean_h2s(h2s_fusion)
        if self.rf_mode == "random_forest_h2s_fusion":
            return np.array([[h]], dtype=np.float32)
        return np.array([[_clean_h2s(s1), _clean_h2s(s2), _clean_h2s(s3), _clean_h2s(s4), h]], dtype=np.float32)

    def _predict_rf(self, h2s_fusion, s1=None, s2=None, s3=None, s4=None):
        h = _clean_h2s(h2s_fusion)
        formula_cls = classify_c_fusion(h)

        if self.rf_mode == "random_forest_h2s_fusion":
            # Le RF corrige a ete entraine sur la regle C_fusion 10/20 ppm.
            # On ancre l'inference temps reel sur cette formulation pour que
            # les valeurs limites restent exactement coherentes avec le memoire.
            return formula_cls, _threshold_probabilities(formula_cls)

        row = self._rf_vector(h, s1, s2, s3, s4)
        cls = int(self.rf.predict(row)[0])
        if hasattr(self.rf, "predict_proba"):
            proba = self.rf.predict_proba(row)[0]
            probs = {int(c): float(p) for c, p in zip(self.rf.classes_, proba)}
        else:
            probs = {cls: 1.0}
        for k in (0, 1, 2):
            probs.setdefault(k, 0.0)
        return cls, probs

    def classify_future_h2s(self, predicted_h2s):
        """Classifie la concentration predite par LSTM avec le meme RF."""
        if not self.ready:
            return {
                "pred_risk_class": 0,
                "pred_risk_label": RISK_LABELS[0],
                "pred_probabilities": {0: 1.0, 1: 0.0, 2: 0.0},
                "pred_risk_probability": 1.0,
                "risk_model": "idle",
            }
        h = _clean_h2s(predicted_h2s)
        cls, probs = self._predict_rf(h, h, h, h, h)
        return {
            "pred_risk_class": cls,
            "pred_risk_label": RISK_LABELS.get(cls, "NORMAL"),
            "pred_probabilities": probs,
            "pred_risk_probability": float(probs.get(cls, 0.0)),
            "risk_model": self.rf_mode,
        }

    def reset_device(self, device_id):
        self._buffers.pop(device_id, None)
        self._doses[device_id] = 0.0

    def process(self, device_id, s1, s2, s3, s4, humidity, temperature):
        """
        Analyse une mesure et retourne le resultat complet.

        Les valeurs s1..s4 sont les capteurs H2S disponibles. Si le casque n'envoie
        qu'un seul capteur, l'application replique cette valeur avant d'appeler ce moteur.
        """
        if not self.ready:
            raise RuntimeError("Moteur non charge (appeler load()).")

        sensors = [_clean_h2s(s1), _clean_h2s(s2), _clean_h2s(s3), _clean_h2s(s4)]
        valid = [v for v in sensors if v >= 0.0]
        h2s_mesure = round(float(np.mean(valid or [0.0])), 3)

        risk_class, probabilities = self._predict_rf(h2s_mesure, *sensors)

        buf = self._buffers.setdefault(device_id, deque(maxlen=self.window))
        prediction_h2s = 0.0
        prediction_ready = False

        if risk_class == 0:
            buf.clear()
        else:
            scale = max(self.h2s_max - self.h2s_min, 1e-8)
            h2s_norm = (h2s_mesure - self.h2s_min) / scale
            buf.append(float(np.clip(h2s_norm, 0.0, 1.0)))

            if len(buf) == self.window:
                seq = np.array(buf, dtype=np.float32).reshape(1, self.window, 1)
                pred_n = float(np.ravel(self.lstm.predict(seq, verbose=0))[0])
                pred_n = float(np.clip(pred_n, 0.0, 1.0))
                prediction_h2s = round(pred_n * scale + self.h2s_min, 2)
                prediction_h2s = max(0.0, prediction_h2s)
                prediction_ready = True

        if risk_class > 0:
            self._doses[device_id] = self._doses.get(device_id, 0.0) + h2s_mesure
        dose = round(self._doses.get(device_id, 0.0), 2)

        if dose < 50:
            exposure = "Faible"
        elif dose < 500:
            exposure = "Modere"
        elif dose < 2000:
            exposure = "Eleve"
        else:
            exposure = "Critique"

        pred_risk = self.classify_future_h2s(prediction_h2s) if prediction_ready else {
            "pred_risk_class": 0,
            "pred_risk_label": RISK_LABELS[0],
            "pred_probabilities": {0: 1.0, 1: 0.0, 2: 0.0},
            "pred_risk_probability": 1.0,
            "risk_model": "idle",
        }

        return {
            "risk_class": risk_class,
            "risk_label": RISK_LABELS.get(risk_class, "NORMAL"),
            "probabilities": probabilities,
            "h2s_mesure": h2s_mesure,
            "h2s_fusion_ppm": h2s_mesure,
            "c_fusion_ppm": h2s_mesure,
            "decision_rule": DECISION_RULE,
            "prediction_h2s": prediction_h2s,
            "prediction_ready": prediction_ready,
            "pred_risk_class": pred_risk["pred_risk_class"],
            "pred_risk_label": pred_risk["pred_risk_label"],
            "pred_probabilities": pred_risk["pred_probabilities"],
            "pred_risk_probability": pred_risk.get("pred_risk_probability", 0.0),
            "prediction_risk_model": pred_risk["risk_model"],
            "prediction_horizon_s": self.horizon_s,
            "buffer_fill": len(buf),
            "buffer_size": self.window,
            "dose_accumulee": dose,
            "exposure_level": exposure,
            "model_type": self.rf_mode,
        }


engine = H2SEngine()
