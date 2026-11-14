"""Turn the NASA PSI FLEX experimental table (PSI-69) into a clean BurnBook CSV.

Run from burnbook/:
    python scripts/ingest_flex.py PSI-69_Experimental_table_FLEX.csv

Writes data/flex_tests.csv, one row per ISS FLEX droplet test (methanol and n-heptane, 2009-2011).

Notes on the source:
- The file is Windows-1252; an en dash (byte 0x96) marks a value that was not measured. It becomes blank.
- Gas fractions are mole fractions (stated in the header). 'Burning rate; mm' is the droplet burning-rate constant;
  its unit is printed as mm but the values (0.05 to 1.06) are mm2/s, the usual unit, and are kept as printed.
- A visible-flame extinction diameter of 0 means the droplet burned to completion with no measured extinction size.
- Nothing is corrected; problems are listed in data_quality.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
MMHG_TO_KPA = 0.133322


def _num(v):
    v = (v or "").strip().replace("–", "")
    if v in ("", "-"):
        return None
    try:
        return float(v.lstrip("~"))
    except ValueError:
        return None


def _fmt(v, nd=4):
    return "" if v is None else f"{round(v, nd):g}"


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    with open(argv[1], newline="", encoding="cp1252") as f:
        rows = list(csv.reader(f))
    head, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    ids = Counter(r[1].strip() for r in body)
    out = []
    for r in body:
        q = []
        num, ident, date, gmt, fuel = (c.strip() for c in r[:5])
        p, o2, n2, co2, he, d0, dext, k, tb = (_num(c) for c in r[5:14])
        end = r[14].strip()
        if "–" in "".join(r):
            q.append("en dash in source read as 'not measured'")
        if p == 0:
            q.append("pressure recorded as 0 mmHg; not physical, withheld")
            p = None
        if ids[ident] > 1:
            q.append(f"identifier {ident} appears {ids[ident]} times in the table")
        if r[13].strip().startswith("~"):
            q.append("burn time given as approximate")
        gas = [x for x in (o2, n2, co2, he) if x is not None]
        if gas and abs(sum(gas) - 1) > 0.02:
            q.append(f"mole fractions sum to {sum(gas):.2f}")
        diluent = "+".join(n for n, x in (("N2", n2), ("CO2", co2), ("He", he)) if x)
        consumed = None
        if d0 and dext is not None and dext > 0:
            consumed = 1 - (dext / d0) ** 2
        elif d0 and dext == 0:
            consumed = 1.0
        out.append({
            "record_id": f"FLEX-{int(float(num)):03d}", "identifier": ident, "date": date, "gmt": gmt, "fuel": fuel.lower(),
            "pressure_mmhg": _fmt(p, 1), "pressure_kpa": _fmt(p * MMHG_TO_KPA if p else None, 1),
            "x_o2": _fmt(o2), "x_n2": _fmt(n2), "x_co2": _fmt(co2), "x_he": _fmt(he), "diluent": diluent,
            "d0_mm": _fmt(d0), "dext_mm": _fmt(dext), "burning_rate_mm2_s": _fmt(k), "burn_time_s": _fmt(tb),
            "fraction_burned": _fmt(consumed, 3), "test_end": end.lower(),
            "data_quality": "; ".join(q) or "ok",
            "source": "NASA PSI table PSI-69 (FLEX)",
        })
    with open(DATA / "flex_tests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"wrote data/flex_tests.csv ({len(out)} tests)")


if __name__ == "__main__":
    main(sys.argv)
