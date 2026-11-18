from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import audit
from .config import ProjectConfig, find_project_root, list_projects
from .estimate import estimate_data
from .pdf_reports import technical_report
from .project_mgmt import inventory
from .reports import build_data_records, validation_report, write_build_manifest, write_working_registers
from .takeoff import takeoff
from .workbooks import build_workbooks


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        import sys
        argv = sys.argv[1:]
    if argv and argv[0] == "estimate-agent":
        # Agente estimador: lee planos/specs/addenda con la API de Anthropic y produce el paquete de 3 documentos.
        from .estimator_agent.agent import main as agent_main
        return agent_main(argv[1:])
    if argv and argv[0] == "package":
        # Paquete ALKAN de 3 documentos: no depende de un expediente en docs/.
        from .package_build import main as package_main
        return package_main(argv[1:])
    if argv and argv[0] == "reprice":
        # Cambiar precios o proveedores de un estimado (archivo de cambios o listas de precios).
        from .reprice import main as reprice_main
        return reprice_main(argv[1:])
    parser = argparse.ArgumentParser(prog="bidkit")
    parser.add_argument("command", choices=["audit", "takeoff", "estimate", "build", "validate", "list-projects", "inventory", "cost-init", "cost-import", "estimate-ui", "package", "estimate-agent"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--project", help="Nombre del expediente o identificador; obligatorio salvo para listar.")
    parser.add_argument("--workbook", type=Path, help="Cost workbook with estimator edits for cost-import.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    root = (args.root or find_project_root()).resolve()
    if args.command == "estimate-ui":
        from .intelligence_ui import serve
        serve(root, args.port, open_browser=not args.no_browser)
        return 0
    # Adopted dossiers have one authoritative source; old inputs remain historical.
    if args.project:
        from .intelligence import Intelligence
        service = Intelligence(root)
        matches = [p for p in service.list_projects() if args.project in (p["project_id"], p["name"]) and p["integrated"]]
        if len(matches) == 1:
            pid = matches[0]["project_id"]
            row = service.store.load(pid)
            service.check_originals(pid, row["state"])
            result = service.evaluate(row["state"])
            if args.command in ("cost-init", "cost-import"):
                parser.error("Expediente V2: registre cotizaciones en estimate-ui; los inputs anteriores se conservan como históricos.")
            if args.command == "build":
                from .intelligence_reports import export_document
                kinds = ["internal", "supplier"] + (["proposal"] if row["state"].get("current_approval") and not result["release_blockers"] else [])
                result = {"revision": row["revision"], "files": [str(export_document(service, pid, kind)) for kind in kinds]}
            elif args.command == "takeoff": result = {"revision": row["revision"], "records": row["state"]["lines"]}
            elif args.command == "audit": result = {"revision": row["revision"], "documents": len(row["state"]["documents"]), "original_integrity": "PASS"}
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
    try:
        if args.command == "list-projects":
            result = {"projects": list_projects(root)}
        elif args.command == "inventory":
            result = inventory(root)
        else:
            config = ProjectConfig(root, args.project)
            if args.command == "cost-init":
                from .costing import initialize
                from .project_schema import require_valid_analysis
                result = initialize(config, require_valid_analysis(config))
            elif args.command == "cost-import":
                from .cost_workbooks import import_cost_workbook
                from .project_schema import require_valid_analysis
                if not args.workbook:
                    raise ValueError("cost-import requires --workbook")
                result = import_cost_workbook(config, args.workbook, require_valid_analysis(config))
            elif args.command == "audit":
                data = audit(config)
                result = {"documents": len(data["documents"]), "manifest": str(config.audit_dir / "document_inventory.json")}
            elif args.command == "takeoff":
                data = takeoff(config)
                result = {"records": len(data["records"]), "path": str(config.data_dir / "takeoff" / "takeoff.json")}
            elif args.command == "estimate":
                data = estimate_data(config)
                result = {"rows": len(data["rows"]), "path": str(config.data_dir / "estimate" / "estimate_inputs.json")}
            elif args.command == "build":
                estimate_data(config)
                build_data_records(config)
                write_working_registers(config)
                build_workbooks(config)
                technical_report(config)
                if (config.project_dir / "bid_form.json").exists():
                    from .bid_preparation import build_preparation
                    from .project_schema import require_valid_analysis
                    build_preparation(config, require_valid_analysis(config))
                write_build_manifest(config)
                result = validation_report(config)
            else:
                result = validation_report(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("technical_validation") == "FAIL" else 0
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
