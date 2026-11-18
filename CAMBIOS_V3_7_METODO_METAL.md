# BidEngine v3.7 — Método de metal integrado al agente estimador (2026-11-14)

Lo que funcionó a mano en los estimados de metal (SEA10/Westin, Green Lantern Dock, West Seattle Junction,
Steilacoom, HC3) ahora vive en el agente (`src/bidkit/estimator_agent/`).

## Instrucciones nuevas del agente (agent.py → METHOD)
- **Cotizaciones de proveedor primero** (Farwest, etc.): copiar renglón por renglón como QUOTE con número y fecha,
  revisar que no falte ni sobre nada, sumar solo lo que la cotización no trae. Si viene a nombre de otra empresa,
  queda como pregunta para pedirla de nuevo a nombre del contratista.
- **Engineer's estimate**: se registra como referencia (`benchmark`), nunca se usa para fijar el precio.
- **Alcance "per GC direction"** cuando un addendum borró la sección pero el GC lo pide; paquetes de proveedor separados.
- **Condiciones de obra (8b)**: elevador/límites de acceso, hot work + fire watch, fireproofing (con pregunta de UL),
  grúa, diseño delegado PE, trabajo sobre agua/HPA, edificio ocupado. Cada una se cobra o se excluye.
- **Preguntas al GC** antes de liberar material.
- **Precio objetivo**: si piden un total, el agente NO mueve números; el reporte muestra la diferencia y el margen.
- **La propuesta no menciona** bids anteriores, competencia, engineer's estimate ni la comisión de Alkan.

## Controles automáticos nuevos (sanity.py → method_checks)
- `internal_leak`: palabras internas en scope / exclusiones / supuestos de la propuesta.
- `quote_no_ref`: renglón QUOTE sin número de cotización.
- `special_unpriced`: una condición especial aparece en las notas pero no está cobrada ni excluida.

## Reporte
- Sección "Referencias de precio" y sección "Precio objetivo" (alerta si queda bajo costo o con menos de 8%).

Pruebas: `tests/test_metal_method.py` (8 nuevas). Suite completa: 325 passed, 8 skipped.
Cambios sin commit: revisar y hacer commit en tu máquina.
