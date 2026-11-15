# BurnBook

Evidence board for microgravity fire safety: a spread-rate model, flammability boundaries, large-scale test results and a cited evidence base, behind a small API and a single-page dashboard.

##Website
The following is the link to the website hosted on render. The initial boot may take up to a minute for the server to turn on. Please be patient
https://burnbook-lpmz.onrender.com/

## Run it

```
pip install -r requirements.txt
python build_web.py                # embeds a data snapshot into web/index.html
uvicorn api.main:app --reload     # open http://127.0.0.1:8000/
python tests/test_api.py          # or: python -m pytest tests
```

The BASS and BASS-II tables are rebuilt from the raw NASA PSI downloads with
`python scripts/ingest_bass.py PSI-25_Experimental_table_BASS-II.csv PSI-26_Experimental_table_BASS.csv`, and the ACME and CFI-G tables with `python scripts/ingest_acme.py` (PSI-20, PSI-21 and the two PSI-159 files).


## API

| Route | Purpose |
|---|---|
| `GET /api/predict?o2=&flow=&psia=` | Kimwipes concurrent spread rate with 95% range and range warnings |
| `GET /api/curve?o2=&psia=` | Spread rate against flow |
| `GET /api/boundary`, `/api/limits`, `/api/saffire` | Data behind the charts; `/api/saffire` also returns the Saffire-II space-versus-ground table as `flammability` |
| `GET /api/saffire/sensors?record=saffire1_s2` (or `saffire2_s1`, `_s5`, `_s7`, `_s9`, `saffire3_s1`, `saffire3`) | A Saffire sensor record at 1 s (pressure, O2, CO2, radiometers, thermocouples) with a summary |
| `GET /api/bass2?family=&pi=&outcome=` | 129 BASS-II ISS tests: O2/CO2/CO before and after, outcome flags, raw-table cross-checks |
| `GET /api/bass` | BASS (2012) test manifest: sample and material per test |
| `GET /api/flex?fuel=&diluent=&end=` | 274 ISS FLEX droplet tests (methanol, heptane) with gas mix, pressure, sizes, burning rate and burn time |
| `GET /api/cfi` | 227 ISS CFI droplet tests: conditions for all, results (sizes, burning rates, re-ignitions) for the 146 analysed |
| `GET /api/spice` | 11 published ethylene smoke points (1.6 mm burner) plus BurnBook's video-frame measurements and a check against the published value |
| `GET /api/evidence?q=&topic=` | Keyword search over 53 sourced claims |
| `GET /api/history` | Apollo 1 and Apollo 13: what happened and what changed (from NASA pages), links to BurnBook claims, and Apollo-era versus current cabin atmospheres |
| `POST /api/ask` | `{"question": "..."}` returns a cited answer or matching evidence |
| `GET /api/acme` | ACME BRE and CLD Flame test days and 333 CFI-G flames, with a burn-time summary by oxygen level |
| `GET /api/soot` | Soot score for 62 flame images (27 scored), from `scripts/soot_score.py` |
| `GET /api/gallery` | Eight ISS flame images with captions (`?embed=1` includes the images) |
| `GET /api/investigations?o2=&psia=&phase=` | The investigation catalog, ranked for a target cabin atmosphere, with each score's parts |
| `POST /api/investigations/{id}/summary` | `{"o2":30,"psia":10.2}` returns a plain-language summary (language model, or catalog fields as fallback) |
| `GET /api/llm` | Which language-model providers are configured and in what order (never shows keys) |
| `GET /api/coverage` | Record counts and the partial-gravity gap |
| `GET /api/bundle` | Everything the dashboard needs |

## Language models

BurnBook never hard-codes a model. `api/llm.py` supports three provider types and tries them in the order you choose, moving to the next if one fails (rate limit, overload, retired model, bad key):

| Provider | Set these | Notes |
|---|---|---|
| `gemini` | `GEMINI_API_KEY`, optional `BURNBOOK_GEMINI_MODEL` (default gemini-3.8-flash) | Google AI Studio free tier |
| `anthropic` | `ANTHROPIC_API_KEY`, optional `BURNBOOK_ANTHROPIC_MODEL` | |
| `openai` | `BURNBOOK_OPENAI_MODEL`, `BURNBOOK_OPENAI_BASE_URL`, `BURNBOOK_OPENAI_API_KEY` | Any OpenAI-compatible service: OpenAI, Groq, OpenRouter, Together, Mistral, or a local Ollama / LM Studio (no key needed) |

```
# Gemini first, fall back to a local Ollama model if Gemini is overloaded
export GEMINI_API_KEY=...
export BURNBOOK_OPENAI_BASE_URL=http://localhost:11434/v1  BURNBOOK_OPENAI_MODEL=<model you pulled>
export BURNBOOK_LLM=gemini,openai

# Switch everything to an OpenAI-compatible host instead (e.g. Groq or OpenRouter)
export BURNBOOK_LLM=openai BURNBOOK_OPENAI_BASE_URL=<service's /v1 URL> BURNBOOK_OPENAI_MODEL=<model name> BURNBOOK_OPENAI_API_KEY=...

export BURNBOOK_LLM=none   # turn written answers off
```

Model names and free tiers change often, so the OpenAI-compatible provider has no default model; check the service's current model list and terms. Each provider retries HTTP 429/500/502/503/504 twice with a short backoff before the next provider is tried. Answers report which provider wrote them (`provider` in the JSON, shown under the answer on the page). Check `GET /api/llm` to confirm the setup.

## Investigation catalog

`data/investigations.csv` describes 21 investigations (every one named in the mission brief, plus the drop-tower studies BurnBook uses) by the brief's attributes: objective, fuel and sample or burner geometry, oxygen, pressure and airflow tested, what was varied, and sensors, with sources, gaps, linked claims and how much of its data BurnBook holds. Values come only from the sources listed in each row; anything our sources do not give is left blank and shown as "not stated".

The ranking (`api/catalog.py`, mirrored in the page so it re-ranks offline) is a fixed weighted score for the cabin atmosphere chosen in the scenario: fuel is a cabin material (x3), oxygen tested (x2), pressure tested (x2), ventilation-like airflow (x1), fire size (x1), data in BurnBook (x1). Each row shows its parts. A blank range scores 0.25 rather than zero, so a gap is penalised without being hidden. The language model only writes summaries; it never sets a rank.

## Scope and  notes

- The model is the published Olson 2008 line (V = 0.2498x + 0.4038, x = O2 fraction × flow × √pressure) plus an uncertainty band fit to 22 digitized points. It covers Kimwipes, concurrent flow, microgravity only, and warns outside O2 24–85%, flow 0–30 cm/s, 3.6–14.7 psia.
- The PMMA boundary points are partial figure traces; the published fits are the reference.
- The Ultem 0 g shift differs between the paper's table (−1.75) and text (−2.75); the table value is used and flagged.
- BASS-II test records (`data/bass2_instrumented_tests.csv`) come from NASA PSI table PSI-25. The source has no outcome column: `outcome_flag` is a keyword match over the free-text flow log in the table (extinguished, blowoff, no_ignition), and a blank means the log does not say, not that the sample burned out. 104 of 129 tests have no outcome word.
- Units come from the BASS-II report (p. 5): `Air display` is the air-velocity transducer in cm/s, `Fan display` is fan voltage x10, the N2 flow is in cm3/min, and the radiometer is uncalibrated with a gain set per test, so `rad` values cannot be compared across tests. `initial_air_cm_s` is the first air reading in each test (0 to 20 cm/s); the transducer takes about a minute to settle.
- Eleven BASS-II rows are flagged in `data_quality`: five final-O2 readings (0.6 to 40.4%) are not physical and look like values typed into the wrong cell, so no O2 delta is derived from them; two air readings of 49 exceed the duct limit and look like fan values; one shows CO falling during the test; three have date problems (two dated 2018, one whose date and GMT day disagree). Nine BASS manifest rows have date problems too (a year of 2103, an unparseable date, and GMT days that disagree with the date). Dates are flagged, never corrected, since either column could be the wrong one.
- As a check on the raw table, median CO2 produced per O2 consumed is 0.80 (quartiles 0.72 to 0.87, n=65), close to the 0.83 implied by the 6:5 ratio in the BASS-II Summary Report (Fig. 1.3). Claims C-13 to C-18 and C-20 to C-26 cite that report (NASA/TM-20210011385); C-19 cites the raw table.
- CO limits on the Saffire chart (425 ppm 1 h, 100 ppm 24 h) are checked against NASA's SMAC table, JSC 20584 Rev C (2024), claim C-48. The BASS-II report's '55 ppm 1-hour' figure matches the current 7-day limit; C-18 keeps the authors' wording and notes this.
- Saffire-III: sample 1 has a full sensor workbook (record `saffire3_s1`, same script as Saffire-I/II); both burns also have vehicle telemetry (`scripts/ingest_saffire3_telemetry.py`, record `saffire3`: cabin pressure, temperature, smoke detector, 30 s radiometer samples). Saffire's pressure sensor (14.46 psia) and the Cygnus cabin sensors (13.99 psia) disagree; BurnBook shows Saffire's, like the other Saffire flights, and flags the difference. Saffire-III's O2 sensor read 19.8%, low for cabin air.
- The BASS (2012) table, PSI-26, is a manifest only: no gas readings or outcomes.
- SPICE smoke points (`data/spice_smoke_points.csv`) are copied from DeBold 2012, Appendix 5.1 (ethylene, 1.6 mm burner only; the thesis has 112 smoke points across fuels). `data/spice_video_frames.csv` holds BurnBook's own measurements from test-day 045 video (scale 4.93 px/mm from the ruler frames). The frame nearest the 58 cm/s smoke point measures 75.5 mm against 75.35 mm published. Open questions are listed in `video_check.caveats`: a 2 to 3 minute gap between the thesis time and the video clock, and an overlay AIR reading about 20% above the published coflow.
- The overlay AIR value is the raw transducer reading. In SPICE it read 68 to 72 where the published (fan-calibrated) coflow was 58 cm/s, so BASS-II `initial_air_cm_s` may also run high; treat it as approximate. RAD shows 4.10 on many different flames and looks like the display's ceiling.
- Saffire-I (2016) comes from NASA PSI table PSI-98: two burns with burn time only, no gas or heat-release data, so the Saffire chart shows them as "not reported". The table's length (40.6 cm) and width (94 cm) look swapped against the flight report (0.4 m wide, 94 cm long); BurnBook uses 94 cm as the length.
- Saffire-II (`data/saffire2_flammability.csv`, PSI-99) lists microgravity and 1g burn results for nine 29 x 5 cm samples, copied as printed. Thicknesses printed as "037 mm" are read as 0.37 mm; rows 2-6 and 2-9 have blank material cells and are assumed to match the row above (flagged `material_inferred`). O2 is derived from measured CO2 (source note 1).
- Saffire-III (PSI-100) adds two SIBAL burns at 30 cm/s with no O2, burn time or gas data. Its table lists the sample as 94 cm long and 40.6 cm wide, confirming the Saffire-I table has those swapped. SIBAL thickness is printed as 0.37 cm (Saffire-I), 0.37 mm (Saffire-II) and 0.33 cm (Saffire-III); the units disagree and are left as printed.
- The flame images (`web/img`, `data/gallery.csv`) are NASA ISS crew photos (BASS, BASS-II) and ACME camera frames, credited to NASA. Which investigation each shows is inferred from dates: expedition dates against the BASS logs, and ACME file dates against each experiment's operating window in Stocker 2021 (E-FIELD Sept-Nov 2018, BRE Jan-Apr 2019, Flame Design April-July 2019). Captions say "likely". Claims C-33 to C-35 come from the same Stocker paper.
- ACME BRE (PSI-20) and CLD Flame (PSI-21) are test-day summaries: fuel, O2 or fuel-concentration range, and flames lit per day, with no outcomes or pressures. Two BRE oxygen values printed as "3400%" and "2100%" are read as 34 and 21; 26 CLD fuel names were auto-filled by a spreadsheet ("40% CH5", "C2H11" and so on) and are restored to CH4 or C2H4. Every correction is in `data_quality`.
- CFI-G (PSI-159) has one row per test for 179 normal and 154 inverse flames. The oxygen chart and claim C-36 group the normal flames by chamber O2; fuel, dilution, flow and pressure also vary, so it shows a pattern, not a controlled result. Flames stopped by cutting the fuel are plotted as lower bounds. The cool-flame column is blank on most days, so the 7 recorded cool flames (C-37) may undercount.
- The soot score (`scripts/soot_score.py`, `data/soot_scores.csv`) is image processing, not AI: pixels brighter than 20% are flame, yellow/orange/red/white ones count as soot and cyan/blue ones as blue, and the score is soot / (soot + blue) by area. Thresholds were set by eye on overlay images and then fixed for all images. Scores are only comparable within one camera. SPICE video frames are measured but not scored (the overexposed video shows no blue at all, so every frame reads 1.0); one ISS photo is excluded for orange-lit hardware and one ACME frame for being too dim.
- Saffire-I sample 2 sensor data (`scripts/ingest_saffire_sensors.py`, PSI workbook) is reduced to 1 s means plus a summary. Cabin pressure is the sensor mean (14.88 psia); the CO2 rise is the peak of a 10 s running mean at the avionics-bay sensor. Its O2 sensor reads about 22.3% where PSI-98 lists ~21.5%, which is flagged, not corrected. Saffire I-III had no CO sensor.
- FLEX (`scripts/ingest_flex.py`, PSI-69) is read as Windows-1252; its en dashes mean 'not measured' and become blank. Gas fractions are mole fractions. The 'burning rate; mm' column is kept as printed and treated as mm2/s. One pressure of 0 mmHg is withheld and one identifier appears twice; both are flagged.
- CFI (`scripts/ingest_cfi.py`) comes from NASA's CFI data summary spreadsheet (Jan 2021), covering all 227 tests FLEX-1206 to 1431; conditions match PSI-39 for every test both list. Farnesane tests are not analysed in the source. A cool-flame extinction diameter of 0 means the droplet burned out. Test 1268 differs from the final report (0 vs 2.563 mm); gas mixes summing to 0.97, one odd mixture label, two out-of-sequence dates and '12:xx am' times are flagged.
- No record is at lunar or Mars gravity.
- The API uses Starlette rather than FastAPI because FastAPI could not be installed in the build sandbox.
