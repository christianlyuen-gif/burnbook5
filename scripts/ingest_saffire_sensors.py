"""Reduce a Saffire sensor workbook from NASA PSI to a 1-second CSV plus a short summary.

Run from burnbook/:
    python scripts/ingest_saffire_sensors.py WORKBOOK.xlsx RECORD_ID
    e.g. python scripts/ingest_saffire_sensors.py Saffire-I_Sample_2_Sensor_Data_Complete_TM_graphs.xlsx saffire1_s2

Reads the 'Calibrated Data' sheet (about 30 samples per second) and writes
    data/<RECORD_ID>_sensors_1hz.csv       one row per second: means of each kept channel
    data/<RECORD_ID>_sensors_summary.json  pressure, gas change, igniter on-time, flame window, peaks

Rows without an elapsed time are skipped (the sheet carries extra helper rows below the data). Radiometer zero
offsets are not removed in the CSV; the summary reports rises above the pre-ignition mean. Nothing is corrected.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"
KEEP = {  # output column: source header
    "pressure_psia": "Ambient Pressure", "o2_pct": "O2", "co2_pct": "CO2",
    "anemometer1_cm_s": "Anemometer 1", "anemometer2_cm_s": "Anemometer 2", "fan_rpm": "Average Fan Speed",
    "rad1_downstream_front_mw_cm2": "Radiometer 1", "rad2_upstream_front_mw_cm2": "Radiometer 2",
    "rad3_upstream_back_mw_cm2": "Radiometer 3", "rad4_downstream_back_mw_cm2": "Radiometer 4",
    "inlet_temp_c": "Test Section Inlet Temp",
    **{f"plume_tc{i}_c": f"Plume Temp {i} (TC{i})" for i in range(1, 7)},
    **{f"sample_tc{i}_c": f"Sample Temp {i - 6} (TC{i})" for i in range(7, 13)},
    "igniter_current_a": "Igniter Current", "igniter_voltage_v": "Igniter Voltage",
}


POSITIONS_LABELLED = False


def load(path):
    global POSITIONS_LABELLED
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Calibrated Data"]
    rows = ws.iter_rows(values_only=True)
    head = list(next(rows))
    POSITIONS_LABELLED = "Downstream Front" in head  # Saffire-I files name each radiometer's position; Saffire-II files do not
    next(rows)  # units row
    idx = {k: head.index(v) for k, v in KEEP.items()}
    t, cols = [], {k: [] for k in KEEP}
    for r in rows:
        if r[0] is None or isinstance(r[0], str):
            continue
        t.append(float(r[0]))
        for k, i in idx.items():
            v = r[i]
            cols[k].append(float(v) if isinstance(v, (int, float)) else np.nan)
    return np.array(t), {k: np.array(v) for k, v in cols.items()}


def window(t, x, a, b):
    m = (t >= a) & (t <= b)
    return float(np.nanmean(x[m]))


def summarise(t, c):
    ign = t[c["igniter_current_a"] > 0.5]
    t_on, t_off = (float(ign.min()), float(ign.max())) if len(ign) else (None, None)
    pre = (5.0, (t_on or 60.0) - 5.0)
    k = max(1, int(round(10 / np.nanmedian(np.diff(t)))))  # 10 s running mean for slow gas sensors
    sm = lambda x: np.convolve(np.nan_to_num(x, nan=np.nanmean(x)), np.ones(k) / k, mode="valid")  # noqa: E731
    ts = t[k // 2: k // 2 + len(t) - k + 1]
    gas = {}
    for g in ("o2_pct", "co2_pct"):
        s = sm(c[g])
        base = float(np.mean(s[(ts >= pre[0]) & (ts <= pre[1])]))
        after = ts > (t_off or 0)
        gas[g] = {"pre_ignition": round(base, 4), "max_after": round(float(s[after].max()), 4),
                  "min_after": round(float(s[after].min()), 4), "end": round(float(s[-1]), 4),
                  "noise_sd_raw": round(float(np.nanstd(c[g][(t >= pre[0]) & (t <= pre[1])])), 4)}
    flame = {}
    for r in ("rad1_downstream_front_mw_cm2", "rad2_upstream_front_mw_cm2", "rad3_upstream_back_mw_cm2", "rad4_downstream_back_mw_cm2"):
        x = c[r]
        base, sd = window(t, x, *pre), float(np.nanstd(x[(t >= pre[0]) & (t <= pre[1])]))
        med = np.array([np.nanmedian(x[max(0, i - 15): i + 16]) for i in range(len(x))])
        on = t[(t > pre[1]) & (t < t.max() - 5) & (med > base + max(1.0, 5 * sd))]
        flame[r] = {"peak_rise": round(float(np.nanmax(med) - base), 2),
                    "above_baseline_s": [round(float(on.min()), 1), round(float(on.max()), 1)] if len(on) else None}
    i = int(np.nanargmax(c["igniter_current_a"]))
    on = c["igniter_current_a"] > 0.5
    power = float(np.nanmedian(c["igniter_current_a"][on] * c["igniter_voltage_v"][on])) if on.any() else None
    checks = []
    if power is not None and not 20 <= power <= 1000:
        checks.append(f"igniter voltage channel reads about {np.nanmedian(c['igniter_voltage_v'][on]):.1f} V while on, giving "
                      f"{power:.0f} W, far from the roughly 190 W in the Saffire-I file; the voltage channel is not consistent "
                      "across flights, so power is withheld (the PSI table lists the planned igniter power)")
        power = None
    if not POSITIONS_LABELLED:
        checks.append("radiometer positions are not labelled in this file; the downstream/upstream names follow the Saffire-I layout and may not apply")
    plume = {k: round(float(np.nanmax(v)), 1) for k, v in c.items() if k.startswith("plume_tc")}
    return {
        "record_s": round(float(t.max()), 1), "samples": int(len(t)),
        "pressure_psia": {"mean": round(float(np.nanmean(c["pressure_psia"])), 3),
                          "min": round(float(np.nanmin(c["pressure_psia"])), 3),
                          "max": round(float(np.nanmax(c["pressure_psia"])), 3)},
        "igniter": {"on_s": t_on, "off_s": t_off, "peak_current_a": round(float(c["igniter_current_a"][i]), 2),
                    "median_power_w": None if power is None else round(power, 0)},
        "airflow_before_ignition_cm_s": [round(window(t, c["anemometer1_cm_s"], *pre), 1), round(window(t, c["anemometer2_cm_s"], *pre), 1)],
        "gas": gas, "radiometers": flame, "plume_peak_c": plume,
        "sample_tc_peak_c": {k: round(float(np.nanmax(v)), 1) for k, v in c.items() if k.startswith("sample_tc")},
        "checks": checks,
    }


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    t, c = load(argv[1])
    rid = argv[2]
    secs = np.floor(t).astype(int)
    with open(DATA / f"{rid}_sensors_1hz.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s"] + list(KEEP))
        for s in range(secs.min(), secs.max() + 1):
            m = secs == s
            if m.any():
                w.writerow([s] + [("" if np.isnan(v := np.nanmean(c[k][m])) else round(float(v), 4)) for k in KEEP])
    summ = summarise(t, c)
    summ["source"] = Path(argv[1]).name
    (DATA / f"{rid}_sensors_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(sys.argv)
