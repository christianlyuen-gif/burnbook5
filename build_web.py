"""Embed the API bundle in web/template.html and write web/index.html (served by the API)
and web/artifact.html (fragment without doctype/html/head/body, for publishing as a hosted page).

Run from burnbook/:  python build_web.py
"""
import json
import re
from pathlib import Path

from starlette.testclient import TestClient

from api.main import app

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def main():
    bundle = TestClient(app).get("/api/bundle").json()
    payload = json.dumps(bundle, separators=(",", ":")).replace("</", "<\\/")
    tpl = (WEB / "template.html").read_text(encoding="utf-8")
    fragment = tpl.replace("/*__BUNDLE__*/null", payload)
    (WEB / "artifact.html").write_text(fragment, encoding="utf-8")

    head_bits = re.findall(r"<title>.*?</title>|<link [^>]*>|<style>.*?</style>", fragment, flags=re.S)
    body = fragment
    for b in head_bits:
        body = body.replace(b, "", 1)
    full = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + "\n".join(head_bits) + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n"
    )
    (WEB / "index.html").write_text(full, encoding="utf-8")
    print(f"wrote web/index.html ({len(full)//1024} KB) and web/artifact.html ({len(fragment)//1024} KB)")


if __name__ == "__main__":
    main()
