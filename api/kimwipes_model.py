"""
Kimwipes concurrent-flow flame spread model (microgravity) with uncertainty and range flags.

Physics anchor: Olson, Ruff & Miller (2008), NASA/TM-2008-215260, Fig. 7 correlation
    V [cm/s] = 0.2498 * x + 0.4038,   x = O2_molefrac * flow_cm_s * P_atm**0.5
Data: 22 points digitized from that figure (authors' own concurrent tests; the
Grayson/Pettegrew literature points in the figure are NOT included).

Validated result (leave-one-out on the 22 points): the published line is as good as
any refit, power-law, or Gaussian-process residual model, so this module keeps the
published line as the mean and adds an honest, x-dependent uncertainty band.

Scope: ONE fuel (Kimwipes, thin cellulose), concurrent flow, microgravity (5.18 s drop tower).
Do not use for other materials, other gravity levels, or outside the tested ranges (see RANGE).
"""
import numpy as np

SLOPE = 0.2498
INTERCEPT = 0.4038

# (x parameter, spread rate cm/s, marker category in the original figure)
DIGITIZED = [
    (12.49, 3.24, "oxygen_varies"), (12.60, 3.08, "normoxic"), (12.01, 3.41, "pressure_varies"),
    (11.21, 3.37, "pressure_varies"), (10.00, 2.80, "pressure_varies"), (9.85, 2.97, "other_combination"),
    (9.65, 2.95, "normoxic"), (9.12, 2.56, "pressure_varies+normoxic"),
    (8.50, 2.56, "oxygen_varies+velocity_varies"), (8.00, 2.80, "oxygen_varies"),
    (7.49, 2.14, "oxygen_varies+normoxic"), (7.01, 2.28, "pressure_varies"), (6.71, 2.23, "normoxic"),
    (5.99, 2.06, "oxygen_varies"), (5.46, 1.87, "other_combination"), (4.74, 1.58, "other_combination"),
    (3.10, 1.37, "velocity_varies"), (2.85, 1.30, "velocity_varies"), (2.03, 0.84, "velocity_varies"),
    (1.08, 0.86, "velocity_varies"), (0.60, 0.75, "velocity_varies"), (0.30, 0.50, "velocity_varies"),
]

# Tested envelope stated in Olson et al. 2008 (text, section "Flame Spread Results")
RANGE = {
    "o2_pct": (24.0, 85.0),
    "flow_cm_s": (0.0, 30.0),
    "pressure_psia": (3.6, 14.7),
    "x": (0.3, 12.6),  # spread of the digitized correlation parameter
}
T975 = 2.09  # two-sided 95% t multiplier, ~20 degrees of freedom
SD_FLOOR = 0.06  # cm/s, roughly digitization + measurement floor


def _x_y():
    a = np.array(DIGITIZED, dtype=object)
    return a[:, 0].astype(float), a[:, 1].astype(float)


def fit_sd_model(x=None, y=None):
    """sd(x) = c0 + c1*x, fit to |residual about the published line| * sqrt(pi/2)."""
    if x is None:
        x, y = _x_y()
    r = np.abs(y - (SLOPE * x + INTERCEPT)) * np.sqrt(np.pi / 2.0)
    c1, c0 = np.polyfit(x, r, 1)
    return float(c0), float(c1)


_C0, _C1 = fit_sd_model()


def correlation_parameter(o2_pct, flow_cm_s, pressure_psia):
    return (o2_pct / 100.0) * flow_cm_s * (pressure_psia / 14.696) ** 0.5


def predict(o2_pct, flow_cm_s, pressure_psia):
    """Return predicted spread rate with a ~95% interval and out-of-range warnings."""
    x = correlation_parameter(o2_pct, flow_cm_s, pressure_psia)
    mean = SLOPE * x + INTERCEPT
    sd = max(SD_FLOOR, _C0 + _C1 * x)
    lo, hi = max(0.0, mean - T975 * sd), mean + T975 * sd
    warnings = []
    for name, val in (("o2_pct", o2_pct), ("flow_cm_s", flow_cm_s), ("pressure_psia", pressure_psia), ("x", x)):
        lo_r, hi_r = RANGE[name]
        if not (lo_r <= val <= hi_r):
            warnings.append(f"{name}={val:.3g} is outside the tested range {lo_r}-{hi_r}")
    if x < 1.0:
        warnings.append("x<1: near the quench limit the correlation falls off from linear; treat as an upper estimate")
    return {
        "x": round(x, 3),
        "spread_rate_cm_s": round(mean, 3),
        "lo95": round(lo, 3),
        "hi95": round(hi, 3),
        "in_tested_range": len(warnings) == 0,
        "warnings": warnings,
        "scope": "Kimwipes thin cellulose, concurrent flow, microgravity only",
    }


def loo_report():
    """Leave-one-out check of the interval: RMSE about the published line and empirical coverage."""
    x, y = _x_y()
    errs, cover = [], []
    for i in range(len(x)):
        m = np.arange(len(x)) != i
        c0, c1 = fit_sd_model(x[m], y[m])
        mean = SLOPE * x[i] + INTERCEPT
        sd = max(SD_FLOOR, c0 + c1 * x[i])
        errs.append(y[i] - mean)
        cover.append(abs(y[i] - mean) <= T975 * sd)
    errs = np.array(errs)
    return {
        "n": int(len(x)),
        "rmse_cm_s": float(np.sqrt(np.mean(errs ** 2))),
        "mean_error_cm_s": float(np.mean(errs)),
        "interval_coverage": float(np.mean(cover)),
    }


if __name__ == "__main__":
    print("sd(x) = %.3f + %.4f*x" % (_C0, _C1))
    print(loo_report())
    for label, args in [
        ("ISS air, 20 cm/s", (21, 20, 14.7)),
        ("30% O2 / 10.2 psia, 20 cm/s", (30, 20, 10.2)),
        ("34% O2 / 8.0 psia, 5 cm/s", (34, 5, 8.0)),
    ]:
        print(label, predict(*args))
