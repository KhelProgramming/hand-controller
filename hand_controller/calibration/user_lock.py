#hand_controller/calibration/user_lock.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
import numpy as np

@dataclass(frozen=True)
class UserProfile:
    mean: np.ndarray #(18,) mean of the 
    std: np.ndarray #(18,) to normalize the dsitance
    max_zdist: float = 3.0 # threshold to accept a hand as "the user"
    
def _zdist(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> float:
    std2 = np.maximum(std, 1e-6)
    z = (x - mean) / std2
    return float(np.linalg.norm(z))

class UserHandLocker:
    def __init__(self, profile: UserProfile):
        self.profile = profile
        
    def pick_index(self, features_list: List[List[float]]) -> Optional[int]:
        if not features_list:
            return None
        best_i = None
        best_d = 1e18
        
        for i, f in enumerate(features_list):
            x = np.asarray(f, dtype=np.float64)
            d = _zdist(x, self.profile.mean, self.profile.std)
            if d < best_d:
                best_d = d
                best_i = i
        
        if best_i is None:
            return None
        return best_i if best_d <= self.profile.max_zdist else None
    
