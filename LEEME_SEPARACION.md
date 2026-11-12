# ALKAN Bid Engine — copia de código original (2026-10-26)

Este ZIP es una **separación de archivos, no una refactorización**.

Contiene código fuente, pruebas, herramienta de generación, archivos de configuración, plantillas vacías y documentación técnica extraídos SIN ALTERACIONES del `spacework.zip` entregado por el usuario.

El expediente de P J Roofing LLC está en el paquete separado `PACK_PJ_ROOFING_PORT_TACOMA.zip`. El ZIP fuente no incluye PDFs oficiales, reportes finales, estimaciones ni datos de entrada de esa licitación.

## Limitaciones actuales

- **No es aún multi-cliente**: `src/bidkit/contractor.py`, `records.py` y los reportes contienen identidad/requisitos específicos de P J Roofing y Port of Tacoma.
- `config.py` encuentra PDFs que comienzan con `072026-1044_` en la raíz del proyecto.
- `__main__.py` usa una ruta absoluta de Node.js dentro de `C:\Users\diana`, por lo que la generación de hojas Excel no es portable todavía.
- Para ejecutar el proyecto actual se requieren los documentos y datos originales de la licitación y las dependencias apropiadas.
- El archivo `PRE_COMMIT_AUDIT.md` recoge afirmaciones reportadas por Claude, no una auditoría independiente de todas las pruebas. El código del ZIP se verificó sintácticamente; no se ejecutó toda la suite.
- Este paquete no incluye historial Git ni representa confirmación de un commit.

## Política

La separación no modifica los originales ni convierte una oferta interna en una propuesta lista para entregar. No se añaden credenciales.
