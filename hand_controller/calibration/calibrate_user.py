# hand_controller/calibration/calibrate_user.py
from __future__ import annotations
import os, json, time
from dataclasses import dataclass
from typing import List
import cv2
import numpy as np
import mediapipe as mp


from hand_controller.ml.geo18 import extract_geo18

@dataclass(frozen=True)
class CalibConfig:
    seconds: float = 5.0
    out_dir: str = "artifacts/user_profile"
    name: str = "default_user"

def run_user_calibration(cfg: CalibConfig) -> str:
    os.makedirs(cfg.out_dir, exist_ok=True)

    cap = cv2.VideoCapture(0)
    hands = mp.solutions.hands.Hands(max_num_hands=2, min_detection_confidence=0.7, min_tracking_confidence=0.7)

    feats: List[List[float]] = []
    started = False
    t0 = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = hands.process(rgb)

            msg = "Press SPACE to start user calibration (Idle/neutral hand), Q to quit"
            if started:
                rem = max(0.0, cfg.seconds - (time.time() - t0))
                msg = f"Calibrating... {rem:0.1f}s left (keep steady)"
                if res.multi_hand_landmarks:
                    # take the most prominent hand for calibration: index 0
                    f18 = extract_geo18(res.multi_hand_landmarks[0])
                    feats.append(f18)

                if rem <= 0.001 and len(feats) >= 20:
                    X = np.asarray(feats, dtype=np.float64)
                    mean = X.mean(axis=0)
                    std = X.std(axis=0)

                    profile = {
                        "name": cfg.name,
                        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "n_frames": int(X.shape[0]),
                        "mean": mean.tolist(),
                        "std": std.tolist(),
                        "max_zdist": 3.0
                    }
                    out_path = os.path.join(cfg.out_dir, f"{cfg.name}_profile.json")
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(profile, f, indent=2)

                    cv2.putText(frame, "ACCEPTED ✅", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,0), 2)
                    cv2.imshow("User Calibration", frame)
                    cv2.waitKey(400)
                    return out_path

            cv2.putText(frame, msg, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200,200,200), 2)
            cv2.imshow("User Calibration", frame)
            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), ord("Q")):
                raise SystemExit("Quit")
            if (not started) and k == 32:
                started = True
                t0 = time.time()
                feats = []

    finally:
        cap.release()
        hands.close()
        cv2.destroyAllWindows()
