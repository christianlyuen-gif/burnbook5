"""Plain-assert tests for the BurnBook API. Run from burnbook/:  python -m pytest tests  (or: python tests/test_api.py)"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient  # noqa: E402

from api.main import app, INDEX  # noqa: E402
from api.search import ask  # noqa: E402
from api import kimwipes_model as km  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["claims"] == 53


def test_predict_in_range():
    j = client.get("/api/predict", params={"o2": 34, "flow": 5, "psia": 8.0}).json()
    assert j["in_tested_range"] is True
    assert abs(j["spread_rate_cm_s"] - 0.717) < 0.005
    assert j["lo95"] < j["spread_rate_cm_s"] < j["hi95"]


def test_predict_out_of_range_warns():
    j = client.get("/api/predict", params={"o2": 21, "flow": 20, "psia": 14.7}).json()
    assert j["in_tested_range"] is False
    assert any("o2_pct" in w for w in j["warnings"])


def test_predict_bad_input():
    assert client.get("/api/predict", params={"o2": "abc", "flow": 5, "psia": 8}).status_code == 422
    assert client.get("/api/predict", params={"flow": 5, "psia": 8}).status_code == 422
    assert client.get("/api/predict", params={"o2": 500, "flow": 5, "psia": 8}).status_code == 422


def test_curve_monotone_and_bounded():
    j = client.get("/api/curve", params={"o2": 30, "psia": 10.2, "n": 21}).json()
    v = [p["v"] for p in j["points"]]
    assert len(v) == 21 and all(b >= a for a, b in zip(v, v[1:]))
    assert all(p["lo"] <= p["v"] <= p["hi"] for p in j["points"])


def test_model_matches_module():
    j = client.get("/api/model").json()
    assert j["slope"] == km.SLOPE and j["intercept"] == km.INTERCEPT and len(j["points"]) == 22


def test_limits_flag_ultem_discrepancy():
    rows = client.get("/api/limits").json()
    assert {r["fuel"] for r in rows} >= {"Nomex", "Ultem", "Mylar"} or len(rows) == 3
    assert any(r["discrepancy"] for r in rows)


def test_coverage_zero_partial_gravity():
    j = client.get("/api/coverage").json()
    assert j["records_at_partial_gravity"] == 0
    assert j["records_total"] == sum(j["record_counts"].values())


def test_bundle_keys():
    j = client.get("/api/bundle").json()
    assert set(j) == {"model", "presets", "boundary", "limits", "saffire", "evidence", "coverage", "discrete", "bass2", "spice", "gallery", "acme", "soot", "catalog", "flex", "history"}
    assert len(j["evidence"]) == 53 and len(j["boundary"]["points"]) == 64
    assert len(j["bass2"]["tests"]) == 129


def test_bass2_records_and_quality_flags():
    j = client.get("/api/bass2").json()
    tests = j["tests"]
    assert len(tests) == 129 and {t["pi"] for t in tests} >= {"Olson", "Ferkul", "Bhattacharjee"}
    flagged = [t for t in tests if t["quality"] != "ok"]
    # rows with non-physical final O2 keep the raw value but never produce a derived O2 delta
    assert all(t["o2_consumed"] is None for t in flagged if "final O2" in t["quality"])
    assert all(t["o2_consumed"] is None or t["o2_consumed"] <= 6 for t in tests)
    ratio = j["summary"]["co2_per_o2_consumed"]
    assert 0.7 <= ratio["median"] <= 0.9  # near the 5/6 stoichiometric ratio the report shows in Fig 1.3
    # air speed is the duct transducer in cm/s; nothing may exceed the 55 cm/s duct maximum
    air = [t["air_cm_s"] for t in tests if t["air_cm_s"] is not None]
    assert len(air) >= 110 and max(air) <= 55


def test_bass2_filters_and_outcomes():
    rods_out = client.get("/api/bass2", params={"family": "pmma", "outcome": "no_ignition"}).json()["tests"]
    assert {t["id"] for t in rods_out} == {"B2T-061", "B2T-081"}
    assert all(t["pi"] == "Ferkul" for t in client.get("/api/bass2", params={"pi": "ferkul"}).json()["tests"])
    assert len(client.get("/api/bass").json()["tests"]) == 121


def test_spice_smoke_points_and_video_check():
    j = client.get("/api/spice").json()
    sp = j["smoke_points"]
    assert len(sp) == 11 and all(p["fuel"] == "Ethylene" and p["nozzle_mm"] == 1.6 for p in sp)
    # within one campaign, smoke point length rises with coflow
    d = sorted((p["coflow_cm_s"], p["length_mm"]) for p in sp if p["campaign"].startswith("ISS 2012"))
    assert all(b[1] > a[1] for a, b in zip(d, d[1:]))
    assert abs(j["video_check"]["difference_mm"]) < 3
    assert len(j["frames"]) == 16


def test_saffire_includes_saffire_one_without_gas_data():
    tests = client.get("/api/saffire").json()["tests"]
    s1 = {t["id"]: t for t in tests}
    assert {"SF-06", "SF-07"} <= set(s1) and s1["SF-06"]["co_ppm"] is None and s1["SF-06"]["length_cm"] == 94


def test_saffire2_space_vs_ground():
    f = client.get("/api/saffire").json()["flammability"]
    assert len(f) == 9
    silicone = [x for x in f if x["material"] == "Silicone"]
    assert len(silicone) == 4 and all(x["ug_burn"] == "~0" for x in silicone)
    assert {x["sample"] for x in f if x["material_inferred"]} == {"2-6", "2-9"}
    ids = {t["id"] for t in client.get("/api/saffire").json()["tests"]}
    assert {"SF-08", "SF-09"} <= ids
    sens = {x["sample"]: x["sensors"] for x in f}
    assert sens["2-9"]["co2_rise_ppm"] > 5 * sens["2-5"]["co2_rise_ppm"] and sens["2-9"]["igniter_s"] == 30.0
    assert sens["2-2"] is None and sens["2-7"]["peak_sample_tc_c"] > 300


def test_gallery_and_date_flags():
    g = client.get("/api/bundle").json()["gallery"]
    assert len(g) == 8 and all(x["src"].startswith("data:image/jpeg;base64,") for x in g)
    assert "src" not in client.get("/api/gallery").json()[0]
    flagged = {t["id"]: t["quality"] for t in client.get("/api/bass").json()["tests"] if t["quality"] != "ok"}
    assert "B1T-109" in flagged and "2103" in flagged["B1T-109"]


def test_acme_tables_and_cfig_summary():
    a = client.get("/api/acme").json()
    assert len(a["bre"]) == 18 and sum(d["flames_ignited"] for d in a["bre"]) == 194
    assert all("CH5" not in d["fuel"] and "C2H5" not in d["fuel"] for d in a["cld"])
    assert {d["id"] for d in a["bre"] if d["quality"] != "ok"} == {"BRE-05", "BRE-08"}
    by = {b["o2_band"]: b for b in a["cfig_summary"]["by_o2"]}
    assert by["about 21%"]["self_extinguished"] == by["about 21%"]["ignited"] == 37 and by["about 21%"]["max_self_ext_s"] <= 20
    assert by["33 to 40%"]["median_self_ext_s"] > 4 * by["about 21%"]["median_self_ext_s"]
    assert a["cfig_summary"]["cool_flames"] == 7


def test_soot_scores():
    s = client.get("/api/soot").json()["scores"]
    by = {x["id"]: x for x in s}
    assert len(s) == 62 and sum(1 for x in s if x["score"] is not None) == 27
    assert by["iss040e073120"]["score"] < 0.05 and by["acme_bre_19039a1"]["score"] > 0.9   # blue cap vs sooty dome
    assert all(x["score"] is None and x["excluded"] for x in s if x["set"].startswith("SPICE"))
    g = {x["id"]: x for x in client.get("/api/gallery").json()}
    assert g["acme_20190624b_flamedesign"]["soot_score"] == by["acme_sphere_19175b6_00061"]["score"]


def test_saffire1_sensor_record():
    j = client.get("/api/saffire/sensors", params={"record": "saffire1_s2"}).json()
    sm = j["summary"]
    assert 14.8 < sm["pressure_psia"]["mean"] < 14.95 and abs(sm["igniter"]["on_s"] - 60.03) < 0.05
    assert len(j["series"]) >= 650 and j["series"][0]["t_s"] == 0
    assert client.get("/api/saffire/sensors", params={"record": "../etc"}).status_code == 404
    s2 = client.get("/api/saffire/sensors", params={"record": "saffire2_s1", "series": "0"}).json()["summary"]
    assert 14.8 < s2["pressure_psia"]["mean"] < 14.95 and s2["igniter"]["median_power_w"] is None and s2["checks"]
    t = {x["id"]: x for x in client.get("/api/saffire").json()["tests"]}["SF-07"]
    assert t["co2_mmhg"] and t["co2_mmhg"] < 1 and t["co_ppm"] is None
    inv = {r["id"]: r for r in client.get("/api/investigations", params={"o2": 21, "psia": 14.7}).json()["investigations"]}
    assert inv["saffire-i"]["pressure_kpa"][0] > 102


def test_flex_table():
    t = client.get("/api/flex").json()["tests"]
    assert len(t) == 274 and {x["fuel"] for x in t} == {"methanol", "heptane"}
    p = [x["pressure_kpa"] for x in t if x["pressure_kpa"]]
    assert 70 < min(p) < 71 and 309 < max(p) < 310
    by = {x["id"]: x for x in t}
    assert by["FLEX-114"]["pressure_kpa"] is None and "0 mmHg" in by["FLEX-114"]["quality"]
    assert by["FLEX-236"]["identifier"] == "H04H201" and by["FLEX-236"]["x_o2"] == 0.17 and by["FLEX-236"]["x_he"] == 0.2
    he = client.get("/api/flex", params={"diluent": "N2+He"}).json()["tests"]
    assert he and all(x["x_he"] for x in he)
    inv = {r["id"]: r for r in client.get("/api/investigations", params={"o2": 21, "psia": 14.7}).json()["investigations"]}
    assert inv["flex"]["data_level"] == "full" and inv["flex"]["pressure_kpa"] == [70.2, 309.3]


def test_cfi_tests():
    t = client.get("/api/cfi").json()["tests"]
    by = {x["flex_number"]: x for x in t}
    assert len(t) == 227 and "1206" in by and "1431" in by and "1274A" in by
    assert sum(x["analysed"] for x in t) == 146 and all(x["d0_mm"] is None for x in t if x["fuel"] == "farnesane")
    assert by["1223"]["d0_mm"] == 4.04 and by["1223"]["dext_cool_mm"] == 0.392   # matches report Fig. 1
    assert "2.563" in by["1268"]["quality"]
    assert min(x["pressure_atm"] for x in t) == 0.5 and max(x["pressure_atm"] for x in t) == 5


def test_bass_report_claims_searchable():
    hits = client.get("/api/evidence", params={"q": "equivalence ratio fuel rich", "k": 3}).json()
    assert hits and hits[0]["id"] == "C-17"
    hits = client.get("/api/evidence", params={"q": "extinction velocity thickness", "k": 3}).json()
    assert hits and hits[0]["id"] == "C-20"


def test_evidence_search_and_topic():
    hits = client.get("/api/evidence", params={"q": "ground test conservative", "k": 3}).json()
    assert 0 < len(hits) <= 3 and hits[0]["score"] >= hits[-1]["score"]
    assert client.get("/api/evidence", params={"q": "zzzqqq"}).json() == []


def test_ask_retrieval_only(monkeypatch=None):
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BURNBOOK_OPENAI_MODEL"):
        os.environ.pop(k, None)
    r = client.post("/api/ask", json={"question": "Are ground flammability tests conservative for microgravity?"})
    j = r.json()
    assert r.status_code == 200 and j["mode"] == "retrieval_only" and j["citations"]
    assert len(j["evidence"]) == len(j["citations"])


def test_ask_validation():
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 422
    assert client.post("/api/ask", content=b"not json").status_code == 400


LLM_ENV = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BURNBOOK_OPENAI_API_KEY",
           "BURNBOOK_OPENAI_MODEL", "BURNBOOK_OPENAI_BASE_URL", "BURNBOOK_LLM", "BURNBOOK_PROVIDER"]


def _clear_llm_env():
    for k in LLM_ENV:
        os.environ.pop(k, None)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        import httpx
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)


def _patch_http(handler):
    """Replace httpx.post and time.sleep; returns a restore function and the call log."""
    import httpx
    import time as _t
    calls, real_post, real_sleep = [], httpx.post, _t.sleep
    def fake(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "body": json})
        return handler(url, headers or {}, json)
    httpx.post, _t.sleep = fake, (lambda s: None)
    def restore():
        httpx.post, _t.sleep = real_post, real_sleep
    return restore, calls


def test_ask_llm_path_and_fallback():
    ok = ask(INDEX, "flame spread flow velocity", llm_fn=lambda q, c: "Answer [C-01]")
    assert ok["mode"] == "llm" and ok["answer"].startswith("Answer")
    def boom(q, c):
        raise RuntimeError("down")
    fb = ask(INDEX, "flame spread flow velocity", llm_fn=boom)
    assert fb["mode"] == "retrieval_only" and "unavailable" in fb["note"]


def test_llm_fallback_chain_skips_overloaded_provider():
    from api import llm
    _clear_llm_env()
    os.environ.update(GEMINI_API_KEY="g-test", BURNBOOK_OPENAI_MODEL="some-model", BURNBOOK_OPENAI_API_KEY="o-test",
                      BURNBOOK_OPENAI_BASE_URL="https://example.test/v1", BURNBOOK_LLM="gemini,openai")
    def handler(url, headers, body):
        if "generativelanguage" in url:
            return _Resp(503, {"error": {"message": "overloaded"}})
        return _Resp(200, {"choices": [{"message": {"content": "From the fallback [C-01]"}}]})
    restore, calls = _patch_http(handler)
    try:
        res = llm.generate("sys", "prompt")
        assert res.provider == "openai" and res.model == "some-model" and "fallback" in res.text
        assert sum("generativelanguage" in c["url"] for c in calls) == 3   # first try plus two retries
        oc = [c for c in calls if c["url"] == "https://example.test/v1/chat/completions"][0]
        assert oc["headers"]["authorization"] == "Bearer o-test" and oc["body"]["model"] == "some-model"
        out = ask(INDEX, "flame spread flow velocity")
        assert out["mode"] == "llm" and out["provider"] == "openai:some-model"
    finally:
        restore(); _clear_llm_env()


def test_llm_non_transient_error_fails_fast_and_status_hides_keys():
    from api import llm
    _clear_llm_env()
    os.environ.update(GEMINI_API_KEY="secret-key-123")
    restore, calls = _patch_http(lambda url, h, b: _Resp(404, {"error": {"message": "model retired"}}))
    try:
        try:
            llm.generate("sys", "prompt")
            assert False, "should raise"
        except llm.LLMUnavailable as exc:
            assert "404" in str(exc) and "model retired" in str(exc)
        assert len(calls) == 1
        st = client.get("/api/llm").json()
        assert st["order"] == ["gemini"] and "secret-key-123" not in str(st)
        os.environ["BURNBOOK_LLM"] = "none"
        assert llm.order() == [] and not llm.available()
    finally:
        restore(); _clear_llm_env()


def test_catalog_ranking_and_api():
    j = client.get("/api/investigations", params={"o2": 30, "psia": 10.2}).json()
    inv = j["investigations"]
    ids = [r["id"] for r in inv]
    assert len(inv) == 21 and ids[0] == "saffire-iv-vi" and ids[-1] == "daft"
    assert {"bass", "bass-ii", "saffire-i", "saffire-ii", "saffire-iii", "spice", "slice", "flex", "flex-2", "same",
            "cfi", "cfi-g", "bre", "cld-flame", "e-field", "flame-design", "s-flame"} <= set(ids)
    w = j["weights"]
    for r in inv:   # the score is the published weighted mean of its parts
        assert abs(r["score"] - round(100 * sum(w[k] * v for k, v in r["parts"].items()) / sum(w.values()), 1)) < 0.11
    assert [r["rank"] for r in inv] == list(range(1, 22))
    solids = client.get("/api/investigations", params={"o2": 21, "psia": 14.7, "phase": "solid"}).json()["investigations"]
    assert solids and all(r["fuel_phase"] == "solid" for r in solids)
    assert client.get("/api/investigations", params={"o2": 500}).status_code == 422


def test_investigation_summary_template_and_llm():
    _clear_llm_env()
    r = client.post("/api/investigations/bass-ii/summary", json={"o2": 30, "psia": 10.2}).json()
    assert r["mode"] == "template" and "C-13" in r["citations"] and r["summary"].startswith("BASS-II")
    assert client.post("/api/investigations/nope/summary", json={}).status_code == 404
    os.environ.update(GEMINI_API_KEY="g-test")
    restore, calls = _patch_http(lambda url, h, b: _Resp(200, {"candidates": [{"content": {"parts": [{"text": "Summary [C-09]"}]}}]}))
    try:
        a = client.post("/api/investigations/saffire-iv-vi/summary", json={"o2": 30, "psia": 10.2}).json()
        b = client.post("/api/investigations/saffire-iv-vi/summary", json={"o2": 30, "psia": 10.2}).json()
        assert a["mode"] == "llm" and a["provider"].startswith("gemini:") and a == b and len(calls) == 1   # second call cached
        prompt = calls[0]["body"]["contents"][0]["parts"][0]["text"]
        assert "C-09" in prompt and "30% O2" in prompt
    finally:
        restore(); _clear_llm_env()


def test_ask_no_match():
    assert ask(INDEX, "qqqq zzzz")["mode"] == "no_match"

def test_bre_pressures_from_final_report():
    from api import catalog
    bre = next(i for i in catalog.load() if i["id"] == "bre")
    assert list(bre["pressure_kpa"]) == [56.5, 101.3] and list(bre["flow_cm_s"]) == [0.0, 0.0]
    assert "bre" in [r["id"] for r in catalog.rank(34, 8.2)[:4]]

def test_saffire3_telemetry_and_flex2_matrix():
    from api import catalog, data
    rec = data.load_saffire_sensors("saffire3")
    sm = rec["summary"]
    assert abs(sm["pressure_psia"]["pre_ignition"] - 13.985) < 0.01 and sm["smoke_scatter_v"]["peak"] > 50 * sm["smoke_scatter_v"]["baseline"]
    assert len(rec["series"]) > 500 and "smoke_scatter_v" in rec["series"][0]
    sf = {t["id"]: t for t in data.load_saffire()}
    assert 340 < sf["SF-08"]["burn_s"] < 380 and 1.4 < sf["SF-08"]["co2_mmhg"] < 1.7 and sf["SF-09"]["pressure_kpa"] == 99.7
    s1 = data.load_saffire_sensors("saffire3_s1", series=False)["summary"]
    assert s1["igniter"]["median_power_w"] is None and s1["sample_tc_peak_c"]["sample_tc11_c"] > 1000
    inv = {i["id"]: i for i in catalog.load()}
    assert list(inv["flex-2"]["o2"]) == [17.0, 30.0] and list(inv["saffire-iii"]["pressure_kpa"]) == [99.7, 99.7]

def test_history_events_link_to_real_claims():
    h = client.get("/api/history").json()
    assert [e["id"] for e in h["events"]] == ["apollo-1", "apollo-13"]
    ids = {c["id"] for c in client.get("/api/bundle").json()["evidence"]}
    for e in h["events"]:
        assert e["sources"] and all(s["url"].startswith("https://") for s in e["sources"])
        for link in e["links"]:
            assert set(link["claims"]) <= ids
    assert {"C-52", "C-53"} <= ids



if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f()
        print("ok ", f.__name__)
    print(len(fns), "passed")
