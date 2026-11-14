"""Turn the CFI test data into a clean BurnBook CSV.

Run from burnbook/:
    python scripts/ingest_cfi.py CFI_DataSummary_Spreadsheet_Jan2021.xlsx [PSI-39_Experimental_table_CFI.csv]

The workbook (NASA CFI data summary, Jan 2021) has one row per test, FLEX-1206 to FLEX-1431, across sheets:
'Master Sheet' (conditions), 'DATA' (results), 'Igniter' and 'Comments'. The optional PSI-39 table is used only to
cross-check conditions. Writes data/cfi_tests.csv.

Columns kept from DATA: initial diameter d0, hot-flame extinction diameter, hot and cool burning-rate constants,
cool-flame extinction diameter (0 = droplet burned out with no cool-flame extinction), number of hot-flame
re-ignitions, hot-flame burn time, peak broad-band and water-band radiation, and whether analysis was completed.
Farnesane tests (FLEX-1388 to 1431) are in the sheet but were not analysed, so their results are blank.
Nothing is corrected; problems go to data_quality.
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ATM_TO_KPA = 101.325
# where the workbook disagrees with the CFI Science Final Report (Nayagam and Dietrich 2020)
REPORT_CHECKS = {"1268": "report Fig. 3 data box gives a cool-flame extinction diameter of 2.563 mm; this sheet gives 0 after 1 re-ignition"}


def _n(v):
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _f(v, nd=4):
    return "" if v is None else f"{round(v, nd):g}"


def main(argv):
    if len(argv) not in (2, 3):
        sys.exit(__doc__)
    import openpyxl
    wb = openpyxl.load_workbook(argv[1], read_only=True, data_only=True)

    def sheet(name):
        rows = list(wb[name].iter_rows(values_only=True))
        return {str(r[0]).strip(): r for r in rows[1:] if r and r[0] is not None}

    M, D, I, C = sheet("Master Sheet"), sheet("DATA"), sheet("Igniter"), sheet("Comments")
    psi = {}
    if len(argv) == 3:
        with open(argv[2], newline="", encoding="utf-8-sig") as f:
            for r in list(csv.reader(f))[1:]:
                if r and r[0].strip():
                    psi[r[0].strip()] = [c.strip() for c in r]

    def key(k):
        m = re.match(r"(\d+)(\D*)", k)
        return (int(m.group(1)), m.group(2))

    out = []
    for k in sorted(M, key=key):
        m, d, ig, cm = M[k], D.get(k, ()), I.get(k, ()), C.get(k, (None, ""))
        q = []
        date, time, cir, p, o2, n2, he, fiber, fuel = m[1:10]
        atm = float(str(p).split()[0])
        fuel = str(fuel).strip()
        mix = re.match(r"\[(\.\d+)\]/\[(\.\d+)\]", fuel)
        fuel_name = "n-dodecane" if fuel == "C12H26" else "farnesane" if fuel.lower() == "farnesane" else \
            (f"n-dodecane/iso-dodecane {mix.group(1)}/{mix.group(2)} by mass" if mix else fuel)
        if not k.isdigit():
            q.append(f"test number '{k}' is not a plain number in the source")
        if abs(o2 + n2 + he - 1) > 0.015:
            q.append(f"mole fractions sum to {o2 + n2 + he:.2f}")
        time = str(time).strip()
        if "xx" in time:
            q.append("time partly missing in source")
        if time.startswith("12:") and " am" in time:
            q.append("12:xx am in a daytime sequence; probably pm")
        series = str(cir)[4:5]
        if mix and series in ("d", "e") and mix.group(1) != (".60" if series == "d" else ".75"):
            q.append(f"mixture {mix.group(1)} differs from the rest of CIR series '{series}'")
        vals = [d[i] if len(d) > i else None for i in range(20)]
        if any(isinstance(v, str) and v.strip().lower() == "nan" for v in vals[1:19]):
            q.append("NaN in a results column")
        if k in REPORT_CHECKS:
            q.append(REPORT_CHECKS[k])
        if k in psi:
            r = psi[k]
            if float(re.sub(r"[^0-9.]", "", r[4])) != atm or float(r[5]) != o2 or float(r[6]) != n2 or float(r[7]) != he:
                q.append("conditions differ from PSI-39")
        d0, dhot, khot, kcool, dcool = (_n(vals[i]) for i in (1, 2, 3, 4, 5))
        out.append({
            "record_id": f"CFI-{k}", "flex_number": k, "date": date.date().isoformat() if isinstance(date, datetime) else str(date),
            "local_time": time, "cir_id": str(cir).strip(), "pressure_atm": f"{atm:g}", "pressure_kpa": f"{atm * ATM_TO_KPA:.1f}",
            "x_o2": f"{o2:g}", "x_n2": f"{n2:g}", "x_he": f"{he:g}",
            "fiber": {"Yes": "yes", "No": "no"}.get(str(fiber).strip(), ""), "fuel": fuel_name,
            "d0_mm": _f(d0), "dext_hot_mm": _f(dhot), "k_hot_mm2_s": _f(khot), "k_cool_mm2_s": _f(kcool), "dext_cool_mm": _f(dcool),
            "reignitions": _f(_n(vals[7])), "hot_flame_burn_s": _f(_n(vals[9])), "peak_hot_flame_rad": _f(_n(vals[10])),
            "peak_water_band_rad": _f(_n(vals[11])),
            "analysis_completed": str(vals[19] or "").strip().lower(),
            "ignition_power": str(ig[1] or "").strip() if len(ig) > 1 else "", "ignition_time": str(ig[2] or "").strip() if len(ig) > 2 else "",
            "comments": re.sub(r"\s+", " ", str(cm[1] or "")).strip(),
            "data_quality": "; ".join(q) or "ok",
            "source": "CFI data summary spreadsheet (NASA, Jan 2021)" + ("; conditions cross-checked with NASA PSI table PSI-39" if k in psi else ""),
        })
    for i, o in enumerate(out):  # a date far from both neighbours is a probable typo
        nb = [out[j]["date"] for j in (i - 1, i + 1) if 0 <= j < len(out)]
        try:
            if nb and all(abs((datetime.fromisoformat(o["date"]) - datetime.fromisoformat(n)).days) > 20 for n in nb):
                o["data_quality"] = "; ".join(x for x in (o["data_quality"], "date out of sequence with neighbouring tests; possible typo") if x != "ok")
        except ValueError:
            pass
    with open(DATA / "cfi_tests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"wrote data/cfi_tests.csv ({len(out)} tests)")


if __name__ == "__main__":
    main(sys.argv)
