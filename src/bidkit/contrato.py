"""Contrato con alcance por cliente: la preconfiguración de cada contratista.

Uno nada más dice el cliente y el motor hace el paquete con su marca:

    python -m bidkit.contrato hacer --cliente diaz --paquete takeoff.json --out ENTREGAS/X
    python -m bidkit.contrato listar
    python -m bidkit.contrato logos --origen logos_contractors.zip

El perfil (``profiles/<id>.json``) pone todo lo comercial: nombre, licencia, logo,
tarifas de taller/oficina, burden, markups, comisión, exclusiones y supuestos de base.
El paquete (el takeoff) pone cantidades, horas, el salario prevailing del condado de
la obra y el alcance.  Antes de construir se revisa que el alcance no traiga partidas
que ese cliente no hace (``scope_excluir`` del perfil).
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import unicodedata
import zipfile
from datetime import date
from pathlib import Path

from .estimator_agent.tools import merge_profile

ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "profiles"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
LOGO_MAX_PX = 900


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def list_profiles(profiles_dir: Path = PROFILES_DIR) -> dict[str, dict]:
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(Path(profiles_dir).glob("*.json"))}


def _names(pid: str, prof: dict) -> list[str]:
    names = [pid, prof.get("profile", ""), prof.get("contractor", {}).get("name", "")] + list(prof.get("aliases", []))
    return [n for n in (_norm(x) for x in names) if n]


def resolve(cliente: str, profiles_dir: Path = PROFILES_DIR) -> tuple[str, dict]:
    """Perfil por id, alias o nombre (sin acentos ni mayúsculas); error claro si es ambiguo."""
    profiles = list_profiles(profiles_dir)
    key = _norm(cliente)
    if not key:
        raise ValueError("Falta el nombre del cliente")
    exact = [pid for pid, p in profiles.items() if key in _names(pid, p)]
    if len(exact) == 1:
        return exact[0], profiles[exact[0]]
    partial = exact or [pid for pid, p in profiles.items() if len(key) >= 3 and any(key in n for n in _names(pid, p))]
    if len(partial) == 1:
        return partial[0], profiles[partial[0]]
    options = ", ".join(f"{pid} ({profiles[pid].get('profile', '')})" for pid in (partial or profiles))
    raise ValueError(f"Cliente «{cliente}» {'ambiguo' if partial else 'no encontrado'}. Opciones: {options}")


def find_logo(pid: str, prof: dict, profiles_dir: Path = PROFILES_DIR) -> Path | None:
    """Logo del perfil; si no lo declara, busca en profiles/assets un archivo con su id o alias."""
    declared = prof.get("contractor", {}).get("logo")
    if declared:
        lp = Path(declared)
        lp = lp if lp.is_absolute() else Path(profiles_dir) / lp
        if lp.exists():
            return lp
    assets = Path(profiles_dir) / "assets"
    if not assets.is_dir():
        return None
    names = set(_names(pid, prof))
    for f in sorted(assets.iterdir()):
        if f.suffix.lower() in IMAGE_EXT and _norm(f.stem) in names:
            return f
    return None


def missing_data(prof: dict) -> list[str]:
    """Campos del contratista que siguen como marcador ([...] / Pending)."""
    if prof.get("generic"):
        return []
    c = prof.get("contractor", {})
    return [k for k in ("name", "address", "license", "phone", "contact")
            if not str(c.get(k, "")).strip() or "[" in str(c.get(k, "")) or "pending" in str(c.get(k, "")).lower()]


def scope_conflicts(draft: dict, prof: dict) -> list[dict]:
    """Renglones del paquete que el perfil dice que ese cliente no hace."""
    out = []
    for rule in prof.get("scope_excluir", []):
        rx = re.compile(rule["patron"])
        for m in draft.get("materials", []):
            if rx.search(f"{m.get('item', '')} {m.get('section', '')}"):
                out.append({"id": m.get("id", ""), "item": m.get("item", ""), "motivo": rule.get("motivo", "")})
    return out


def _merge_list(base: list[str], extra: list[str]) -> list[str]:
    seen = {_norm(x) for x in base}
    return list(base) + [x for x in extra if _norm(x) not in seen]


def preparar(draft: dict, cliente: str, profiles_dir: Path = PROFILES_DIR, today: date | None = None) -> tuple[dict, dict]:
    """Paquete alkan-package/1 para ese cliente + reporte de la preconfiguración."""
    pid, prof = resolve(cliente, profiles_dir)
    prof = json.loads(json.dumps(prof))
    if prof.get("date") in (None, "", "AUTO"):
        prof["date"] = (today or date.today()).isoformat()
    logo = find_logo(pid, prof, profiles_dir)
    if logo:
        prof["contractor"]["logo"] = str(logo.resolve())
    else:
        prof["contractor"].pop("logo", None)
    pkg = merge_profile(draft, prof, profiles_dir)
    used = {l["rate"] for l in pkg["labor"]}
    pkg["labor_rates"] = {k: r for k, r in pkg["labor_rates"].items() if k in used}
    rev = int(draft.get("revision", 1) or 1)
    pkg["estimate_id"] = f"{prof['estimate_prefix']}-{draft['project']['key']}-{rev:02d}"
    pkg["date"] = draft.get("date") or prof["date"]
    for k in ("release", "revision_log", "distance_miles", "subcontract_package"):
        if k in draft:
            pkg[k] = draft[k]
    pkg["exclusions"] = _merge_list(draft.get("exclusions", []), prof.get("exclusiones_base", []))
    pkg["assumptions"] = _merge_list(draft.get("assumptions", []), prof.get("supuestos_base", []))
    report = {"cliente": pid, "perfil": prof.get("profile", pid), "contratista": prof["contractor"]["name"],
              "logo": str(logo) if logo else None, "estimate_id": pkg["estimate_id"],
              "faltan_datos": missing_data(prof), "fuera_de_alcance": scope_conflicts(draft, prof),
              "incompleto": bool(prof.get("incompleto"))}
    return pkg, report


def hacer(paquete: Path, cliente: str, out_dir: Path, profiles_dir: Path = PROFILES_DIR, estricto: bool = False) -> dict:
    from .package_build import build
    draft = json.loads(Path(paquete).read_text(encoding="utf-8"))
    pkg, report = preparar(draft, cliente, profiles_dir)
    if report["fuera_de_alcance"] and estricto:
        raise ValueError("El paquete trae partidas que este cliente no hace: "
                         + "; ".join(f"{c['id']} {c['item']}" for c in report["fuera_de_alcance"]))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{Path(paquete).stem}__{report['cliente']}.json"
    target.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = build(target, out_dir)
    t = manifest["computation"]["totals"]
    report.update({"paquete": str(target), "precio": t["price"], "costo_directo": t["direct"],
                   "qa": manifest["qa"]["status"], "propuesta": manifest["proposal_release"]["label"],
                   "archivos": [f["path"] for f in manifest["files"].values()]})
    return report


# ─────────────────────────────────────────────────────────────── logos
def _iter_images(origen: Path):
    origen = Path(origen)
    if origen.is_file() and origen.suffix.lower() == ".zip":
        with zipfile.ZipFile(origen) as zf:   # se lee en memoria: nada del zip se extrae al disco
            for info in zf.infolist():
                name = Path(info.filename).name
                if not info.is_dir() and Path(name).suffix.lower() in IMAGE_EXT and not name.startswith("."):
                    yield name, zf.read(info)
    elif origen.is_dir():
        for f in sorted(origen.rglob("*")):
            if f.is_file() and f.suffix.lower() in IMAGE_EXT:
                yield f.name, f.read_bytes()
    else:
        raise ValueError(f"No es un .zip ni una carpeta: {origen}")


def _match(stem: str, profiles: dict[str, dict]) -> str | None:
    key = _norm(stem)
    hits = [pid for pid, p in profiles.items()
            if not p.get("generic") and any(n == key or (len(n) >= 3 and n in key) for n in _names(pid, p))]
    if len(hits) > 1:   # el nombre más largo que coincide gana (p.ej. «jc granite logo» vs «granite»)
        best = max(hits, key=lambda pid: max(len(n) for n in _names(pid, profiles[pid]) if n == key or n in key))
        return best
    return hits[0] if hits else None


def importar_logos(origen: Path, profiles_dir: Path = PROFILES_DIR) -> dict:
    """Copia cada imagen al perfil que le corresponde por nombre de archivo (PNG recortado)."""
    from PIL import Image, ImageChops
    profiles = list_profiles(profiles_dir)
    assets = Path(profiles_dir) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    done, skipped = [], []
    for name, data in _iter_images(origen):
        pid = _match(Path(name).stem, profiles)
        if not pid:
            skipped.append(name)
            continue
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
        flat = Image.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img).convert("RGB")
        box = ImageChops.difference(flat, Image.new("RGB", img.size, (255, 255, 255))).getbbox()
        alpha_box = img.getchannel("A").getbbox()
        box = box if box else alpha_box
        if box:
            img = img.crop(box)
        img.thumbnail((LOGO_MAX_PX, LOGO_MAX_PX))
        target = assets / f"{pid}.png"
        img.save(target, "PNG")
        prof_file = Path(profiles_dir) / f"{pid}.json"
        prof = json.loads(prof_file.read_text(encoding="utf-8"))
        prof.setdefault("contractor", {})["logo"] = f"assets/{pid}.png"
        prof_file.write_text(json.dumps(prof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        done.append({"archivo": name, "cliente": pid, "logo": str(target)})
    return {"importados": done, "sin_cliente": skipped}


# ─────────────────────────────────────────────────────────────── CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bidkit-contrato", description="Contrato con alcance preconfigurado por cliente")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("listar", help="Clientes preconfigurados, logo y datos faltantes")
    h = sub.add_parser("hacer", help="Paquete de 3 documentos con la marca del cliente")
    h.add_argument("--cliente", required=True)
    h.add_argument("--paquete", required=True, nargs="+", help="Takeoff(s) JSON alkan-package/1")
    h.add_argument("--out", required=True)
    h.add_argument("--estricto", action="store_true", help="Bloquear si el alcance trae partidas que el cliente no hace")
    lg = sub.add_parser("logos", help="Importar un pack de logos (.zip o carpeta)")
    lg.add_argument("--origen", required=True)
    ap.add_argument("--profiles", default=str(PROFILES_DIR))
    args = ap.parse_args(argv)
    pdir = Path(args.profiles)
    if args.cmd == "listar":
        rows = []
        for pid, p in list_profiles(pdir).items():
            logo = find_logo(pid, p, pdir)
            rows.append({"cliente": pid, "nombre": p.get("contractor", {}).get("name", ""), "oficio": p.get("oficio", ""),
                         "alias": p.get("aliases", []), "logo": logo.name if logo else "FALTA",
                         "faltan_datos": missing_data(p)})
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "logos":
        print(json.dumps(importar_logos(Path(args.origen), pdir), indent=2, ensure_ascii=False))
        return 0
    rc = 0
    for paquete in args.paquete:
        out = Path(args.out) / Path(paquete).stem if len(args.paquete) > 1 else Path(args.out)
        try:
            rep = hacer(Path(paquete), args.cliente, out, pdir, args.estricto)
        except ValueError as exc:
            print(json.dumps({"paquete": paquete, "status": "BLOQUEADO", "error": str(exc)}, indent=2, ensure_ascii=False))
            rc = 1
            continue
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        if rep["qa"] != "PASS":
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
