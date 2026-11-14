"""Load the BurnBook datasets from CSV and expose them as plain dicts for the API."""
from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Spacecraft-atmosphere safety limits quoted in the Saffire VI presentation (slide 20)
SAFFIRE_LIMITS = {"co2_1h_mmhg": 3.0, "co_1h_ppm": 425.0, "co_24h_ppm": 100.0}  # CO: JSC 20584 Rev C (2024), C-48; CO2: Saffire VI slide


def _read(name: str) -> list[dict]:
    with open(DATA_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v, default=None):
    if v is None:
        return default
    v = str(v).strip()
    if v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def load_limits() -> list[dict]:
    rows = []
    for r in _read("flammability_limits_olson2008.csv"):
        table_delta = _num(r["delta_o2_0g_minus_1g_computed_from_table"])
        text_raw = (r.get("delta_o2_reported_in_text") or "").strip()
        text_delta = _num(text_raw)
        rows.append({
            "id": r["record_id"],
            "fuel": r["fuel"],
            "description": r["fuel_description"],
            "pressure_psia": _num(r["pressure_psia"]),
            "flow_cm_s": _num(r["concurrent_flow_0g_cm_s"]),
            "ulo_1g": _num(r["ulo_1g_pct_o2"]),
            "moc_1g": _num(r["moc_1g_pct_o2"]),
            "ulo_0g": _num(r["ulo_0g_pct_o2_burns"]),
            "moc_0g": _num(r["moc_0g_pct_o2_extinguishes"]),
            "delta_from_table": table_delta,
            "delta_reported_in_text": text_raw or None,
            "discrepancy": text_delta is not None and table_delta is not None and abs(text_delta - table_delta) > 0.05,
            "notes": r["notes"],
        })
    return rows


def load_saffire() -> list[dict]:
    rows = []
    for r in _read("saffire_large_scale_tests.csv"):
        rows.append({
            "id": r["record_id"],
            "flight": r["flight_sample"],
            "material": r["material"],
            "length_cm": _num(r["sample_length_cm"]),
            "flow_cm_s": _num(r["flow_cm_s"]),
            "direction": r["flow_direction"],
            "pressure_kpa": _num(r["pressure_kpa"]),
            "o2_pct": _num(r["o2_mol_pct"]),
            "free_volume_m3": _num(r["free_volume_m3"]),
            "burn_s": _num(r["burn_duration_s"]),
            "peak_hrr_w": _num(r["peak_heat_release_w_o2_calorimetry"]),
            "avg_hrr_w": _num(r["avg_heat_release_w_fuel_calorimetry"]),
            "total_kj": _num(r["total_heat_release_kj_o2_calorimetry"]) or _num(r["total_heat_release_kj_fuel_calorimetry"]),
            "max_temp_c": _num(r["max_temp_c_at_flow_unit_outlet"]),
            "co2_mmhg": _num(r["co2_partial_pressure_increase_mmhg"]),
            "co_ppm": _num(r["co_increase_ppm"]),
            "exceeds_co2_1h": r["exceeds_co2_1h_limit"].strip().lower() == "yes",
            "exceeds_co_24h": r["exceeds_co_24h_limit"].strip().lower() == "yes",
            "notes": r["notes"],
        })
    return rows


def load_bass_points() -> list[dict]:
    return [
        {
            "id": r["point_id"],
            "cls": r["outcome_class"],
            "stretch": _num(r["forced_stretch_rate_1_per_s"]),
            "o2": _num(r["final_o2_vol_pct"]),
            "method": r["extraction_method"],
        }
        for r in _read("bass2_boundary_points_digitized_PARTIAL.csv")
    ]


def load_bass2_tests() -> list[dict]:
    """BASS-II ISS glovebox tests (PSI-25 table): chamber O2/CO2/CO before and after each burn.
    outcome is a keyword match over the free-text flow log; blank means the log does not say."""
    return [
        {
            "id": r["record_id"],
            "pi": r["pi"],
            "test": r["test_number"],
            "date": r["date"],
            "sample": r["sample_number"],
            "material": r["material"],
            "family": r["material_family"],
            "geometry": r["geometry"],
            "o2_initial": _num(r["initial_o2_pct"]),
            "o2_final": _num(r["final_o2_pct"]),
            "co2_initial": _num(r["initial_co2_pct"]),
            "co2_final": _num(r["final_co2_pct"]),
            "co_initial": _num(r["initial_co_ppm"]),
            "co_final": _num(r["final_co_ppm"]),
            "o2_consumed": _num(r["o2_consumed_pct"]),
            "co2_produced": _num(r["co2_produced_pct"]),
            "co_produced": _num(r["co_produced_ppm"]),
            "air_cm_s": _num(r["initial_air_cm_s"]),
            "restrictors": _num(r["flow_restrictors"]),
            "rad_gain": r["radiometer_gain"],
            "outcome": r["outcome_flag"] or None,
            "flow_log": r["flow_log_notes"],
            "quality": r["data_quality"],
        }
        for r in _read("bass2_instrumented_tests.csv")
    ]


def load_bass_index() -> list[dict]:
    """BASS (2012) test manifest (PSI-26 table): which sample was burned when. No measurements."""
    return [
        {
            "id": r["record_id"],
            "test": r["test_number"],
            "run_order": r["as_run_order"],
            "date": r["date"],
            "sample": r["sample_number"],
            "material": r["material"],
            "family": r["material_family"],
            "geometry": r["geometry"],
            "quality": r["data_quality"],
        }
        for r in _read("bass_test_index.csv")
    ]


def _quartiles(vals: list[float]) -> dict | None:
    if len(vals) < 4:
        return None
    s = sorted(vals)
    q = lambda p: s[min(len(s) - 1, int(round(p * (len(s) - 1))))]  # noqa: E731 - nearest-rank is enough here
    return {"n": len(s), "q1": round(q(0.25), 3), "median": round(q(0.5), 3), "q3": round(q(0.75), 3)}


def bass2_summary(tests: list[dict] | None = None) -> dict:
    """Cross-checks computed from the raw table, kept separate from the published numbers."""
    tests = tests if tests is not None else load_bass2_tests()
    by_outcome, by_family = {}, {}
    for t in tests:
        by_outcome[t["outcome"] or "not stated"] = by_outcome.get(t["outcome"] or "not stated", 0) + 1
        by_family[t["family"]] = by_family.get(t["family"], 0) + 1
    # only burns that moved O2 by at least 0.3% give a ratio that is not dominated by sensor resolution (0.1%)
    ratio = [t["co2_produced"] / t["o2_consumed"] for t in tests
             if t["o2_consumed"] and t["co2_produced"] and t["o2_consumed"] >= 0.3 and t["co2_produced"] > 0]
    co_per_co2 = [t["co_produced"] / (t["co2_produced"] * 1e4) for t in tests
                  if t["co_produced"] is not None and t["co2_produced"] and t["co2_produced"] >= 0.2]
    o2 = [t["o2_initial"] for t in tests if t["o2_initial"] is not None]
    lowest_burn = {}
    for t in tests:
        if t["o2_initial"] is None or t["outcome"] == "no_ignition" or not t["co2_produced"] or t["co2_produced"] < 0.05:
            continue  # count a test as a burn only if it made measurable CO2
        f = t["family"]
        if f not in lowest_burn or t["o2_initial"] < lowest_burn[f]["o2"]:
            lowest_burn[f] = {"o2": t["o2_initial"], "id": t["id"], "material": t["material"]}
    return {
        "tests": len(tests),
        "flagged_rows": sum(1 for t in tests if t["quality"] != "ok"),
        "by_outcome": by_outcome,
        "by_family": by_family,
        "initial_o2_range": [min(o2), max(o2)] if o2 else None,
        "co2_per_o2_consumed": _quartiles(ratio),
        "co2_per_o2_published": {"value": round(5 / 6, 3), "basis": "O2:CO2 about 6:5 (BASS-II Summary Report, Fig. 1.3)"},
        "co_per_co2_molar": _quartiles(co_per_co2),
        "lowest_o2_with_measurable_burn": lowest_burn,
        "method": ("Ratios use tests where O2 fell at least 0.3% and CO2 rose; rows whose final O2 is not physical are "
                   "excluded. 'Burn' means CO2 rose at least 0.05%. These are checks on the raw table, not new results."),
    }


WEB_IMG = Path(__file__).resolve().parent.parent / "web" / "img"


def load_gallery(embed: bool = True) -> list[dict]:
    """ISS flame photos (NASA, public domain) with captions. Images are embedded as data URIs so the
    standalone page needs no other files."""
    import base64
    out = []
    for r in _read("gallery.csv"):
        is_iss_photo = r["nasa_id"].startswith("iss")
        item = {"id": r["nasa_id"], "expedition": int(r["expedition"]) if r["expedition"] else None,
                "year": int(r["year"]), "date": r.get("date") or None,
                "investigation": r["investigation"], "caption": r["caption"],
                "claims": [c for c in r["claims"].split(";") if c],
                "credit": f"NASA, ISS photo {r['nasa_id']}" if is_iss_photo else "NASA, ACME camera image"}
        sid = r.get("soot_id")
        sc = next((x for x in _read("soot_scores.csv") if x["image_id"] == sid), None) if sid else None
        item["soot_score"] = _num(sc["soot_score"]) if sc else None
        if embed:
            item["src"] = "data:image/jpeg;base64," + base64.b64encode((WEB_IMG / r["file"]).read_bytes()).decode()
        out.append(item)
    return out


def load_soot(embed: bool = True) -> dict:
    """Soot scores from scripts/soot_score.py: share of flame pixels that glow yellow/orange/white rather than blue."""
    import base64
    scores = [{"id": r["image_id"], "set": r["image_set"], "investigation": r["investigation"], "date": r["date"],
               "score": _num(r["soot_score"]), "flame_px": int(r["flame_px"]),
               "unclassified": _num(r["unclassified_frac"]), "excluded": r["excluded_because"] or None}
              for r in _read("soot_scores.csv")]
    out = {"scores": scores,
           "method": "Image processing, not AI. Pixels brighter than 20% are flame; yellow, orange, red or white ones count as soot, "
                     "cyan to blue ones as blue. Score = soot pixels / (soot + blue). Compare within one camera set: exposure and "
                     "white balance differ between cameras, and saturated cores read as white. It measures area, not brightness."}
    ex = WEB_IMG / "soot_method_example.jpg"
    if embed and ex.exists():
        out["example_src"] = "data:image/jpeg;base64," + base64.b64encode(ex.read_bytes()).decode()
    return out


def load_saffire2() -> list[dict]:
    """Saffire-II small samples (PSI-99): the same material burned in microgravity on Cygnus and in 1g."""
    return [
        {
            "id": r["record_id"], "sample": r["sample"], "material": r["material"],
            "material_inferred": r["material_inferred"] == "yes",
            "thickness_mm": _num(r["thickness_mm"]), "thickness_as_printed": r["thickness_as_printed"],
            "direction": r["flow_direction"], "o2": r["o2_pct_note1"],
            "ignition_w": _num(r["ignition_w"]), "ignition_s": _num(r["ignition_s"]),
            "burn_s": _num(r["burn_time_s"]), "burn_as_printed": r["burn_time_as_printed"],
            "ug_burn": r["ug_burn_length"], "ug_rate_mm_s": _num(r["ug_spread_mm_s"]),
            "g1_burn": r["g1_burn_length"], "g1_rate": r["g1_spread_mm_s"],
            "notes": r["notes"],
            "sensors": _saffire2_sensor_brief(r["sample"]),
        }
        for r in _read("saffire2_flammability.csv")
    ]


def _saffire2_sensor_brief(sample: str) -> dict | None:
    """Key numbers from a Saffire-II sensor record, if loaded: CO2 rise, how long radiometers saw flame, hottest sample TC."""
    rec = load_saffire_sensors(f"saffire2_s{sample.split('-')[-1]}", series=False)
    if not rec:
        return None
    sm = rec["summary"]
    co2 = sm["gas"]["co2_pct"]
    windows = [v["above_baseline_s"] for v in sm["radiometers"].values() if v["above_baseline_s"]]
    seen = round(max(b - a for a, b in windows)) if windows else 0
    return {"record": rec["record"], "pressure_psia": sm["pressure_psia"]["mean"],
            "co2_rise_ppm": round((co2["max_after"] - co2["pre_ignition"]) * 1e4),
            "radiometer_seen_s": seen, "peak_sample_tc_c": max(sm["sample_tc_peak_c"].values()),
            "igniter_s": round(sm["igniter"]["off_s"] - sm["igniter"]["on_s"], 1)}


def load_acme() -> dict:
    """ACME BRE and CLD Flame test-day tables (PSI-20, PSI-21) and CFI-G per-test flames (PSI-159)."""
    bre = [{"id": r["record_id"], "date": r["date"], "burner_mm": _num(r["burner_mm"]), "fuel": r["fuel"],
            "o2_levels": [_num(x) for x in r["o2_levels_pct"].split(";") if x.strip()],
            "flames_ignited": int(r["flames_ignited"]), "quality": r["data_quality"]}
           for r in _read("acme_bre_test_days.csv")]
    cld = [{"id": r["record_id"], "date": r["date"], "type": r["test_type"], "fuel": r["fuel_bottle"],
            "fuel_conc": r["fuel_conc_range"], "flames_ignited": int(r["flames_ignited"]), "quality": r["data_quality"]}
           for r in _read("acme_cld_test_days.csv")]
    cfig = [{"id": r["record_id"], "type": r["flame_type"], "fuel": r["fuel"], "test": r["test"],
             "o2_ambient": _num(r["o2_ambient"]), "o2_burner": _num(r["o2_burner"]), "pressure_bar": _num(r["pressure_bar"]),
             "fuel_rate_mg_s": _num(r["fuel_rate_mg_s"]), "ignited": r["hot_ignition"], "burn_s": _num(r["burn_s"]),
             "ended_by": r["ended_by"] or None, "cool_flame": r["cool_flame"] or None, "comments": r["comments"],
             "quality": r["data_quality"]}
            for r in _read("cfig_flames.csv")]
    return {"bre": bre, "cld": cld, "cfig": cfig, "cfig_summary": cfig_summary(cfig)}


def cfig_summary(cfig: list[dict]) -> dict:
    """How long hot normal flames lasted, grouped by ambient O2. Flames stopped by cutting the fuel are lower bounds."""
    bands = [("about 18%", 0.0, 0.19), ("about 21%", 0.19, 0.22), ("about 23%", 0.22, 0.30), ("33 to 40%", 0.30, 1.0)]
    out = []
    for label, lo, hi in bands:
        tests = [t for t in cfig if t["type"] == "normal" and t["o2_ambient"] is not None and lo <= t["o2_ambient"] < hi]
        lit = [t for t in tests if t["ignited"] == "yes" and t["burn_s"]]
        se = sorted(t["burn_s"] for t in lit if t["ended_by"] == "self-extinguished")
        ft = sorted(t["burn_s"] for t in lit if t["ended_by"] == "fuel flow stopped")
        med = (se[len(se) // 2] if len(se) % 2 else (se[len(se) // 2 - 1] + se[len(se) // 2]) / 2) if se else None
        out.append({"o2_band": label, "tests": len(tests), "ignited": len(lit), "self_extinguished": len(se),
                    "median_self_ext_s": med, "max_self_ext_s": se[-1] if se else None,
                    "still_burning_when_fuel_cut": len(ft), "max_still_burning_s": ft[-1] if ft else None})
    cool = [t for t in cfig if t["cool_flame"] == "yes"]
    return {"by_o2": out, "cool_flames": len(cool),
            "cool_flame_conditions": sorted({f"{t['fuel']}, {t['pressure_bar']:g} bar, O2 {t['o2_ambient']:.2f}" for t in cool}),
            "method": "Normal flames only (fuel through the burner into the chamber air). "
                      "Fuel type, dilution and flow rate also differ between tests, so the O2 bands are not a controlled comparison."}


def load_saffire_sensors(record: str, series: bool = True) -> dict | None:
    """A Saffire sensor record: 1 s means from scripts/ingest_saffire_sensors.py (Saffire-I, II), or 10 s bins of
    housekeeping telemetry from scripts/ingest_saffire3_telemetry.py (record 'saffire3'), plus a summary."""
    import json
    summ = DATA_DIR / f"{record}_sensors_summary.json"
    if not record.replace("_", "").isalnum() or not summ.exists():
        return None
    out = {"record": record, "summary": json.loads(summ.read_text())}
    if series:
        name = f"{record}_sensors_1hz.csv" if (DATA_DIR / f"{record}_sensors_1hz.csv").exists() else f"{record}_sensors.csv"
        out["series"] = [{k: _num(v) for k, v in r.items()} for r in _read(name)]
    return out


def load_flex() -> list[dict]:
    """ISS FLEX droplet tests (PSI-69), cleaned by scripts/ingest_flex.py. Mole fractions; pressure in kPa."""
    return [
        {"id": r["record_id"], "identifier": r["identifier"], "date": r["date"], "fuel": r["fuel"],
         "pressure_kpa": _num(r["pressure_kpa"]), "x_o2": _num(r["x_o2"]), "x_n2": _num(r["x_n2"]),
         "x_co2": _num(r["x_co2"]), "x_he": _num(r["x_he"]), "diluent": r["diluent"], "d0_mm": _num(r["d0_mm"]),
         "dext_mm": _num(r["dext_mm"]), "k_mm2_s": _num(r["burning_rate_mm2_s"]), "burn_s": _num(r["burn_time_s"]),
         "fraction_burned": _num(r["fraction_burned"]), "end": r["test_end"], "quality": r["data_quality"]}
        for r in _read("flex_tests.csv")
    ]


def load_cfi() -> list[dict]:
    """ISS CFI droplet tests (FLEX-1206 to 1431), cleaned by scripts/ingest_cfi.py from the NASA CFI data summary."""
    return [
        {"id": r["record_id"], "flex_number": r["flex_number"], "date": r["date"], "cir_id": r["cir_id"],
         "pressure_atm": _num(r["pressure_atm"]), "pressure_kpa": _num(r["pressure_kpa"]), "x_o2": _num(r["x_o2"]),
         "x_n2": _num(r["x_n2"]), "x_he": _num(r["x_he"]), "fiber": r["fiber"] or None, "fuel": r["fuel"],
         "d0_mm": _num(r["d0_mm"]), "dext_hot_mm": _num(r["dext_hot_mm"]), "k_hot_mm2_s": _num(r["k_hot_mm2_s"]),
         "k_cool_mm2_s": _num(r["k_cool_mm2_s"]), "dext_cool_mm": _num(r["dext_cool_mm"]),
         "reignitions": _num(r["reignitions"]), "hot_flame_burn_s": _num(r["hot_flame_burn_s"]),
         "analysed": r["analysis_completed"] == "yes", "comments": r["comments"], "quality": r["data_quality"]}
        for r in _read("cfi_tests.csv")
    ]


def load_spice() -> list[dict]:
    """Published laminar smoke points, ethylene from a 1.6 mm burner (DeBold 2012 thesis, Appendix 5.1)."""
    return [
        {
            "id": r["record_id"],
            "fuel": r["fuel"],
            "nozzle_mm": _num(r["nozzle_mm"]),
            "gmt_day": int(r["gmt_day"]),
            "time": r["time_observed"],
            "campaign": r["campaign"],
            "fuel_velocity_cm_s": _num(r["fuel_velocity_cm_s"]),
            "mass_flow_mg_s": _num(r["mass_flow_mg_s"]),
            "coflow_cm_s": _num(r["coflow_cm_s"]),
            "length_mm": _num(r["smoke_point_length_mm"]),
            "reynolds": _num(r["reynolds_number"]),
        }
        for r in _read("spice_smoke_points.csv")
    ]


def load_spice_frames() -> list[dict]:
    """BurnBook's own flame-length measurements from SPICE test-day 045 video frames (ethylene, 1.6 mm)."""
    return [
        {
            "frame": r["frame"], "kind": r["kind"], "time": r["time_gmt"],
            "fuel_display": _num(r["fuel_display"]), "air_display": _num(r["air_display"]),
            "fan_display": _num(r["fan_display"]), "rad_display": _num(r["rad_display"]),
            "luminous_mm": _num(r["luminous_length_mm"]), "core_mm": _num(r["white_core_length_mm"]),
            "notes": r["notes"],
        }
        for r in _read("spice_video_frames.csv")
    ]


def spice_video_check() -> dict:
    """Compare our measured length near the smoke point with the published value for the same test day."""
    pub = next(p for p in load_spice() if p["gmt_day"] == 45 and p["coflow_cm_s"] and p["coflow_cm_s"] > 50)
    ours = next(f for f in load_spice_frames() if f["frame"] == "slide_3")
    return {
        "published": {"id": pub["id"], "length_mm": pub["length_mm"], "mass_flow_mg_s": pub["mass_flow_mg_s"],
                      "coflow_cm_s": pub["coflow_cm_s"], "time": pub["time"]},
        "measured": {"frame": ours["frame"], "length_mm": ours["luminous_mm"], "fuel_display": ours["fuel_display"],
                     "air_display": ours["air_display"], "time": ours["time"]},
        "difference_mm": round(ours["luminous_mm"] - pub["length_mm"], 1),
        "caveats": [
            "Our scale is 4.93 px/mm from the ruler frames; the thesis used 4.80 px/mm (336.02 px per 70 mm) and a 50% intensity edge, so expect a few percent difference.",
            "The thesis logs this smoke point at 15:00:23 but the slide labels it GMT 15:03 and the frame near the smoke point is stamped 15:02:29; the 15:00:24 frame shows a 47 mm flame. The clocks may differ.",
            "The overlay AIR reading (68-72) is higher than the published coflow (58.02 cm/s); the published value comes from the calibrated fan setting.",
            "FUEL 283 x 0.60 (the controller's ethylene K-factor) is about 170 sccm of ethylene, roughly 3.3 to 3.5 mg/s depending on the standard temperature, consistent with the published 3.31 mg/s.",
        ],
    }


def load_history() -> dict:
    """Past spacecraft fires (Apollo 1, Apollo 13) from NASA pages, with links to BurnBook claims; data/history.json."""
    import json
    return json.loads((DATA_DIR / "history.json").read_text(encoding="utf-8"))


def load_evidence() -> list[dict]:
    return [
        {
            "id": r["claim_id"],
            "topic": r["topic"],
            "claim": r["claim"],
            "conditions": r["conditions"],
            "source": r["source"],
            "location": r["location"],
            "evidence_type": r["evidence_type"],
            "caveat": r["confidence_note"],
        }
        for r in _read("evidence_claims.csv")
    ]


def load_discrete() -> list[dict]:
    return [
        {
            "id": r["record_id"],
            "segment_cm": _num(r["segment_length_cm"]),
            "gap_cm": _num(r["gap_size_cm"]),
            "fuel_ratio": _num(r["fuel_ratio"]),
            "outcome": r["spread_outcome"],
            "spread_cm_s": _num(r["spread_rate_cm_s"]),
        }
        for r in _read("discrete_fuel_flame_spread_seed.csv")
    ]


# Microgravity test platforms. Durations and gravity levels come from NASA TM-101424 (1989)
# pp. 1-3 where stated; "approx" marks levels read only from that memo's Fig. 1 or inferred.
PLATFORMS = [
    {"id": "tower22", "name": "2.2 s drop tower", "seconds": 2.2, "g": 1e-5, "approx": True,
     "note": "Low cost, fast turnaround; g-level not given in memo text"},
    {"id": "zgf", "name": "5.18 s Zero Gravity Facility", "seconds": 5.18, "g": 1e-6, "approx": False,
     "note": "132 m evacuated drop; about 1e-6 g stated in memo"},
    {"id": "kc135", "name": "KC-135 aircraft", "seconds": 15.0, "g": 1e-3, "approx": False,
     "note": "5 to 15 s free-float at about 1e-3 g; up to 40 trajectories per flight"},
    {"id": "learjet", "name": "Learjet parabola (reduced g)", "seconds": 20.0, "g": 1e-2, "approx": False,
     "note": "Up to 20 s at about 1e-2 g; can be set to 1/6 g (lunar), 1/3 g (Mars-like) and others"},
    {"id": "rocket", "name": "Sounding rocket", "seconds": 300.0, "g": 1e-4, "approx": False,
     "note": "About 300 s at 1e-4 g; not yet used by the US combustion program in 1989"},
    {"id": "iss", "name": "ISS and Cygnus free-flyer", "seconds": 1.0e6, "g": 1e-6, "approx": True,
     "note": "Days to months; BASS-II (ISS glovebox) and Saffire IV-VI (Cygnus)"},
]
PARTIAL_G_TARGETS = [
    {"name": "Moon", "g": 0.166},
    {"name": "Mars", "g": 0.379},
]


def coverage() -> dict:
    counts = {
        "kimwipes_concurrent_spread": len(_read("kimwipes_concurrent_spread_digitized.csv")),
        "bass2_boundary_points": len(_read("bass2_boundary_points_digitized_PARTIAL.csv")),
        "saffire_large_scale_tests": len(_read("saffire_large_scale_tests.csv")),
        "discrete_fuel_flame_spread": len(_read("discrete_fuel_flame_spread_seed.csv")),
        "flammability_limits_fuels": len(_read("flammability_limits_olson2008.csv")),
        "bass2_instrumented_tests": len(_read("bass2_instrumented_tests.csv")),
        "bass_test_manifest": len(_read("bass_test_index.csv")),
        "spice_smoke_points": len(_read("spice_smoke_points.csv")),
        "flex_droplet_tests": len(_read("flex_tests.csv")),
        "cfi_test_conditions": len(_read("cfi_tests.csv")),
        "saffire2_small_samples": len(_read("saffire2_flammability.csv")),
        "acme_bre_test_days": len(_read("acme_bre_test_days.csv")),
        "acme_cld_test_days": len(_read("acme_cld_test_days.csv")),
        "cfig_flames": len(_read("cfig_flames.csv")),
        "soot_scored_images": sum(1 for r in _read("soot_scores.csv") if r["soot_score"]),
    }
    total = sum(counts.values())
    return {
        "platforms": PLATFORMS,
        "targets": PARTIAL_G_TARGETS,
        "record_counts": counts,
        "records_total": total,
        "records_at_partial_gravity": 0,
        "explanation": (
            "Every record comes from a drop tower, the ISS glovebox or a Cygnus free-flyer, all at roughly a millionth to a hundred-thousandth of Earth gravity. "
            "No record was measured at lunar (0.166 g) or Mars (0.379 g) gravity."
        ),
    }
