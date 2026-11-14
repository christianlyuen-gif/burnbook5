"""Turn the raw NASA PSI tables for ACME (BRE, CLD Flame) and CFI-G into clean BurnBook CSVs.

Run from burnbook/:
    python scripts/ingest_acme.py BRE.csv CLD_Flame.csv CFI-G_Normal.csv CFI-G_Inverse.csv
(the PSI-20, PSI-21 and two PSI-159 downloads, in that order)

Writes:
    data/acme_bre_test_days.csv    one row per BRE test day (burner, fuel, O2 levels that ignited, flames ignited)
    data/acme_cld_test_days.csv    one row per CLD Flame test day
    data/cfig_flames.csv           one row per CFI-G test, normal and inverse flames

Honesty rules: values are copied as printed; obvious typos are corrected only where the intended value is
unambiguous, and every correction is written to data_quality. Blank cells stay blank.
"""
from __future__ import annotations

import csv
import datetime
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _read(p):
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _col(r, name):
    for k, v in r.items():
        if k and re.sub(r"\s+", " ", k).strip().lower() == name.lower():
            return (v or "").strip()
    return ""


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v):
    return "" if v is None else f"{v:g}"


def _write(rows, name):
    with open(DATA / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote data/{name} ({len(rows)} rows)")


def bre(src):
    out = []
    for i, r in enumerate(_read(src), 1):
        q = []
        o2_raw = _col(r, "Oxygen Conc (percent)")
        levels = []
        for tok in o2_raw.split(";"):
            tok = tok.strip()
            m = re.fullmatch(r"(\d{2})00%", tok)  # '3400%' and '2100%' are 34 and 21 typed into a percent-formatted cell
            if m:
                levels.append(m.group(1))
                q.append(f"O2 printed as '{tok}', read as {m.group(1)}%")
            elif tok:
                levels.append(tok)
        mon = MONTHS[_col(r, "Month")[:3].lower()]
        date = datetime.date(int(_col(r, "Year")), mon, int(_col(r, "Date")))
        out.append({
            "record_id": f"BRE-{i:02d}", "date": date.isoformat(), "burner_mm": _col(r, "Burner Size (mm)"),
            "fuel": re.sub(r"%\s*", "% ", _col(r, "Fuel Bottle")),
            "o2_levels_pct": "; ".join(levels), "flames_ignited": _col(r, "Flames Ignited"),
            "data_quality": "; ".join(q) or "ok",
            "source": "NASA PSI table PSI-20 (ACME BRE); chamber pressures varied but are not listed",
        })
    return out


def cld(src):
    out = []
    for i, r in enumerate(_read(src), 1):
        q = []
        day = _col(r, "Test Day")
        date = datetime.date(2000 + int(day[:2]), 1, 1) + datetime.timedelta(days=int(day[2:]) - 1)
        bottle = _col(r, "Fuel Bottle")
        # spreadsheet auto-fill turned repeated '40% CH4' into CH5, CH6 ... and 'C2H4' into C2H5 ...; the
        # fuel family is never in doubt (methane or ethylene), so restore the formula and flag it
        m = re.fullmatch(r"(\d+%)\s*(CH|C2H)(\d+)", bottle.replace(" ", ""))
        if m:
            fixed = f"{m.group(1)} {'CH4' if m.group(2) == 'CH' else 'C2H4'}"
            if fixed.replace(" ", "") != bottle.replace(" ", ""):
                q.append(f"fuel printed as '{bottle}', an auto-fill artefact; read as {fixed}")
            bottle = fixed
        out.append({
            "record_id": f"CLD-{i:02d}", "test_day": day, "date": date.isoformat(), "test_type": _col(r, "Test Type"),
            "fuel_bottle": bottle, "fuel_mfc_slpm": _col(r, "Fuel MFC"), "n2_mfc_slpm": _col(r, "N2 MFC"),
            "fuel_conc_range": _col(r, "Fuel conc. Range"), "flames_ignited": _col(r, "Flames ignited"),
            "data_quality": "; ".join(q) or "ok",
            "source": "NASA PSI table PSI-21 (ACME CLD Flame)",
        })
    return out


def cfig(normal_src, inverse_src):
    out = []

    def common(r, ftype, q):
        ign = _col(r, "Hot ignition").lower()
        burn = _num(_col(r, "burn time (sec)"))
        end = _col(r, "Self-ext or flow term") or _col(r, "Self -ext or flow term")
        if ign == "no" and burn:
            q.append(f"hot ignition 'No' but burn time {burn:g} s; comment says '{_col(r, 'Comments')}'")
        return {
            "hot_ignition": ign or "",
            "burn_s": _fmt(burn),
            "ended_by": {"SE": "self-extinguished", "FT": "fuel flow stopped"}.get(end, ""),
            "comments": _col(r, "Comments"),
        }

    for r in _read(normal_src):
        if not _col(r, "Test"):
            continue
        q = []
        tad = _col(r, "Tad (K)")
        if "#DIV" in tad:
            q.append("spreadsheet error (#DIV/0!) in Tad and Zst: fuel flow listed as 0")
        cool = _col(r, "Cool flame?").lower()
        row = {
            "record_id": f"CFN-{len([o for o in out if o['flame_type'] == 'normal']) + 1:03d}", "flame_type": "normal",
            "day": _col(r, "Day"), "fuel": _col(r, "Fuel"), "test": _col(r, "Test"),
            "o2_ambient": _col(r, "XO2 before test"), "o2_ambient_after": _col(r, "XO2 after test"),
            "fuel_fraction": _col(r, "Xf"), "pressure_bar": _col(r, "approx p (bar)"),
            "fuel_rate_mg_s": _col(r, "mHC (mg/s)"), "o2_rate_mg_s": "",
            "tad_k": "" if "#DIV" in tad else tad,
            "cool_flame": "yes" if cool.startswith("yes") else ("no" if cool.startswith("no") else ""),
            "peak_burner_c": _col(r, "Peak burner T (C )").replace("-", ""), "color": "",
        }
        row.update(common(r, "normal", q))
        row["data_quality"] = "; ".join(q) or "ok"
        out.append(row)
    n = 0
    for r in _read(inverse_src):
        if not _col(r, "Test"):
            continue
        q = []
        n += 1
        row = {
            "record_id": f"CFI-{n:03d}", "flame_type": "inverse", "day": _col(r, "Day"), "fuel": _col(r, "Fuel"),
            "test": _col(r, "Test"), "o2_ambient": "", "o2_ambient_after": "",
            "fuel_fraction": _col(r, "Xf before test"), "pressure_bar": _col(r, "approx p (bar)"),
            "fuel_rate_mg_s": _col(r, "HC burnrate (mg/s)"), "o2_rate_mg_s": _col(r, "O2 flow rate (mg/s)"),
            "tad_k": _col(r, "Tad (K)"), "cool_flame": "",
            "peak_burner_c": _col(r, "Peak burner Temp (C)"), "color": _col(r, "Color").replace("-", ""),
        }
        row["o2_burner"] = _col(r, "XO2")
        row.update(common(r, "inverse", q))
        row["data_quality"] = "; ".join(q) or "ok"
        out.append(row)
    for row in out:  # same columns everywhere; o2_burner is the O2 fraction fed through the burner in inverse flames
        row.setdefault("o2_burner", "")
    keys = ["record_id", "flame_type", "day", "fuel", "test", "o2_ambient", "o2_ambient_after", "o2_burner", "fuel_fraction",
            "pressure_bar", "fuel_rate_mg_s", "o2_rate_mg_s", "tad_k", "hot_ignition", "burn_s", "ended_by", "cool_flame",
            "peak_burner_c", "color", "comments", "data_quality"]
    for row in out:
        row["source"] = "NASA PSI table PSI-159 (CFI-G, normal and inverse flames)"
    return [{k: row.get(k, "") for k in keys + ["source"]} for row in out]


def main(argv):
    if len(argv) != 5:
        sys.exit(__doc__)
    _write(bre(argv[1]), "acme_bre_test_days.csv")
    _write(cld(argv[2]), "acme_cld_test_days.csv")
    _write(cfig(argv[3], argv[4]), "cfig_flames.csv")


if __name__ == "__main__":
    main(sys.argv)
