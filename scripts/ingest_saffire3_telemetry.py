"""Reduce the Saffire-III telemetry workbook (NASA PSI) to a 10-second CSV plus a short summary.

Run from burnbook/:
    python scripts/ingest_saffire3_telemetry.py Saffire-III_Telemetry_Data.xlsx

Unlike the Saffire-I and II sensor workbooks, this file is housekeeping telemetry, not calibrated science data:
- 'SaffireData': the experiment's own channels (4 radiometers, 2 anemometers, fan speed, igniter currents) every ~30 s.
- 'CygnusData': the cargo vehicle's cabin sensors (3 pressure sensors, air temperature, two smoke detectors) every ~10 s.
  Each row carries only one or two channels; the rest are 0, so 0 is read as 'no reading in this row'.
There are no O2, CO2, CO or thermocouple channels. Writes
    data/saffire3_sensors.csv           10 s bins: cabin pressure, air temperature, smoke detector, Saffire channels
    data/saffire3_sensors_summary.json  pressure and temperature rise, smoke detector response, radiometer windows
Nothing is corrected; problems go to "checks".
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"
IDLE_I = -3.0  # igniter current channels read about -3.05 A when not selected
PRE = (7500.0, 8250.0)  # quiet cabin window before any igniter channel or smoke-detector activity, s


def _f(v):
    return float(v) if isinstance(v, (int, float)) else np.nan


def load(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb["SaffireData"].iter_rows(values_only=True))
    h = list(rows[0])
    body = [r for r in rows[1:] if isinstance(r[3], (int, float))]
    col = lambda name: np.array([_f(r[h.index(name)]) for r in body])  # noqa: E731
    saf = {"t": col("Relative Time (s)"), "saffire_epoch_s": np.array([_f(r[0]) / 1e3 for r in body])}
    for i in range(1, 5):
        saf[f"rad{i}"] = col(f"Radiometer{i}Value")
    saf["anem1"], saf["anem2"], saf["fan_rpm"] = col("Anemometer1"), col("Anemometer2"), col("FanTachometer")
    for s in (1, 2):
        saf[f"ign{s}_i"] = col(f"Sample{s}IgniterI")
    rows = list(wb["CygnusData"].iter_rows(values_only=True))
    h = list(rows[0])
    body = [r for r in rows[1:] if isinstance(r[2], (int, float))]
    t = np.array([_f(r[2]) for r in body])
    zero = next(_f(r[0]) / 1e3 for r in body if r[1] == 0)  # Cygnus epoch time at relative time 0
    saf["clock_offset_s"] = saf["saffire_epoch_s"] - (zero + saf["t"])
    bad = int((t < -1e5).sum())
    keep = t > -1e5
    cyg = {"t": t[keep]}
    names = {"temp_c": "PCM Air Temp (degC)", "p1": "PCM Press EPS 1 (psi)", "p2": "PCM Press ECM 2 (psi)",
             "p3": "PCM Press EPS 3 (psi)", "fiz1_obsc": "FIZ1 Smoke Detector Obscuration  (V)",
             "fiz2_obsc": "FIZ 2 Smoke Detector Obscuration (V)", "fiz2_scat": "FIZ 2 Smoke Detector Scatterometer (V)"}
    for k, n in names.items():
        x = np.array([_f(r[h.index(n)]) for r in body])[keep]
        x[x == 0] = np.nan
        cyg[k] = x
    o = np.argsort(cyg["t"])
    cyg = {k: v[o] for k, v in cyg.items()}
    return saf, cyg, bad


def m(t, x, a, b):
    s = (t >= a) & (t < b) & ~np.isnan(x)
    return float(np.mean(x[s])) if s.any() else np.nan


def windows(t, on, gap=45.0):
    """Group sample times where `on` is true into windows, splitting at gaps longer than `gap` seconds."""
    ts = t[on]
    if not len(ts):
        return []
    out, a, b = [], ts[0], ts[0]
    for x in ts[1:]:
        if x - b > gap:
            out.append([round(a, 1), round(b, 1)])
            a = x
        b = x
    out.append([round(a, 1), round(b, 1)])
    return out


def summarise(saf, cyg, bad):
    t = saf["t"]
    base_n = int(np.sum(t < 8380))  # Saffire samples before the first igniter current (8,383 s)
    rad = {}
    for i in range(1, 5):
        x = saf[f"rad{i}"]
        b, sd = float(np.mean(x[:base_n])), float(np.std(x[:base_n]))
        on = x > b + max(5.0, 5 * sd)
        rad[f"rad{i}"] = {"baseline": round(b, 1), "peak_rise": round(float(np.max(x) - b), 1),
                          "peak_at_s": round(float(t[np.argmax(x)]), 1), "above_baseline_s": windows(t, on)}
    ign = {}
    for s in (1, 2):
        i = saf[f"ign{s}_i"]
        sel = t[i > IDLE_I + 1]
        ign[f"sample{s}"] = {"channel_selected_from_s": round(float(sel.min()), 1) if len(sel) else None,
                             "current_seen_s": [round(float(x), 1) for x in t[i > 0.5]],
                             "peak_current_seen_a": round(float(np.max(i)), 2)}
    fan_off = windows(t, saf["anem1"] < 2, gap=31)
    pres = {}
    for k in ("p1", "p2", "p3"):
        x, tt = cyg[k], cyg["t"]
        g = ~np.isnan(x)
        after = g & (tt > PRE[1])
        pres[k] = {"pre": round(m(tt, x, *PRE), 3), "max": round(float(np.max(x[after])), 3),
                   "max_at_s": round(float(tt[after][np.argmax(x[after])]), 0), "end": round(float(x[g][-1]), 3)}
    pre_p = float(np.mean([v["pre"] for v in pres.values()]))
    max_p = float(np.mean([v["max"] for v in pres.values()]))
    tt, temp = cyg["t"], cyg["temp_c"]
    g = ~np.isnan(temp)
    sc, gs = cyg["fiz2_scat"], ~np.isnan(cyg["fiz2_scat"])
    sb, ssd = m(tt, sc, *PRE), float(np.nanstd(sc[(tt >= PRE[0]) & (tt < PRE[1])]))
    hi = gs & (tt > PRE[1]) & (sc > sb + 10 * max(ssd, 0.002))
    win = windows(tt, hi, gap=25)
    peak_i = int(np.nanargmax(np.where(tt > PRE[1], sc, np.nan)))
    checks = [
        "telemetry, not calibrated science data: Saffire channels every ~30 s, cabin channels every ~10 s, so times are good to about 30 s",
        f"the Saffire and Cygnus clocks differ by about {np.median(saf['clock_offset_s']):.0f} s; times here use the Cygnus relative clock given in the file",
        "no O2, CO2, CO or thermocouple channels in this file, so no gas rise can be computed",
        "radiometer positions are not labelled; in Saffire-I's file radiometer 1 is 'downstream front', which does not fit the order seen here, so no positions are named",
        f"anemometers read about {np.mean(saf['anem1'][:base_n]):.1f} and {np.mean(saf['anem2'][:base_n]):.1f} cm/s before ignition; PSI-100 lists 30 cm/s",
        "from about 9,343 s the anemometer and fan channels hold fixed values (4.3, 6.2 cm/s, -14.7 rpm), so the experiment was probably shut down; readings after that are not airflow",
        "Cygnus smoke detector FIZ 1 has no readings; FIZ 2 obscuration stepped to about 3.8 V at about 1,500 s, long before any test, and did not respond to the fire",
        "the FIZ 2 scatter channel spiked to 1.6 V at about 8,296 s, before any radiometer signal but close to when sample 2's igniter channel was switched on (8,323 s, within the 30 s sampling and 17 s clock uncertainty); the cause is not identifiable from this file",
        f"{bad} cabin rows have an invalid timestamp and were skipped",
        "the igniter current is caught in one 30 s sample for sample 2 only; sample 1's ignition falls between samples",
    ]
    return {
        "cadence_s": {"saffire": round(float(np.median(np.diff(t))), 1), "cabin": round(float(np.median(np.diff(tt[g]))), 1)},
        "record_s": round(float(tt.max()), 1), "saffire_window_s": [round(float(t.min()), 1), round(float(t.max()), 1)],
        "pressure_psia": {"pre_ignition": round(pre_p, 3), "max_after": round(max_p, 3), "rise": round(max_p - pre_p, 3),
                          "sensors": pres},
        "air_temp_c": {"pre_ignition": round(m(tt, temp, *PRE), 2), "max_after": round(float(np.nanmax(temp[tt > PRE[1]])), 2),
                       "max_at_s": round(float(tt[g & (tt > PRE[1])][np.argmax(temp[g & (tt > PRE[1])])]), 0)},
        "smoke_scatter_v": {"baseline": round(sb, 3), "peak": round(float(sc[peak_i]), 3), "peak_at_s": round(float(tt[peak_i]), 0),
                            "above_10sd_windows_s": win, "end": round(float(sc[gs][-1]), 3), "end_at_s": round(float(tt[gs][-1]), 0)},
        "airflow_before_ignition_cm_s": [round(float(np.mean(saf["anem1"][:base_n])), 1), round(float(np.mean(saf["anem2"][:base_n])), 1)],
        "fan_stopped_s": fan_off, "igniters": ign, "radiometers": rad, "checks": checks,
    }


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    saf, cyg, bad = load(argv[1])
    summ = summarise(saf, cyg, bad)
    summ["source"] = Path(argv[1]).name
    t0, t1 = 0, int(cyg["t"].max()) + 10
    keys = ["pressure_psia", "air_temp_c", "smoke_scatter_v", "smoke_obscuration_v",
            "rad1", "rad2", "rad3", "rad4", "anemometer1_cm_s", "anemometer2_cm_s", "fan_rpm"]
    with open(DATA / "saffire3_sensors.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s"] + keys)
        for a in range(t0, t1, 10):
            b = a + 10
            ct, st = cyg["t"], saf["t"]
            p = [m(ct, cyg[k], a, b) for k in ("p1", "p2", "p3")]
            p = [x for x in p if not np.isnan(x)]
            row = [np.mean(p) if p else np.nan, m(ct, cyg["temp_c"], a, b), m(ct, cyg["fiz2_scat"], a, b), m(ct, cyg["fiz2_obsc"], a, b)]
            row += [m(st, saf[k], a, b) for k in ("rad1", "rad2", "rad3", "rad4", "anem1", "anem2", "fan_rpm")]
            if all(np.isnan(x) for x in row):
                continue
            w.writerow([a] + ["" if np.isnan(x) else round(float(x), 4) for x in row])
    (DATA / "saffire3_sensors_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(sys.argv)
