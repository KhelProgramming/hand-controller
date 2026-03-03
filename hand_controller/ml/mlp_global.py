from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
import joblib
import os

def _top1_margin(probs: np.ndarray) -> Tuple[int, float, float]:
    order = np.argsort(probs)[::-1]
    top = int(order[0])
    p1 = float(probs[top])
    p2 = float(probs[order[1]]) if len(order) > 1 else 0.0
    return top, p1, (p1 - p2)

@dataclass(frozen=True)
class MLPResult:
    label: str
    p1: float
    margin: float
    probs: np.ndarray

class GlobalMLP:
    def _init_(self, scaler_path: str, label_encoder_path: str, mlp_path: str):
        for p in (scaler_path, label_encoder_path, mlp_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"Missing artifacts: {p}")
        self.scaler = joblib.load(scaler_path)
        self.le = joblib.load(label_encoder_path)
        self.mlp = joblib.load(mlp_path)
        
    def predict(self, f18: List[float]) -> MLPResult:
        Xs = self.scaler.transform([f18])
        probs = self.mlp.predict_proba(Xs)[0]
        top, p1, margin = _top1_margin(probs)
        label = self.le.inverse_transform([top])[0]
        return MLPResult(label=label, p1=p1, margin=margin, probs=probs)

