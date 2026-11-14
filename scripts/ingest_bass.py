"""Turn the raw NASA PSI test tables for BASS and BASS-II into clean BurnBook CSVs.

Run from burnbook/:
    python scripts/ingest_bass.py PATH/TO/PSI-25_Experimental_table_BASS-II.csv PATH/TO/PSI-26_Experimental_table_BASS.csv

Writes:
    data/bass2_instrumented_tests.csv   one row per BASS-II test with O2 / CO2 / CO before and after
    data/bass_test_index.csv            the BASS (first campaign) test manifest: date, test, sample, material

Honesty rules this script follows:
- Numeric columns are copied as-is; blank or 'none' become empty, never zero.
- The source has no outcome column. Researchers wrote the flow ramp and what happened into the
  'Fan display' / 'Air display' cells as free text. outcome_flag is a keyword match over that text
  (extinguished / blowoff / no_ignition). An empty flag means "not stated in the notes", not "burned to completion".
- Deltas are computed only when both readings exist.

Units, from the BASS-II Summary Report (NASA/TM-20210011385, p. 5): the video overlay and these columns show
the air velocity transducer in cm/s ('Air display'), fan voltage x10 ('Fan display'), N2 flow in cm3/min, and an
uncalibrated radiometer signal whose gain is set on the control box. 'pot' values in the notes are fan
potentiometer settings. Flow restrictors at the fan inlet cap the duct flow: about 55 cm/s with none, 35 cm/s with two.
initial_air_cm_s is the first number in 'Air display' (the flow at the start of the test); the transducer
needs about a minute to settle, so treat it as approximate.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SRC_BASS2 = "PSI-25 Experimental table, BASS-II (NASA Physical Sciences Informatics)"
SRC_BASS = "PSI-26 Experimental table, BASS (NASA Physical Sciences Informatics)"

# order matters: first match wins
OUTCOME_PATTERNS = [
    ("no_ignition", re.compile(r"no ign|would not stay lit", re.I)),
    ("blowoff", re.compile(r"blow\s*-?off", re.I)),
    # 'off' alone is left out on purpose: it can mean the fan was switched off, not the flame
    ("extinguished", re.compile(r"extinguish|\bext|\bout\b", re.I)),
]


def _num(v):
    if v is None:
        return None
    v = str(v).strip()
    if v == "" or v.lower() == "none":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _fmt(v):
    return "" if v is None else f"{v:g}"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def material_family(m: str) -> str:
    s = m.lower()
    if "sibal" in s:
        return "SIBAL (cotton-fiberglass blend)"
    if "nomex" in s:
        return "Nomex"
    if "ultem" in s:
        return "Ultem"
    if "wax" in s or "candle" in s:
        return "wax candle"
    # BASS-II rods, films ("... micron ...") and spherical sections are all PMMA in the test matrix
    if any(k in s for k in ("pmma", "rod", "film", "micron", "slab", "sphere", "spherical")):
        return "PMMA"
    return "other"


def geometry(m: str) -> str:
    s = m.lower()
    for key, label in (("rod", "rod"), ("film", "thin film"), ("micron", "thin film"), ("spherical", "spherical section"),
                       ("sphere", "sphere"), ("slab", "slab"), ("thick", "slab"), ("candle", "candle"),
                       ("wax", "candle"), ("sheet", "sheet"), ("sibal", "fabric"), ("nomex", "fabric")):
        if key in s:
            return label
    return "unspecified"


def date_check(date: str, doy: str, years: tuple[int, ...]) -> str:
    """Flag dates that do not parse, fall outside the campaign years, or disagree with the GMT day-of-year column.
    Values are never corrected: we cannot tell which of the two columns is wrong."""
    import datetime
    try:
        m, d, y = (int(x) for x in date.split("/"))
        day = datetime.date(y, m, d).timetuple().tm_yday
    except Exception:
        return f"date '{date}' does not parse"
    notes = []
    if y not in years:
        notes.append(f"year {y} outside the campaign ({'-'.join(str(v) for v in (min(years), max(years)))}); likely a typo")
    if doy.strip() and doy.strip() != str(day):
        notes.append(f"date {date} is day {day} but the GMT column says {doy.strip()}")
    return "; ".join(notes)


def outcome_flag(text: str) -> str:
    for label, pat in OUTCOME_PATTERNS:
        if pat.search(text):
            return label
    return ""


def ingest_bass2(src: Path) -> list[dict]:
    with open(src, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # header has stray double spaces; look columns up by normalized name
    def col(r, name):
        for k, v in r.items():
            if k and _clean(k).lower() == name.lower():
                return v
        return None

    out = []
    for i, r in enumerate(rows, 1):
        mat = _clean(col(r, "Fuel Sample Material"))
        fan, air = _clean(col(r, "Fan display")), _clean(col(r, "Air display"))
        notes = "; ".join(x for x in (f"fan: {fan}" if fan else "", f"air: {air}" if air else "") if x)
        io2, fo2 = _num(col(r, "Calibrated initial O2 % by vol")), _num(col(r, "Calibrated final O2 % by vol"))
        ico2, fco2 = _num(col(r, "Initial CO2 % by vol")), _num(col(r, "Final CO2 % by vol"))
        ico, fco = _num(col(r, "Initial CO (ppm)")), _num(col(r, "Final CO (ppm)"))
        # A small sample in the glovebox moves O2 by a few tenths of a percent, at most ~3%.
        # Final O2 values like 0.6 or 40 are not physical and look like a value typed into the wrong cell.
        m_air = re.match(r"^~?(\d+(?:\.\d+)?)\b", air)
        air0 = float(m_air.group(1)) if m_air else None
        quality = []
        dq = date_check(_clean(col(r, "Date")), _clean(col(r, "GMT")), (2014, 2015, 2016))
        if dq:
            quality.append(dq)
        cap = 36.0 if _clean(col(r, "Flow restrictor")) == "2" else 56.0  # duct maximum for this restrictor setup
        if air0 is not None and air0 > cap:
            quality.append(f"air reading {air0:g} exceeds the {cap:g} cm/s duct limit; likely a fan value, air speed withheld")
            air0 = None
        if io2 is not None and fo2 is not None and not (io2 - 6.0 <= fo2 <= io2 + 0.5):
            quality.append(f"final O2 {fo2:g}% not plausible (initial {io2:g}%); O2 delta withheld")
            fo2_ok = None
        else:
            fo2_ok = fo2
        if ico is not None and fco is not None and fco - ico < -5:
            quality.append("CO fell during test; likely sensor drift")
        out.append({
            "record_id": f"B2T-{i:03d}",
            "pi": _clean(col(r, "PI")),
            "test_number": _clean(col(r, "Test #")),
            "date": _clean(col(r, "Date")),
            "day_of_year": _clean(col(r, "GMT")),
            "sample_number": _clean(col(r, "Sample #")),
            "material": mat,
            "material_family": material_family(mat),
            "geometry": geometry(mat),
            "initial_o2_pct": _fmt(io2),
            "final_o2_pct": _fmt(fo2),
            "initial_co2_pct": _fmt(ico2),
            "final_co2_pct": _fmt(fco2),
            "initial_co_ppm": _fmt(ico),
            "final_co_ppm": _fmt(fco),
            "o2_consumed_pct": _fmt(round(io2 - fo2_ok, 3)) if io2 is not None and fo2_ok is not None else "",
            "co2_produced_pct": _fmt(round(fco2 - ico2, 3)) if ico2 is not None and fco2 is not None else "",
            "co_produced_ppm": _fmt(round(fco - ico, 1)) if ico is not None and fco is not None else "",
            "initial_air_cm_s": _fmt(air0),
            "flow_restrictors": _clean(col(r, "Flow restrictor")),
            "radiometer_gain": _clean(col(r, "Radiometer gain (1000 250 50 10)")),
            "outcome_flag": outcome_flag(fan + " " + air),
            "flow_log_notes": notes,
            "data_quality": "; ".join(quality) or "ok",
            "source": SRC_BASS2,
        })
    return out


def ingest_bass(src: Path) -> list[dict]:
    with open(src, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        mat = _clean(r.get("Fuel Sample Material"))
        if not mat or "clean" in mat.lower():  # skip maintenance rows such as 'SOOT Cleaning'
            continue
        out.append({
            "record_id": f"B1T-{len(out) + 1:03d}",
            "as_run_order": _clean(r.get("As Run Test #")),
            "test_number": _clean(r.get("Test #")),
            "date": _clean(r.get("Date")),
            "day_of_year": _clean(r.get("GMT")),
            "sample_number": _clean(r.get("Sample #")),
            "material": mat,
            "material_family": material_family(mat),
            "geometry": geometry(mat),
            "data_quality": date_check(_clean(r.get("Date")), _clean(r.get("GMT")), (2012, 2013)) or "ok",
            "source": SRC_BASS,
        })
    return out


def write(rows: list[dict], name: str):
    with open(DATA / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote data/{name} ({len(rows)} rows)")


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    write(ingest_bass2(Path(argv[1])), "bass2_instrumented_tests.csv")
    write(ingest_bass(Path(argv[2])), "bass_test_index.csv")


if __name__ == "__main__":
    main(sys.argv)
