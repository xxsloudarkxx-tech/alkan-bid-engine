"""Independent review of a finished package, in a fresh context.

The estimator that produced the numbers is not the one that checks them: a
second conversation receives only the package, the totals, the notes and the
deterministic findings, can re-read the bid documents with read-only tools, and
must return a verdict through ``submit_review``.
"""
from __future__ import annotations

import json

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Final verdict of the independent review. Call exactly once when done.",
    "input_schema": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FIX"],
                    "description": "FIX only when at least one blocker would change the price or the scope carried."},
        "summary": {"type": "string", "description": "Two or three sentences, in Spanish."},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["blocker", "warning", "info"]},
            "where": {"type": "string", "description": "Line id (M012, L003), section or document/page"},
            "issue": {"type": "string"}, "fix": {"type": "string"}},
            "required": ["severity", "where", "issue"]}}},
        "required": ["verdict", "summary", "findings"]},
}
READ_ONLY = ("list_documents", "search_documents", "read_page_text", "lookup_price", "lookup_productivity", "lookup_wage")

SYSTEM = """You are the reviewing estimator at ALKAN Construction Assistant. Another estimator prepared the package \
below for {contractor}. You did not see their work; check it cold, the way a chief estimator signs off a bid:

1. Dates and requirements: is the bid date the LATEST one (addenda extend dates)? Any mandatory pre-bid, bond or \
form that the notes missed? Spot-check with search_documents / read_page_text.
2. Scope: does every scheduled item of the contractor's trade appear in materials? Anything priced that belongs to \
another trade or to an alternate? Do scope, exclusions and materials agree with each other?
3. Quantities: pick the three largest material lines and verify the quantity against its qty_source page.
4. Completeness of each assembly: posts with footings and concrete, rails with fittings and anchors, gates with \
hardware, finish (galvanizing/powder coat) and freight.
5. Prices and labor: units consistent (LF vs EA vs LB), prices in line with lookup_price, hours in line with \
lookup_productivity, the right prevailing-wage trade and county.
6. The deterministic findings listed below: confirm or dismiss each one.

Be specific and brief. A blocker is something that would change the sell price by more than about 2% or would make \
the bid non-responsive; everything else is a warning or info. Do not rewrite the estimate. Finish by calling \
submit_review (findings and summary in Spanish)."""


def _brief(package: dict, totals: dict, notes: list[dict], sanity: list[dict]) -> str:
    keep = {k: package.get(k) for k in ("project", "labor_rates", "materials", "labor", "other", "scope",
                                        "exclusions", "assumptions", "markups", "relationship")}
    return ("PACKAGE\n" + json.dumps(keep, ensure_ascii=False) + "\n\nTOTALS\n" + json.dumps(totals, ensure_ascii=False)
            + "\n\nNOTES RECORDED BY THE ESTIMATOR\n" + json.dumps(notes, ensure_ascii=False)
            + "\n\nDETERMINISTIC FINDINGS\n" + json.dumps(sanity, ensure_ascii=False))


def run_review(client, toolbox, package: dict, totals: dict, notes: list[dict], sanity: list[dict],
               contractor: str, max_turns: int = 14, log=None) -> dict:
    """Returns {verdict, summary, findings}; verdict 'UNAVAILABLE' if the reviewer never answered."""
    tools = [t for t in toolbox.tool_defs() if t["name"] in READ_ONLY] + [REVIEW_TOOL]
    messages = [{"role": "user", "content": _brief(package, totals, notes, sanity)}]
    system = SYSTEM.format(contractor=contractor)
    for turn in range(1, max_turns + 1):
        resp = client.create(system, messages, tools)
        content = resp.get("content", [])
        messages.append({"role": "assistant", "content": content})
        uses = [b for b in content if b.get("type") == "tool_use"]
        if log:
            log({"event": "review", "turn": turn, "tools": [u["name"] for u in uses], "usage": resp.get("usage")})
        if resp.get("stop_reason") == "pause_turn":
            continue
        if not uses:
            messages.append({"role": "user", "content": "Call submit_review now with your verdict."})
            continue
        results = []
        for u in uses:
            if u["name"] == "submit_review":
                r = u.get("input") or {}
                findings = [f for f in r.get("findings", []) if isinstance(f, dict) and f.get("issue")]
                verdict = "FIX" if r.get("verdict") == "FIX" and any(f.get("severity") == "blocker" for f in findings) else "PASS"
                return {"verdict": verdict, "summary": str(r.get("summary", "")), "findings": findings}
            if u["name"] not in READ_ONLY:
                out, err = "Herramienta no disponible en revisión", True
            else:
                out, err = toolbox.call(u["name"], u.get("input") or {})
            results.append({"type": "tool_result", "tool_use_id": u["id"], "content": out, **({"is_error": True} if err else {})})
        messages.append({"role": "user", "content": results})
    return {"verdict": "UNAVAILABLE", "summary": "La revisión independiente no concluyó en el límite de pasos.", "findings": []}
