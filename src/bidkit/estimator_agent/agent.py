"""ALKAN estimator agent — reads a bid set and produces the 3-document package.

Same working method used by hand for WSJ, Meridian, Orangegate and Gonyea
(Nov 2026): inventory → dates & addenda → bid form / alternates → scope search
→ read schedules & specs → view and measure drawings → price (book → web) →
labor by task with prevailing wage → save package → build + QA → report.

Usage:
    bidkit estimate-agent --docs "C:\\...\\Gonyea Playfield.zip" --key GONYEA \
        --profile profiles\\ss_custom_iron_works.json --out ENTREGAS\\GONYEA
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .anthropic_client import AnthropicClient, APIError, equivalent_tokens
from .docindex import DocIndex
from .review import run_review
from .tools import STAGES, ToolBox, web_search_tool

METHOD = """You are the senior estimator of ALKAN Construction Assistant, preparing a bid for {contractor} \
({relationship}) on a Washington State public-works project. Work exactly with the ALKAN method, in this order:

0. GO / NO-GO FIRST (before spending time on takeoff). Read the invitation / advertisement / Division 00 and every
   addendum for conditions to be allowed to bid: MANDATORY pre-bid meeting or site visit (date, and whether it has
   already passed as of today), bid bond / bid security, required registrations or prequalification, required forms
   (subcontractor list, apprenticeship, MWBE), license classes. record_note(kind="requirement") each one with its
   source. {preflight}
1. INVENTORY. list_documents. Identify plans, specs, addenda, bid form, invitation. Note pages without text (scans).
2. DATES. Find bid due date/time, questions and substitution deadlines, then read EVERY addendum looking for date
   extensions ("extended", "revised bid date") — an addendum overrides the specs (Orangegate was extended from
   Nov 4 to Nov 10 by Addendum 3). record_note(kind="date") each one, with the Pacific time and the {tz_label} time
   (Pacific {tz_offset:+d} h). record_note(kind="contact") the owner and prime/GC contacts if present.
   ENGINEER'S ESTIMATE: if the advertisement or bid form states one, record_note(kind="benchmark") with the amount,
   what it covers (whole project or only this trade) and the source. It is a reference, never an anchor: do NOT
   move quantities or prices toward it. Engineer's estimates on marine, diving and specialty work often run
   30-50 % low. If this trade alone takes more than half of a whole-project figure, say so as a risk.
3. BID FORM & ALTERNATES. Read the bid form and the alternates schedule. Price BASE BID only; list every
   alternate in exclusions (offer to price separately if it contains work of this trade).
4. SCOPE. The contractor's trade and limits: {policy}
   Search schedules (material / furnishing / sign / door / finish schedules, keynotes), the spec sections of the
   trade{sections} and the details they reference. Addenda revisions to schedules govern over the original sheets.
   record_note(kind="scope") anything of the trade you decide NOT to carry, and why.
   An addendum may DELETE a spec section or sheet. If the run instructions (the GC or the office) still ask you to
   carry that work, carry it, label the scope item and its assumption "per GC direction" (naming who directed it),
   and record_note(kind="scope") the addendum that deleted it. Never carry deleted work silently.
   If an RFQ splits the material into supplier packages, keep each package as its own material section so it can
   be quoted and issued separately; a separate estimate per package only when the run instructions ask for it.
5. TAKEOFF. view_page and zoom (crop) on plans and details. Count from schedules when given; otherwise measure:
   measure_on_view with the scale bar (ref_p1/ref_p2/ref_feet) or the sheet scale, and cross-check one measured
   length against a written dimension on the same sheet. Every material line needs qty_source (sheet/detail/spec/
   RFQ line). List each assembly down to the last component: posts, rails, fittings, caps, bands, ties, anchors,
   grout, concrete, rock, finish (galvanizing / powder coat / paint), consumables, freight. Add a waste factor
   where stock lengths or rolls apply and say so in the spec column.
6. PRICING. SUPPLIER QUOTES FIRST: if the documents include a supplier quote (Farwest Steel, Pacific Metals,
   Fastenal, a galvanizer...), copy every line exactly as quoted (qty, description, unit price, no rounding) with
   price_basis QUOTE and price_source "<supplier> quote #<number> <date>"; then re-read the quote and check line by
   line that nothing is missing or doubled. Add on top only what the quote does not include (freight if FOB yard,
   cutting, galvanizing, tax) and say so in the spec column. If the quote is issued to another company, record a
   question to re-request it in {contractor}'s name. Then lookup_price (QUOTE > CATALOG > BUDGET). If missing, web_search Puget Sound commercial-grade
   pricing and mark price_basis BUDGET with the source. Never present a budget price as a quote. Pre-engineered or
   owner-selected items without a price: allowance, clearly labeled. Galvanizing ≈ $0.45/lb structural,
   $0.60/lb light members, lot minimum ≈ $375.
7. LABOR. Split shop / field / office by task with hours (lookup_productivity; scale by quantity, do not guess a
   lump). Prevailing-wage trades from lookup_wage for the PROJECT county and the trade doing the work; if a row is
   unverified or missing, web_search L&I and cite county and effective date. Use the profile rate keys
   ({profile_rates}) for shop and office.
8. EQUIPMENT & OTHER. Augers, telehandler, lifts, welder, core drill, mobilization trips, L&I filing fees
   (Intent + Affidavit $40 each), small tools.
8b. SITE CONDITIONS & SPECIAL REQUIREMENTS. Search the specs, general notes and run instructions for conditions
   that cost money, and turn EACH one into a priced line or an explicit exclusion — never leave one silent:
   - access limits (elevator, stair, door or weight limits): size pieces to the limit, add field splices with their
     field bolting/welding hours, extra handling and trips;
   - hot work: permit and fire watch hours for every hour of field welding/cutting;
   - fireproofing (intumescent / spray): allowance from member surface area, and a question asking for the UL
     design and required rating; galvanizing, primer, paint or powder coat as specified;
   - crane / rigging, delegated design (PE-stamped calcs and shop drawings), special inspection, testing;
   - over-water or environmental work (HPA containment, spill kit, debris capture), occupied building, night or
     weekend work, security escort.
   record_note(kind="risk") the ones priced as allowances.
9. SAVE & BUILD. save_package (markups, burden, tax, commission and release are fixed by the profile), then
   build_package. Fix and rebuild until QA = PASS. Read the "sanity" findings returned by build_package: fix the
   real errors and rebuild; keep the ones that are correct and explain them in must_verify. Sanity-check the sell
   price per LF / SF / each against similar past jobs in the price book.
10. FINISH with decision and a short Spanish report: sell price, scope carried, key dates, top risks and the list
   of things a human must verify before sending (assumed counts, scaled quantities, allowances, unverified wages,
   budget prices). An independent reviewer checks the package after you call finish; if it returns blockers, fix
   them, rebuild and call finish again.
   Before finishing, record_note(kind="question") every open question for the GC that must be answered before
   material is released (UL design, field verification, delivery access, by-others interfaces).
   TARGET PRICE: if the run instructions ask for a specific total, do NOT change quantities, prices or hours to
   reach it. Price the job honestly, pass the requested total as finish(target_price=...) and explain in the
   summary what it would take (lower margin, scope cut, alternate supplier). The report computes the gap.

How ALKAN delivers (do not deviate): three documents from ONE computation — 01 Cost Analysis (internal), 02 Material
List & Price List, 03 Estimate/Proposal — with the same sell price in all three; the proposal stays DRAFT until a
person authorizes it; nothing is sent to anyone by you. Scope, exclusions and assumptions are printed in the
client-facing proposal: never mention prior bids, competitors' prices, the engineer's estimate, Alkan's commission
or internal notes there — those go in record_note only.

Rules: never invent a quantity without a source or a stated assumption (record_note kind=assumption); numbers as
strings in save_package; be economical — search text before viewing, zoom on the details you need instead of
viewing many full sheets, and batch independent tool calls in the same turn. Today is {today}.{extra}"""

PREFLIGHT_STOP = ("If a mandatory requirement can no longer be met (for example a mandatory pre-bid meeting that already "
                  "took place, or a bid date already past with no extension), do NOT estimate: record it and call "
                  "finish(decision=\"NO_GO\") explaining exactly what was missed and where it says so.")
PREFLIGHT_CONTINUE = ("If a mandatory requirement can no longer be met, record it as a risk and continue: the estimate "
                      "will be used as a budget reference.")


def _count_images(messages: list) -> int:
    n = 0
    for msg in messages:
        if msg["role"] == "user" and isinstance(msg["content"], list):
            for block in msg["content"]:
                if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                    n += sum(1 for c in block["content"] if c.get("type") == "image")
    return n


def _prune_images(messages: list, keep: int) -> None:
    """Keep only the last `keep` images in the conversation to control context size."""
    seen = 0
    for msg in reversed(messages):
        if msg["role"] != "user" or not isinstance(msg["content"], list):
            continue
        for block in msg["content"]:
            if block.get("type") != "tool_result" or not isinstance(block.get("content"), list):
                continue
            for i, c in enumerate(block["content"]):
                if c.get("type") == "image":
                    seen += 1
                    if seen > keep:
                        block["content"][i] = {"type": "text", "text": "[imagen retirada para ahorrar contexto; vuelva a usar view_page si la necesita]"}


class Cancelled(RuntimeError):
    pass


class EstimatorAgent:
    def __init__(self, client, toolbox: ToolBox, profile: dict, log_path: Path, max_turns: int = 120,
                 keep_images: int = 6, web_search: bool = True, web_uses: int = 15, budget_tokens: int = 6_000_000,
                 *, web_tool_type: str = "", preflight_stop: bool = True, reviewer=None, review_rounds: int = 1,
                 extra_system: str = "", tz_label: str = "Mexico City", tz_offset: int = 2,
                 on_event=None, should_stop=None):
        self.client, self.tb, self.profile = client, toolbox, profile
        self.log_path, self.max_turns, self.keep_images = Path(log_path), max_turns, keep_images
        self.budget_tokens = budget_tokens
        self.reviewer, self.review_rounds = reviewer, review_rounds
        self.on_event, self.should_stop = on_event, should_stop
        self.reviews: list[dict] = []
        self.tools = toolbox.tool_defs() + ([web_search_tool(web_uses, web_tool_type)] if web_search else [])
        sections = profile.get("spec_sections") or []
        self.system = METHOD.format(
            contractor=profile["contractor"]["name"], relationship=profile.get("relationship", "sub_to_gc"),
            policy=" ".join(profile.get("scope_policy", [])) or "(not specified — infer the trade from the run instructions)",
            sections=(" (" + ", ".join(sections) + ")") if sections else "",
            profile_rates=", ".join(profile.get("labor_rates", {})) or "none defined",
            preflight=PREFLIGHT_STOP if preflight_stop else PREFLIGHT_CONTINUE,
            tz_label=tz_label, tz_offset=tz_offset, today=profile["date"],
            extra=("\n\nStanding instructions from the office: " + extra_system.strip()) if extra_system.strip() else "")

    def _log(self, event: dict):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 1), **event}, ensure_ascii=False) + "\n")
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001 - a UI callback must never break a paid run
                pass

    def _used(self) -> int:
        used = equivalent_tokens(self.client.usage)
        if self.reviewer is not None and self.reviewer is not self.client:
            used += equivalent_tokens(self.reviewer.usage)
        return used

    def _review(self) -> dict | None:
        """Independent review of the built package; None when not applicable."""
        if self.reviewer is None or not self.tb.last_build or not self.tb.package_path:
            return None
        self._log({"event": "stage", "stage": "Revisión independiente"})
        package = json.loads(self.tb.package_path.read_text(encoding="utf-8"))
        review = run_review(self.reviewer, self.tb, package, self.tb.last_build["computation"]["totals"], self.tb.notes,
                            self.tb.last_sanity, self.profile["contractor"]["name"], log=self._log)
        self.reviews.append(review)
        self._log({"event": "review_done", "verdict": review["verdict"], "findings": len(review["findings"])})
        return review

    def _try_finish(self, args: dict):
        """(tool_result_text, is_error, accepted).  Guards the end of the run."""
        decision = args.get("decision") or "GO"
        if decision == "NO_GO":
            if not any(n["kind"] == "requirement" for n in self.tb.notes):
                return "Antes de NO_GO registre el requisito incumplido con record_note(kind='requirement') y su fuente.", True, False
            return "FINISHED", False, True
        build = self.tb.last_build
        if not build:
            return "Aún no hay paquete: save_package y build_package antes de finish (o decision NO_GO con su requisito).", True, False
        if build["qa"]["status"] != "PASS":
            return "La verificación cruzada no pasó: corrija, save_package y build_package de nuevo antes de finish.", True, False
        if self.review_rounds > 0:
            review = self._review()
            if review and review["verdict"] == "FIX":
                self.review_rounds -= 1
                blockers = [f for f in review["findings"] if f.get("severity") == "blocker"]
                return ("La revisión independiente encontró bloqueadores. Corríjalos (o explique con evidencia por qué no "
                        "aplican), vuelva a save_package y build_package, y llame finish otra vez:\n"
                        + json.dumps(blockers, ensure_ascii=False)), True, False
        return "FINISHED", False, True

    def run(self, key: str, extra_instructions: str = "") -> dict:
        self.tb.key = key
        messages = [{"role": "user", "content":
                     f"Prepare the estimate package for project key '{key}' with the bid documents provided. {extra_instructions}".strip()}]
        report, warned = None, False
        for turn in range(1, self.max_turns + 1):
            if self.should_stop and self.should_stop():
                self._log({"event": "cancelled", "turn": turn})
                raise Cancelled("Corrida cancelada por el usuario")
            used = self._used()
            if used > self.budget_tokens and not warned:
                warned = True
                self._log({"event": "budget_stop", "tokens": used})
                note = {"type": "text", "text": "Token budget reached: save_package and build_package now with what you have, then finish."}
                last = messages[-1]
                if last["role"] == "user" and isinstance(last["content"], list):
                    last["content"].append(note)
                elif last["role"] == "user":
                    last["content"] = [{"type": "text", "text": last["content"]}, note]
                else:
                    messages.append({"role": "user", "content": [note]})
            # Prune in batches: rewriting old turns on every call would defeat the prompt cache.
            if _count_images(messages) > self.keep_images + max(2, self.keep_images // 2):
                _prune_images(messages, self.keep_images)
            resp = self.client.create(self.system, messages, self.tools)
            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})
            names = [b.get("name") for b in content if b.get("type") in ("tool_use", "server_tool_use")]
            self._log({"event": "assistant", "turn": turn, "stop": resp.get("stop_reason"),
                       "text": " ".join(b.get("text", "") for b in content if b.get("type") == "text")[:2000],
                       "tools": names, "stage": next((STAGES[n] for n in reversed(names) if n in STAGES), None),
                       "usage": resp.get("usage"), "tokens": self._used()})
            if resp.get("stop_reason") == "pause_turn":
                continue                                    # server tool (web search) still working
            uses = [b for b in content if b.get("type") == "tool_use"]
            if not uses:
                if resp.get("stop_reason") == "max_tokens":
                    messages.append({"role": "user", "content": "Your last message was cut off. Continue, splitting large tool inputs if needed."})
                else:
                    messages.append({"role": "user", "content": "Continue with the method until build_package passes QA, then call finish."})
                continue
            results = []
            for u in uses:
                args = u.get("input") or {}
                if u["name"] == "finish":
                    out, err, accepted = self._try_finish(args)
                    if accepted:
                        report = {"decision": "GO", **args}
                else:
                    out, err = self.tb.call(u["name"], args)
                self._log({"event": "tool", "name": u["name"], "input": {k: v for k, v in args.items()
                                                                        if k not in ("materials", "labor", "other", "scope")},
                           "error": err, "result": out[:1500] if isinstance(out, str) else "[image]"})
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": out, **({"is_error": True} if err else {})})
            messages.append({"role": "user", "content": results})
            if report:
                break
        usage = dict(self.client.usage)
        if self.reviewer is not None and self.reviewer is not self.client:
            for k, v in self.reviewer.usage.items():
                usage[k] = usage.get(k, 0) + v
        return {"report": report, "notes": self.tb.notes, "build": self.tb.last_build,
                "package": str(self.tb.package_path) if self.tb.package_path else None,
                "usage": usage, "images": self.tb.images, "reviews": self.reviews, "sanity": self.tb.last_sanity,
                "warnings": list(getattr(self.client, "warnings", [])), "model": getattr(self.client, "model", ""),
                "completed": bool(report)}


DECISIONS = {"GO": "GO — paquete listo para revisión humana", "GO_WITH_CONDITIONS": "GO CON CONDICIONES — lea las condiciones antes de enviar",
             "NO_GO": "NO-GO — no se estimó: hay un requisito que ya no se puede cumplir"}


def target_price_lines(totals: dict, target) -> list[str]:
    """Gap between the honest price and a requested total, and the margin that total leaves over direct cost."""
    try:
        price = Decimal(str(totals["price"]).replace(",", ""))
        direct = Decimal(str(totals["direct"]).replace(",", ""))
        goal = Decimal(str(target).replace(",", "").replace("$", "").strip())
    except (KeyError, InvalidOperation):
        return ["## Precio objetivo", f"- Pedido: {target} (no se pudo comparar con los totales)", ""]
    gap = goal - price
    out = ["## Precio objetivo", f"- Pedido: ${goal:,.2f} · calculado: ${price:,.2f} · diferencia: ${gap:+,.2f}"]
    if direct > 0:
        margin = (goal - direct) / goal * 100 if goal > 0 else Decimal(0)
        out.append(f"- Con el precio pedido, lo que queda sobre el costo directo (${direct:,.2f}) es {margin:.1f}% del precio.")
        if goal < direct:
            out.append("- **ALERTA: el precio pedido está por debajo del costo directo; se perdería dinero.**")
        elif margin < 8:
            out.append("- **Ojo: margen menor a 8%; no alcanza para imprevistos ni overhead real.**")
    out.append("- Los números del paquete NO se ajustaron al precio pedido; decidirlo es del contratista.")
    return out + [""]


def write_report(out_dir: Path, key: str, result: dict) -> Path:
    b = result.get("build") or {}
    t = (b.get("computation") or {}).get("totals", {})
    rep = result.get("report")
    lines = [f"# Reporte del agente — {key}", ""]
    if rep:
        lines += [f"**Decisión: {DECISIONS.get(rep.get('decision', 'GO'), rep.get('decision'))}**", "",
                  "## Resumen", rep["summary"], "", "## Verificar antes de enviar"]
        lines += [f"- {x}" for x in rep["must_verify"]] + [""]
    else:
        lines += ["**La corrida terminó sin reporte final** (límite de pasos o de tokens). Revise la bitácora antes de usar los números.", ""]
    if t:
        lines += ["## Totales", f"- Precio de venta: ${t['price']}", f"- Costo directo: ${t['direct']}",
                  f"- QA: {b['qa']['status']}", f"- Propuesta: {b['proposal_release']['label']}", ""]
    if t and rep and rep.get("target_price"):
        lines += target_price_lines(t, rep["target_price"])
    for kind, title in (("requirement", "Requisitos para poder ofertar"), ("date", "Fechas clave"), ("contact", "Contactos"),
                        ("benchmark", "Referencias de precio (no se usaron para fijar el precio)"),
                        ("risk", "Riesgos"), ("assumption", "Supuestos"), ("question", "Preguntas abiertas"), ("scope", "Notas de alcance")):
        rows = [n for n in result["notes"] if n["kind"] == kind]
        if rows:
            lines += [f"## {title}"] + [f"- {n['text']} _(fuente: {n['source']})_" for n in rows] + [""]
    for i, rv in enumerate(result.get("reviews") or [], 1):
        lines += [f"## Revisión independiente {i}: {rv['verdict']}", rv.get("summary", ""), ""]
        lines += [f"- **{f.get('severity', 'info')}** · {f.get('where', '')}: {f.get('issue', '')}"
                  + (f" → {f['fix']}" if f.get("fix") else "") for f in rv.get("findings", [])] + [""]
    if result.get("sanity"):
        lines += ["## Controles automáticos del paquete final"] + [f"- {s['text']}" for s in result["sanity"]] + [""]
    if result.get("warnings"):
        lines += ["## Avisos técnicos"] + [f"- {w}" for w in result["warnings"]] + [""]
    u = result["usage"]
    lines += ["## Consumo de API", f"- Modelo: {result.get('model') or 'n/d'}",
              f"- Llamadas: {u['calls']} · tokens entrada: {u['input_tokens']:,} · salida: {u['output_tokens']:,} · "
              f"leídos de caché: {u.get('cache_read_input_tokens', 0):,} · imágenes: {result['images']}"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{key}_REPORTE_AGENTE.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bidkit estimate-agent", description="Agente estimador ALKAN (API de Anthropic)")
    ap.add_argument("--docs", required=True, help="Carpeta o ZIP con planos, specs y addenda")
    ap.add_argument("--key", required=True, help="Clave corta del proyecto, p.ej. GONYEA")
    ap.add_argument("--profile", required=True, help="Perfil del contratista (profiles/*.json)")
    ap.add_argument("--out", required=True, help="Carpeta de salida")
    ap.add_argument("--model", default=None, help="Modelo (default claude-fable-5-2 o BIDKIT_CLAUDE_MODEL)")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"], help="Profundidad de razonamiento")
    ap.add_argument("--no-review", action="store_true", help="Sin revisión independiente")
    ap.add_argument("--max-turns", type=int, default=120)
    ap.add_argument("--keep-images", type=int, default=6)
    ap.add_argument("--budget-tokens", type=int, default=6_000_000)
    ap.add_argument("--thinking", type=int, default=0, help="Presupuesto de razonamiento extendido (tokens), 0 = apagado")
    ap.add_argument("--no-web", action="store_true", help="Desactiva web_search")
    ap.add_argument("--notes", default="", help="Instrucciones extra (p.ej. 'incluir bancas y mesas')")
    args = ap.parse_args(argv)
    out = Path(args.out)
    prof_path = Path(args.profile).resolve()
    profile = json.loads(prof_path.read_text(encoding="utf-8"))
    if profile.get("date") in (None, "", "AUTO"):
        profile["date"] = date.today().isoformat()
    index = DocIndex.build(args.docs, out / "_index")
    try:
        client = AnthropicClient(model=args.model, thinking_budget=args.thinking, effort=args.effort,
                                 max_tokens=max(32000, args.thinking + 8000))
    except APIError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 1
    tb = ToolBox(index, profile, out, base_dir=prof_path.parent)
    agent = EstimatorAgent(client, tb, profile, out / f"{args.key}_agent_log.jsonl", args.max_turns,
                           args.keep_images, not args.no_web, budget_tokens=args.budget_tokens,
                           reviewer=None if args.no_review else client)
    try:
        result = agent.run(args.key, args.notes)
    except APIError as exc:
        print(json.dumps({"status": "API_ERROR", "error": str(exc), "partial_package": str(tb.package_path)}, ensure_ascii=False))
        return 1
    rep = write_report(out, args.key, result)
    b = result.get("build") or {}
    print(json.dumps({"status": "DONE" if b else "NO_PACKAGE", "report": str(rep),
                      "sell_price": ((b.get("computation") or {}).get("totals") or {}).get("price"),
                      "qa": (b.get("qa") or {}).get("status"), "usage": result["usage"]}, ensure_ascii=False, indent=2))
    if (result.get("report") or {}).get("decision") == "NO_GO":
        return 0
    return 0 if b and b["qa"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
