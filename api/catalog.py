"""Investigation catalog: one record per NASA investigation, ranked by relevance to a target cabin atmosphere.

The ranking is a fixed, published formula, not a model, so anyone can see why an investigation ranks where it does.
The same formula runs in the dashboard (web/template.html, rankInvestigations) so the standalone page re-ranks
without a server; tests check the two agree on the presets.

Score (0-100) = weighted mean of six parts, each 0-1:
    fuel      (weight 3)  solid cabin material 1; smoke from heated materials 0.8; gas burner imitating a solid 0.6;
                          gas or liquid flame 0.3; dust 0
    oxygen    (weight 2)  1 if the target O2 lies inside the tested range, falling to 0 ten points outside; 0.25 if unknown
    pressure  (weight 2)  1 inside the tested range, falling to 0 at 30 kPa outside; 0.6 if lower pressures were
                          tested but not listed; 0.25 if unknown
    airflow   (weight 1)  1 if forced flow overlapped spacecraft ventilation (5-30 cm/s); 0.6 still air only; 0.25 unknown
    scale     (weight 1)  large fire 1; material sample 0.6; burner 0.4; droplet 0.3; none 0.3
    data      (weight 1)  per-test data in BurnBook 1; summary 0.5; images or manifest 0.25; none 0
"""
from __future__ import annotations

from .data import _num, _read

PSI_TO_KPA = 6.894757
WEIGHTS = {"fuel": 3, "oxygen": 2, "pressure": 2, "airflow": 1, "scale": 1, "data": 1}
FUEL = {"solid_material": 1.0, "solid_material_smoke": 0.8, "gas_emulating_solid": 0.6, "gas_flame": 0.3,
        "liquid_droplet": 0.3, "dust": 0.0}
SCALE = {"large": 1.0, "sample": 0.6, "burner": 0.4, "droplet": 0.3, "none": 0.3}
DATA = {"full": 1.0, "summary": 0.5, "images": 0.25, "manifest": 0.25, "none": 0.0}
VENT = (5.0, 30.0)


def load() -> list[dict]:
    out = []
    for r in _read("investigations.csv"):
        out.append({
            "id": r["id"], "name": r["name"], "group": r["group"], "years": r["years"] or None,
            "platform": r["platform"], "facility": r["facility"] or None, "objective": r["objective"],
            "fuel_phase": r["fuel_phase"], "fuel_class": r["fuel_class"], "materials": r["materials"] or None,
            "geometry": r["geometry"] or None,
            "o2": [_num(r["o2_min"]), _num(r["o2_max"])], "pressure_kpa": [_num(r["p_min_kpa"]), _num(r["p_max_kpa"])],
            "flow_cm_s": [_num(r["flow_min_cm_s"]), _num(r["flow_max_cm_s"])],
            "quiescent": {"yes": True, "no": False}.get(r["quiescent"]),
            "variables": r["variables"] or None, "sensors": r["sensors"] or None, "scale": r["scale"],
            "data_level": r["data_level"], "in_burnbook": r["in_burnbook"] or None, "api": r["api"] or None,
            "claims": [c for c in r["claims"].split(";") if c], "sources": r["sources"], "unknowns": r["unknowns"] or None,
        })
    return out


def _range_score(target: float, lo, hi, fall: float) -> float:
    if lo is None and hi is None:
        return 0.25
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    gap = max(0.0, lo - target, target - hi)
    return max(0.0, 1.0 - gap / fall)


def parts(inv: dict, o2: float, kpa: float) -> dict:
    plo, phi = inv["pressure_kpa"]
    if plo is None and phi is not None:
        pressure = 0.6 if kpa <= phi else max(0.0, 1 - (kpa - phi) / 30)  # reduced pressures tested, values not listed
    else:
        pressure = _range_score(kpa, plo, phi, 30.0)
    flo, fhi = inv["flow_cm_s"]
    if flo is not None and fhi is not None and fhi >= VENT[0] and flo <= VENT[1]:
        airflow = 1.0
    elif inv["quiescent"]:
        airflow = 0.6
    else:
        airflow = 0.25
    return {
        "fuel": FUEL.get(inv["fuel_class"], 0.0),
        "oxygen": _range_score(o2, inv["o2"][0], inv["o2"][1], 10.0),
        "pressure": pressure,
        "airflow": airflow,
        "scale": SCALE.get(inv["scale"], 0.3),
        "data": DATA.get(inv["data_level"], 0.0),
    }


def score(inv: dict, o2: float, kpa: float) -> tuple[float, dict]:
    p = parts(inv, o2, kpa)
    total = sum(WEIGHTS[k] * v for k, v in p.items()) / sum(WEIGHTS.values())
    return round(100 * total, 1), {k: round(v, 3) for k, v in p.items()}


def rank(o2: float, psia: float) -> list[dict]:
    kpa = psia * PSI_TO_KPA
    rows = []
    for inv in load():
        s, p = score(inv, o2, kpa)
        rows.append({**inv, "score": s, "parts": p})
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _rng(a, b, unit):
    if a is None and b is None:
        return None
    if a is None or b is None or a == b:
        return f"{a if a is not None else b:g} {unit}"
    return f"{a:g} to {b:g} {unit}"


def template_summary(inv: dict) -> str:
    """Plain summary built only from catalog fields. Used when no language model is available."""
    bits = [f"{inv['name']} ({inv['years'] or 'years not in our sources'}, {inv['platform']}): {inv['objective'].rstrip('.')}."]
    tested = [x for x in (_rng(*inv["o2"], "% O2"), _rng(*inv["pressure_kpa"], "kPa"),
                          _rng(*inv["flow_cm_s"], "cm/s flow")) if x]
    if inv["quiescent"]:
        tested.append("still air")
    if inv["materials"]:
        bits.append(f"Fuels: {inv['materials']}.")
    if tested:
        bits.append("Tested: " + ", ".join(tested) + ".")
    bits.append(f"In BurnBook: {inv['in_burnbook']}." if inv["in_burnbook"] else "No data in BurnBook yet.")
    if inv["claims"]:
        bits.append("Evidence: " + ", ".join(inv["claims"]) + ".")
    if inv["unknowns"]:
        bits.append(f"Gaps: {inv['unknowns']}.")
    return " ".join(bits)


SUMMARY_SYSTEM = (
    "You summarise NASA microgravity combustion investigations for spacecraft fire-safety planners. "
    "Use ONLY the catalog record and evidence claims provided. Cite claim IDs in square brackets like [C-13]. "
    "Say plainly what the investigation does not tell us, using the record's gaps. Do not add numbers, dates or findings "
    "that are not in the input. Plain language, under 110 words, no headings or lists."
)


def summary_prompt(inv: dict, claims: list[dict], o2: float | None = None, psia: float | None = None) -> str:
    rec = {k: inv[k] for k in ("name", "years", "platform", "facility", "objective", "materials", "geometry", "o2",
                               "pressure_kpa", "flow_cm_s", "quiescent", "variables", "sensors", "in_burnbook", "unknowns")}
    lines = [f"Catalog record: {rec}"]
    if claims:
        lines.append("Evidence claims:")
        lines += [f"[{c['id']}] {c['claim']} (conditions: {c['conditions']}; caveat: {c['caveat']})" for c in claims]
    if o2 is not None and psia is not None:
        lines.append(f"The reader's target cabin atmosphere is {o2:g}% O2 at {psia:g} psia ({psia * PSI_TO_KPA:.0f} kPa). "
                     "Say in one sentence how relevant this investigation is to that atmosphere, based only on the tested ranges.")
    return "\n".join(lines)
