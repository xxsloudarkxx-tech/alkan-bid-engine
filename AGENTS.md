# AGENTS.md — Reglas para agentes en ALKAN Bid Engine

Guía corta para cualquier agente de IA (Antigravity, Claude, etc.) que trabaje en este repo. Si solo lees una cosa, lee la **Regla de oro**.

## Regla de oro: nunca pasar por encima del motor

El cálculo de precios, costos, horas, markups, criterio y los 3 documentos solo sale del motor en `src/bidkit/` (`package_build.build` → `package_method.compute` y `criterio.review`).

- La capa móvil (`src/bidkit/mobile_api.py`) y la app Flutter (`mobile_app/`) **no calculan números**: arman el paquete, llaman al motor y muestran lo que el motor devuelve (`manifest["computation"]["totals"]`).
- Prohibido recalcular totales, re-derivar markups o "redondear" fuera del motor.
- Si necesitas un número nuevo, agrégalo en el motor, no en la API ni en el cliente.

**Candado automático:** `tests/test_mobile_engine_parity.py` verifica que `financials.sell_price` de la API == `compute()` del motor. Si esta prueba falla, rompiste la regla de oro. No la borres ni la "ajustes" para que pase: arregla el código.

## Antes de dar por terminado un cambio

- Ejecutar pruebas con `PYTHONPATH=src` (p. ej. `python -m unittest tests/test_mobile_engine_parity.py tests/test_mobile_api.py -v` o `pytest -q`). Deben pasar todas (incluido el candado de paridad).
- No cambiar `profiles/*.json` (datos reales de contratistas) salvo que la tarea lo pida.
- No tocar la lógica de cálculo para "simplificar" la app. La app se adapta al motor, no al revés.

## Qué sí puede cambiar libremente

- UI/UX de la app Flutter (`mobile_app/`), tema, flujo, textos, widgets.
- La capa de ensamblado del draft en `mobile_api.py` (plantillas de especialidad, notas de voz), siempre dejando que el motor haga el cálculo final.

## Especialidades

- **6 activas:** `metal`, `techado`, `tablaroca`, `pintura`, `molduras`, `cubiertas`. Viven en `src/bidkit/estimator_agent/knowledge/` (productividad, precios, proveedores) y en `criterio.json` (familias, `proveedores_base`). Agregar una especialidad = extender esos datos, no tocar la lógica.

## Deuda de seguridad (antes de repartir a contratistas, NO en pruebas)

- Quitar credenciales embebidas; alta real de usuarios + cambio de contraseña.
- `ALKAN_ALLOW_BOOTSTRAP=false` y `ALKAN_CORS_ORIGINS` restringido (no `*`) en Railway.

## Documentos

Siempre son 3: `01 Cost Analysis` (interno), `02 Material List`, `03 Client Proposal` (al GC). El Cost Analysis es paquete de subcontrato budgetary: precios `BUDGET` hasta cotizar.
