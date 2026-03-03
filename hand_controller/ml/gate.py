# hand_controller/ml/gate.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GatePolicy:
    min_p1: float = 0.70
    min_margin: float = 0.20

def accept(pred_label: str, expected_label: str | None, p1: float, margin: float, policy: GatePolicy) -> bool:
    if expected_label is not None and pred_label != expected_label:
        return False
    return (p1 >= policy.min_p1) and (margin >= policy.min_margin)
