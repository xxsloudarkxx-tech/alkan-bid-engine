"""
ALKAN Bid Engine - Phase A Verification Script

Quick verification of audit findings.
Run this to confirm the audit results before proceeding to Phase B.
"""

from pathlib import Path
import json

def verify_phase_a():
    print("=" * 80)
    print("ALKAN BID ENGINE — PHASE A VERIFICATION")
    print("=" * 80)
    print()

    workspace = Path.cwd()
    errors = []
    warnings = []

    # 1. Verify workspace structure
    print("1. Verificando estructura del workspace...")
    required_dirs = ["docs", "src/bidkit", "data", "output"]
    for dir_name in required_dirs:
        dir_path = workspace / dir_name
        if dir_path.exists():
            print(f"   ✓ {dir_name}")
        else:
            print(f"   ✗ {dir_name} NO ENCONTRADO")
            errors.append(f"Directory missing: {dir_name}")

    # 2. Verify docs/ projects
    print("\n2. Verificando proyectos en docs/...")
    docs_dir = workspace / "docs"
    expected_projects = [
        "Gonyea Playfield",
        "Orangegate Park Phase 1",
        "REBID - Meridian",
        "W Seattle Junction Landbank Park"
    ]

    found_projects = []
    if docs_dir.exists():
        for project in expected_projects:
            project_dir = docs_dir / project
            if project_dir.exists() and project_dir.is_dir():
                file_count = len(list(project_dir.glob("*.*")))
                print(f"   ✓ {project} ({file_count} archivos)")
                found_projects.append(project)
            else:
                print(f"   ✗ {project} NO ENCONTRADO")
                warnings.append(f"Project folder missing: {project}")
    else:
        errors.append("docs/ directory not found")

    # 3. Verify new modules created
    print("\n3. Verificando módulos nuevos creados...")
    new_modules = [
        "src/bidkit/project_schema.py",
        "src/bidkit/data_store.py",
        "src/bidkit/project_mgmt.py"
    ]
    for module in new_modules:
        module_path = workspace / module
        if module_path.exists():
            lines = len(module_path.read_text(encoding="utf-8").splitlines())
            print(f"   ✓ {module} ({lines} líneas)")
        else:
            print(f"   ✗ {module} NO ENCONTRADO")
            errors.append(f"Module missing: {module}")

    # 4. Verify audit reports
    print("\n4. Verificando reportes de auditoría...")
    reports = [
        "data/PHASE_A_AUDIT_REPORT.md",
        "data/PHASE_A_FINAL_REPORT.md",
        "data/PHASE_A_EXECUTIVE_SUMMARY.md",
        "data/projects_inventory.json"
    ]
    for report in reports:
        report_path = workspace / report
        if report_path.exists():
            size_kb = report_path.stat().st_size / 1024
            print(f"   ✓ {report} ({size_kb:.1f} KB)")
        else:
            print(f"   ✗ {report} NO ENCONTRADO")
            warnings.append(f"Report missing: {report}")

    # 5. Check for hardcoded references (sample)
    print("\n5. Verificando referencias hardcoded (muestra)...")
    files_to_check = [
        "src/bidkit/contractor.py",
        "src/bidkit/records.py",
        "src/bidkit/estimate.py"
    ]

    hardcoded_found = []
    for file in files_to_check:
        file_path = workspace / file
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            if "PJ_ROOFING" in content or "PJ ROOFING" in content:
                hardcoded_found.append(f"{file}: PJ_ROOFING")
            if "PORT_TACOMA" in content or "Port of Tacoma" in content:
                hardcoded_found.append(f"{file}: PORT_TACOMA")
            if "072026-1044" in content:
                hardcoded_found.append(f"{file}: 072026-1044")

    if hardcoded_found:
        print(f"   ⚠ Referencias hardcoded encontradas (esperado en Phase A):")
        for ref in hardcoded_found[:5]:  # Show first 5
            print(f"      - {ref}")
        print(f"   Total: {len(hardcoded_found)} referencias")
        print(f"   ✓ Estas deben eliminarse en Phase B")
    else:
        print("   ✓ No se encontraron referencias hardcoded (ya refactorizado)")

    # 6. Load and display inventory
    print("\n6. Cargando inventario de proyectos...")
    inventory_path = workspace / "data/projects_inventory.json"
    if inventory_path.exists():
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            print(f"   ✓ Inventario cargado")
            print(f"      Total proyectos: {inventory.get('total_projects_discovered', 0)}")
            print(f"      Total documentos: {inventory.get('total_documents', 0)}")
            print(f"      Tamaño total: {inventory.get('total_size_mb', 0)} MB")
        except Exception as e:
            errors.append(f"Failed to parse inventory: {e}")
    else:
        warnings.append("Inventory JSON not found")

    # Summary
    print("\n" + "=" * 80)
    print("RESUMEN DE VERIFICACIÓN")
    print("=" * 80)
    print(f"Proyectos detectados: {len(found_projects)}/4")
    print(f"Módulos nuevos creados: {sum(1 for m in new_modules if (workspace / m).exists())}/3")
    print(f"Reportes generados: {sum(1 for r in reports if (workspace / r).exists())}/4")
    print(f"Referencias hardcoded detectadas: {len(hardcoded_found)} (deben eliminarse en Phase B)")
    print()

    if errors:
        print("❌ ERRORES CRÍTICOS:")
        for error in errors:
            print(f"   - {error}")
        print()

    if warnings:
        print("⚠️  ADVERTENCIAS:")
        for warning in warnings:
            print(f"   - {warning}")
        print()

    if not errors and not warnings:
        print("✅ PHASE A: COMPLETADA SIN ERRORES")
        print()
        print("Próximo paso:")
        print("  1. Revisar data/PHASE_A_EXECUTIVE_SUMMARY.md")
        print("  2. Confirmar status de West Seattle Junction (PW2019-094)")
        print("  3. Ejecutar: python -m bidkit migrate-legacy")
    elif not errors:
        print("✅ PHASE A: COMPLETADA CON ADVERTENCIAS MENORES")
        print("   Revisar advertencias antes de continuar.")
    else:
        print("❌ PHASE A: INCOMPLETA")
        print("   Resolver errores críticos antes de continuar.")

    print("=" * 80)

if __name__ == "__main__":
    verify_phase_a()
