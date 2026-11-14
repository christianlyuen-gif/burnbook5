"""Evidence retrieval and (optional) cited answers.

Retrieval is plain keyword scoring so it runs anywhere. If a language model is configured (see api/llm.py),
`ask()` also asks it to write a short answer that may only use the retrieved claims.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import llm

STOP = set(
    "a an and are as at be but by can do does for from has have how i in into is it its of on or "
    "so than that the their there these this to was were what when where which who why will with would you your".split()
)


def tokens(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if t in STOP or len(t) < 2:
            continue
        # light stemming so 'burns'/'burning' and 'limits'/'limit' meet
        for suf in ("ing", "ed", "es", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


def _doc_text(c: dict) -> str:
    return " ".join([c["topic"], c["claim"], c["conditions"], c["source"], c["caveat"]])


class Index:
    def __init__(self, claims: list[dict]):
        self.claims = claims
        self.docs = [Counter(tokens(_doc_text(c))) for c in claims]
        n = len(self.docs)
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.avg = sum(sum(d.values()) for d in self.docs) / max(1, n)

    def search(self, query: str, k: int = 5, topic: str | None = None) -> list[dict]:
        q = tokens(query)
        results = []
        for c, d in zip(self.claims, self.docs):
            if topic and c["topic"] != topic:
                continue
            if not q:
                score = 0.0
            else:
                dl = sum(d.values())
                score = 0.0
                for t in q:
                    f = d.get(t, 0)
                    if f:
                        score += self.idf.get(t, 0) * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * dl / self.avg))
            results.append((score, c))
        results.sort(key=lambda x: -x[0])
        if q:
            results = [r for r in results if r[0] > 0]
        return [{**c, "score": round(s, 3)} for s, c in results[:k]]


SYSTEM = (
    "You answer questions about fire behavior in microgravity for spacecraft planners. "
    "Use ONLY the numbered evidence claims provided. Cite claim IDs in square brackets like [C-05]. "
    "State the conditions each claim applies to (material, atmosphere, platform) and do not generalize beyond them. "
    "If the evidence does not answer the question, say so plainly. Keep the answer under 140 words."
)


def build_prompt(question: str, claims: list[dict]) -> str:
    lines = []
    for c in claims:
        lines.append(f"[{c['id']}] {c['claim']} (conditions: {c['conditions']}; source: {c['source']}; caveat: {c['caveat']})")
    return "Evidence:\n" + "\n".join(lines) + f"\n\nQuestion: {question}"


def _llm_answer(question: str, claims: list[dict]):
    """Default answerer: whichever provider api.llm is configured to use (see api/llm.py)."""
    return llm.generate(SYSTEM, build_prompt(question, claims), max_tokens=400)


def ask(index: Index, question: str, k: int = 4, llm_fn=None) -> dict:
    """llm_fn(question, claims) may return a string or an llm.LLMResult; default is the configured provider chain."""
    hits = index.search(question, k=k)
    if not hits:
        return {"mode": "no_match", "answer": "No claim in the evidence base matches this question.", "citations": []}
    cites = [h["id"] for h in hits]
    if llm_fn is None and not llm.available():
        return {"mode": "retrieval_only", "answer": None, "citations": cites,
                "note": "No language model is configured on the server (see BURNBOOK_LLM in api/llm.py); showing the best-matching evidence."}
    try:
        out = (llm_fn or _llm_answer)(question, hits)
    except Exception as exc:  # every provider failed: fall back to retrieval-only
        return {"mode": "retrieval_only", "answer": None, "citations": cites,
                "note": f"Language model unavailable ({llm.describe_error(exc)}); showing matching evidence instead."}
    if isinstance(out, llm.LLMResult):
        return {"mode": "llm", "answer": out.text, "citations": cites, "provider": out.label}
    return {"mode": "llm", "answer": str(out), "citations": cites, "provider": "custom"}
