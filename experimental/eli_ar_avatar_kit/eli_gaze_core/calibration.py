from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np


@dataclass
class CalibrationResult:
    path: Path
    screen_width: int
    screen_height: int
    degree: int
    mean_error_px: float
    median_error_px: float
    p90_error_px: float
    samples: int
    points: int


def polynomial_features(X: np.ndarray, degree: int = 2) -> np.ndarray:
    """Simple polynomial expansion with bias term, no sklearn dependency."""
    X = np.asarray(X, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    cols = [np.ones((X.shape[0], 1), dtype=np.float64), X]
    if degree >= 2:
        quad = []
        for i in range(X.shape[1]):
            for j in range(i, X.shape[1]):
                quad.append((X[:, i] * X[:, j]).reshape(-1, 1))
        cols.extend(quad)
    if degree >= 3:
        cubic = []
        for i in range(X.shape[1]):
            cubic.append((X[:, i] ** 3).reshape(-1, 1))
        cols.extend(cubic)
    return np.hstack(cols)


def ridge_fit(Phi: np.ndarray, Y: np.ndarray, lam: float = 1e-3) -> np.ndarray:
    I = np.eye(Phi.shape[1], dtype=np.float64)
    I[0, 0] = 0.0  # do not penalize bias
    return np.linalg.solve(Phi.T @ Phi + lam * I, Phi.T @ Y)


def robust_point_filter(features: np.ndarray, targets: np.ndarray, point_ids: np.ndarray, z: float = 2.5):
    keep = np.ones(len(features), dtype=bool)
    for pid in np.unique(point_ids):
        idx = np.where(point_ids == pid)[0]
        if len(idx) < 8:
            continue
        F = features[idx]
        med = np.median(F, axis=0)
        mad = np.median(np.abs(F - med), axis=0) + 1e-9
        score = np.mean(np.abs((F - med) / mad), axis=1)
        thr = np.median(score) + z * (np.median(np.abs(score - np.median(score))) + 1e-9)
        keep[idx] = score <= max(thr, 8.0)
    return features[keep], targets[keep], point_ids[keep]


def fit_calibration(
    samples: List[dict],
    screen_width: int,
    screen_height: int,
    path: Path,
    degree: int = 2,
    ridge: float = 2e-3,
    output_gain: float = 1.0,
) -> CalibrationResult:
    if len(samples) < 30:
        raise ValueError("Not enough calibration samples. Need at least 30 stable face/eye samples.")
    X = np.array([s["features"] for s in samples], dtype=np.float64)
    target_px = np.array([[s["target_x"], s["target_y"]] for s in samples], dtype=np.float64)
    point_ids = np.array([s.get("point_id", 0) for s in samples], dtype=np.int64)

    X, target_px, point_ids = robust_point_filter(X, target_px, point_ids)
    if len(X) < 30:
        raise ValueError("Too many noisy samples rejected. Improve lighting, face webcam directly, and retry.")

    # Standardize feature space. This is the key fix for tiny compressed output movement.
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-6
    Xn = (X - mean) / std

    # Targets are normalized to [-1, 1] so the solver learns full screen extent.
    Yn = np.column_stack([
        (target_px[:, 0] / max(screen_width - 1, 1)) * 2.0 - 1.0,
        (target_px[:, 1] / max(screen_height - 1, 1)) * 2.0 - 1.0,
    ])

    Phi = polynomial_features(Xn, degree=degree)
    coef = ridge_fit(Phi, Yn, lam=ridge)

    pred = Phi @ coef
    pred_px = np.column_stack([
        (pred[:, 0] + 1.0) * 0.5 * (screen_width - 1),
        (pred[:, 1] + 1.0) * 0.5 * (screen_height - 1),
    ])
    err = np.linalg.norm(pred_px - target_px, axis=1)

    model = {
        "version": 2,
        "created_ts": time.time(),
        "screen_width": int(screen_width),
        "screen_height": int(screen_height),
        "degree": int(degree),
        "ridge": float(ridge),
        "output_gain": float(output_gain),
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "coef": coef.tolist(),
        "feature_count": int(X.shape[1]),
        "poly_count": int(Phi.shape[1]),
        "samples": int(len(X)),
        "points": int(len(np.unique(point_ids))),
        "quality": {
            "mean_error_px": float(np.mean(err)),
            "median_error_px": float(np.median(err)),
            "p90_error_px": float(np.percentile(err, 90)),
            "max_error_px": float(np.max(err)),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    return CalibrationResult(
        path=path,
        screen_width=screen_width,
        screen_height=screen_height,
        degree=degree,
        mean_error_px=float(np.mean(err)),
        median_error_px=float(np.median(err)),
        p90_error_px=float(np.percentile(err, 90)),
        samples=int(len(X)),
        points=int(len(np.unique(point_ids))),
    )


class GazeMapper:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.data = data
        self.screen_width = int(data["screen_width"])
        self.screen_height = int(data["screen_height"])
        self.degree = int(data.get("degree", 2))
        self.output_gain = float(data.get("output_gain", 1.0))
        self.mean = np.array(data["feature_mean"], dtype=np.float64)
        self.std = np.array(data["feature_std"], dtype=np.float64)
        self.coef = np.array(data["coef"], dtype=np.float64)
        self.centre = np.array([self.screen_width * 0.5, self.screen_height * 0.5], dtype=np.float64)

    def predict(self, features: np.ndarray, gain: float | None = None, clamp: bool = True) -> Tuple[float, float]:
        f = np.asarray(features, dtype=np.float64)
        if f.shape[0] != self.mean.shape[0]:
            # Permit old fallback vectors by padding/truncating.
            fixed = np.zeros_like(self.mean)
            n = min(len(f), len(fixed))
            fixed[:n] = f[:n]
            f = fixed
        Xn = ((f - self.mean) / self.std).reshape(1, -1)
        Phi = polynomial_features(Xn, self.degree)
        y = Phi @ self.coef
        x = (float(y[0, 0]) + 1.0) * 0.5 * (self.screen_width - 1)
        yy = (float(y[0, 1]) + 1.0) * 0.5 * (self.screen_height - 1)
        g = self.output_gain if gain is None else gain
        if g != 1.0:
            p = np.array([x, yy], dtype=np.float64)
            p = self.centre + (p - self.centre) * float(g)
            x, yy = float(p[0]), float(p[1])
        if clamp:
            margin = 2
            x = max(margin, min(self.screen_width - margin, x))
            yy = max(margin, min(self.screen_height - margin, yy))
        return x, yy


class OneEuroLikeFilter:
    """Velocity-aware exponential smoother. Reduces jitter without freezing the avatar."""

    def __init__(self, alpha_slow: float = 0.18, alpha_fast: float = 0.55, velocity_scale: float = 900.0):
        self.alpha_slow = alpha_slow
        self.alpha_fast = alpha_fast
        self.velocity_scale = velocity_scale
        self.last = None
        self.last_t = None

    def update(self, x: float, y: float, confidence: float = 1.0):
        now = time.time()
        p = np.array([x, y], dtype=np.float64)
        if self.last is None:
            self.last = p
            self.last_t = now
            return float(p[0]), float(p[1])
        dt = max(now - self.last_t, 1e-3)
        v = float(np.linalg.norm(p - self.last) / dt)
        a = self.alpha_slow + (self.alpha_fast - self.alpha_slow) * min(1.0, v / self.velocity_scale)
        a *= max(0.15, min(1.0, confidence))
        out = self.last * (1.0 - a) + p * a
        self.last = out
        self.last_t = now
        return float(out[0]), float(out[1])
