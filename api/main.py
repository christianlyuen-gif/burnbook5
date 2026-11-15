"""BurnBook API: microgravity fire-safety evidence, models and a small cited Q&A.

Run from the burnbook/ folder:  uvicorn api.main:app --reload
Then open http://127.0.0.1:8000/ for the dashboard and http://127.0.0.1:8000/api/bundle for the data.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import catalog, data, llm
from . import kimwipes_model as km
from .search import Index, ask as ask_question

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

EVIDENCE = data.load_evidence()
INDEX = Index(EVIDENCE)

PRESETS = [
    {"id": "iss", "name": "ISS cabin", "o2": 21.0, "psia": 14.7, "flow": 20.0,
     "note": "21% O2 at sea-level pressure; 20 cm/s is the ventilation speed used in Saffire tests"},
    {"id": "preeva", "name": "Pre-EVA cabin", "o2": 30.0, "psia": 10.2, "flow": 20.0,
     "note": "30% O2 at 10.2 psia, used briefly before spacewalks"},
    {"id": "explore", "name": "Exploration cabin", "o2": 34.0, "psia": 8.0, "flow": 20.0,
     "note": "Upper end of the planned 8.0 to 14.9 psia, up to 34% O2 envelope (Olson 2008)"},
    {"id": "lowflow", "name": "Exploration, weak ventilation", "o2": 34.0, "psia": 8.0, "flow": 5.0,
     "note": "Same atmosphere with flow cut to 5 cm/s, the low end of nominal ventilation"},
]

PUBLISHED_FITS = {
    "pmma_rod_quench": {"form": "O2 = A*exp(-D*a) + C", "A": 7.0, "D": 0.8, "C": 13.3},
    "pmma_rod_blowoff": {"form": "O2 = B*a + C", "B": 0.02, "C": 13.3},
    "pmma_rod_blowoff_drop_tower": {"form": "O2 = B*a + C", "B": 0.0181, "C": 13.42},
    "source": "Olson and Ferkul 2015, Fig. 4 legend",
}


class BadInput(ValueError):
    pass


def _param(request: Request, name: str, lo: float, hi: float, default: float | None = None) -> float:
    raw = request.query_params.get(name)
    if raw is None:
        if default is None:
            raise BadInput(f"Missing query parameter '{name}'")
        return default
    try:
        v = float(raw)
    except ValueError:
        raise BadInput(f"'{name}' must be a number, got '{raw}'")
    if not (lo <= v <= hi):
        raise BadInput(f"'{name}' must be between {lo} and {hi}, got {v}")
    return v


def model_info() -> dict:
    return {
        "name": "Kimwipes concurrent-flow flame spread",
        "scope": "Kimwipes thin cellulose, concurrent flow, microgravity only",
        "slope": km.SLOPE, "intercept": km.INTERCEPT,
        "sd_c0": km._C0, "sd_c1": km._C1, "sd_floor": km.SD_FLOOR, "t975": km.T975,
        "range": km.RANGE,
        "loo": km.loo_report(),
        "points": [{"x": x, "v": y, "category": c} for x, y, c in km.DIGITIZED],
        "source": "Olson, Ruff and Miller 2008 (NASA/TM-2008-215260), Fig. 7",
    }


async def health(request: Request):
    return JSONResponse({"status": "ok", "claims": len(EVIDENCE), "llm_order": llm.order()})


async def predict(request: Request):
    try:
        o2 = _param(request, "o2", 0.1, 100.0)
        flow = _param(request, "flow", 0.0, 200.0)
        psia = _param(request, "psia", 0.1, 30.0)
    except BadInput as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return JSONResponse({"inputs": {"o2_pct": o2, "flow_cm_s": flow, "pressure_psia": psia}, **km.predict(o2, flow, psia)})


async def curve(request: Request):
    try:
        o2 = _param(request, "o2", 0.1, 100.0)
        psia = _param(request, "psia", 0.1, 30.0)
        flow_max = _param(request, "flow_max", 5.0, 100.0, 40.0)
        n = int(_param(request, "n", 5, 400, 81))
    except BadInput as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    pts = []
    for f in np.linspace(0.0, flow_max, n):
        p = km.predict(o2, float(f), psia)
        pts.append({"flow": round(float(f), 3), "v": p["spread_rate_cm_s"], "lo": p["lo95"], "hi": p["hi95"],
                    "in_range": p["in_tested_range"]})
    return JSONResponse({"o2_pct": o2, "pressure_psia": psia, "points": pts})


async def model(request: Request):
    return JSONResponse(model_info())


async def presets(request: Request):
    return JSONResponse(PRESETS)


async def boundary(request: Request):
    return JSONResponse({"fits": PUBLISHED_FITS, "points": data.load_bass_points(),
                         "note": "Points were extracted from the published figure and are partial; use the published fits as the reference."})


BASS2_NOTE = ("BASS-II ISS glovebox tests from NASA PSI table PSI-25. O2, CO2 and CO are chamber readings before and "
              "after each burn. 'outcome' is a keyword match over the free-text flow log (blank = not stated). "
              "Rows with non-physical readings are flagged in 'quality' and left out of derived values.")


async def bass2(request: Request):
    tests = data.load_bass2_tests()
    family = request.query_params.get("family")
    pi = request.query_params.get("pi")
    outcome = request.query_params.get("outcome")
    if family:
        tests = [t for t in tests if t["family"].lower().startswith(family.lower())]
    if pi:
        tests = [t for t in tests if t["pi"].lower() == pi.lower()]
    if outcome:
        tests = [t for t in tests if (t["outcome"] or "not stated") == outcome]
    return JSONResponse({"tests": tests, "summary": data.bass2_summary(tests), "note": BASS2_NOTE})


async def bass_index(request: Request):
    return JSONResponse({"tests": data.load_bass_index(),
                         "note": "BASS (2012) manifest from NASA PSI table PSI-26: sample and material per test, no measurements."})


SPICE_NOTE = ("Laminar smoke points (the largest flame that does not release smoke) for ethylene from a 1.6 mm burner "
              "in ISS coflow, from DeBold 2012 Appendix 5.1, which includes Dotson's 2009 SPICE data. 'frames' are "
              "BurnBook's own length measurements from SPICE test-day 045 video, checked against the published value.")


def spice_payload() -> dict:
    return {"smoke_points": data.load_spice(), "frames": data.load_spice_frames(),
            "video_check": data.spice_video_check(), "note": SPICE_NOTE}


async def saffire_sensors(request: Request):
    rec = data.load_saffire_sensors(request.query_params.get("record", "saffire1_s2"),
                                    series=request.query_params.get("series", "1") != "0")
    if rec is None:
        avail = sorted(p.name.replace("_sensors_summary.json", "") for p in data.DATA_DIR.glob("*_sensors_summary.json"))
        return JSONResponse({"error": f"unknown sensor record; available: {', '.join(avail)}"}, status_code=404)
    return JSONResponse(rec)


async def replay(request: Request):
    return JSONResponse(data.load_replay())


async def history(request: Request):
    return JSONResponse(data.load_history())


async def flex(request: Request):
    tests = data.load_flex()
    for key in ("fuel", "diluent", "end"):
        v = request.query_params.get(key)
        if v:
            tests = [t for t in tests if (t[key] or "").lower() == v.lower()]
    return JSONResponse({"tests": tests, "note": "ISS FLEX droplet tests from NASA PSI table PSI-69. Gas fractions are mole fractions; "
                         "fraction_burned = 1 - (dext/d0)^2 (1 when the droplet burned to completion). See data_quality per row."})


async def cfi(request: Request):
    return JSONResponse({"tests": data.load_cfi(),
                         "note": "ISS CFI droplet tests FLEX-1206 to 1431 from the NASA CFI data summary (Jan 2021), conditions cross-checked "
                                 "against PSI-39. dext_cool_mm = 0 means the droplet burned out with no cool-flame extinction; farnesane not analysed."})


async def spice(request: Request):
    return JSONResponse(spice_payload())


async def soot(request: Request):
    return JSONResponse(data.load_soot(embed=request.query_params.get("embed") == "1"))


async def acme(request: Request):
    return JSONResponse(data.load_acme())


async def gallery(request: Request):
    return JSONResponse(data.load_gallery(embed=request.query_params.get("embed") == "1"))


async def limits(request: Request):
    return JSONResponse(data.load_limits())


async def saffire(request: Request):
    return JSONResponse({"tests": data.load_saffire(), "limits": data.SAFFIRE_LIMITS, "flammability": data.load_saffire2()})


async def evidence(request: Request):
    q = request.query_params.get("q", "").strip()
    topic = request.query_params.get("topic") or None
    if q:
        return JSONResponse(INDEX.search(q, k=int(request.query_params.get("k", 12)), topic=topic))
    return JSONResponse([c for c in EVIDENCE if not topic or c["topic"] == topic])


async def ask(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Send JSON like {\"question\": \"...\"}"}, status_code=400)
    question = str(body.get("question", "")).strip()
    if not (3 <= len(question) <= 500):
        return JSONResponse({"error": "question must be 3 to 500 characters"}, status_code=422)
    result = ask_question(INDEX, question)
    by_id = {c["id"]: c for c in EVIDENCE}
    result["evidence"] = [by_id[i] for i in result["citations"]]
    return JSONResponse(result)


_SUMMARY_CACHE: dict[tuple, dict] = {}


async def investigations(request: Request):
    try:
        o2 = _param(request, "o2", 5.0, 100.0, 21.0)
        psia = _param(request, "psia", 1.0, 30.0, 14.7)
    except BadInput as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    phase = request.query_params.get("phase")
    rows = catalog.rank(o2, psia)
    if phase:
        rows = [r for r in rows if r["fuel_phase"] == phase]
    return JSONResponse({"target": {"o2_pct": o2, "pressure_psia": psia, "pressure_kpa": round(psia * catalog.PSI_TO_KPA, 1)},
                         "weights": catalog.WEIGHTS, "method": catalog.__doc__.split("Score (0-100)")[1].strip(),
                         "investigations": rows})


async def investigation_summary(request: Request):
    """Plain-language summary of one investigation. Uses the configured language model if any; otherwise, or if
    every provider fails, a summary assembled from the catalog fields."""
    inv_id = request.path_params["inv_id"]
    inv = next((i for i in catalog.load() if i["id"] == inv_id), None)
    if inv is None:
        return JSONResponse({"error": f"unknown investigation '{inv_id}'"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    o2 = _num_or_none(body.get("o2"))
    psia = _num_or_none(body.get("psia"))
    by_id = {c["id"]: c for c in EVIDENCE}
    claims = [by_id[c] for c in inv["claims"] if c in by_id]
    base = {"id": inv_id, "citations": [c["id"] for c in claims], "fallback": catalog.template_summary(inv)}
    if not llm.available():
        return JSONResponse({**base, "mode": "template", "summary": base["fallback"],
                             "note": "No language model configured; summary built from the catalog fields."})
    key = (inv_id, o2, psia, tuple(llm.order()))
    if key in _SUMMARY_CACHE:
        return JSONResponse(_SUMMARY_CACHE[key])
    try:
        res = llm.generate(catalog.SUMMARY_SYSTEM, catalog.summary_prompt(inv, claims, o2, psia), max_tokens=350)
    except llm.LLMUnavailable as exc:
        return JSONResponse({**base, "mode": "template", "summary": base["fallback"],
                             "note": f"Language model unavailable ({exc}); summary built from the catalog fields."})
    out = {**base, "mode": "llm", "summary": res.text, "provider": res.label}
    _SUMMARY_CACHE[key] = out
    return JSONResponse(out)


def _num_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def llm_status(request: Request):
    return JSONResponse(llm.status())


async def coverage(request: Request):
    return JSONResponse(data.coverage())


async def bundle(request: Request):
    """Everything the dashboard needs in one call."""
    return JSONResponse({
        "model": model_info(),
        "presets": PRESETS,
        "boundary": {"fits": PUBLISHED_FITS, "points": data.load_bass_points()},
        "limits": data.load_limits(),
        "saffire": {"tests": data.load_saffire(), "limits": data.SAFFIRE_LIMITS, "flammability": data.load_saffire2()},
        "evidence": EVIDENCE,
        "coverage": data.coverage(),
        "discrete": data.load_discrete(),
        "bass2": {"tests": data.load_bass2_tests(), "summary": data.bass2_summary(), "note": BASS2_NOTE},
        "spice": spice_payload(),
        "flex": data.load_flex(),
        "history": data.load_history(),
        "replay": data.load_replay(),
        "gallery": data.load_gallery(),
        "acme": data.load_acme(),
        "soot": data.load_soot(),
        "catalog": {"investigations": [{**i, "template_summary": catalog.template_summary(i)} for i in catalog.load()],
                    "weights": catalog.WEIGHTS},
    })


async def index_page(request: Request):
    page = WEB_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"message": "Dashboard not built yet. Run python build_web.py", "api": "/api/bundle"})


routes = [
    Route("/", index_page),
    Route("/api/health", health),
    Route("/api/predict", predict),
    Route("/api/curve", curve),
    Route("/api/model", model),
    Route("/api/presets", presets),
    Route("/api/boundary", boundary),
    Route("/api/bass2", bass2),
    Route("/api/bass", bass_index),
    Route("/api/spice", spice),
    Route("/api/flex", flex),
    Route("/api/cfi", cfi),
    Route("/api/gallery", gallery),
    Route("/api/acme", acme),
    Route("/api/soot", soot),
    Route("/api/limits", limits),
    Route("/api/saffire", saffire),
    Route("/api/saffire/sensors", saffire_sensors),
    Route("/api/evidence", evidence),
    Route("/api/history", history),
    Route("/api/replay", replay),
    Route("/api/ask", ask, methods=["POST"]),
    Route("/api/investigations", investigations),
    Route("/api/investigations/{inv_id}/summary", investigation_summary, methods=["POST"]),
    Route("/api/llm", llm_status),
    Route("/api/coverage", coverage),
    Route("/api/bundle", bundle),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])],
)
