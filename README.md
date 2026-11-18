# ALKAN Bid Engine 3.8

**Nuevo en 3.8 — Proveedores y cambio de precios:** directorio de proveedores (Administrador → Proveedores) y `.\Start-Reprice.ps1` para cambiar precios o proveedores de un estimado ya hecho y volver a generar el paquete, con registro de antes y después. Ver [guía](docs/PROVEEDORES_Y_CAMBIOS_V3_8.md).

**Nuevo en 3.6 — App unificada y administrador:** `.\Start-BidEngine.ps1` abre una sola pantalla con Inicio, Nuevo estimado (subir PDF/ZIP → paquete de 3 documentos con avance en vivo), Entregas y Administrador (clave de API, modelo, método, entrega, contratistas, tarifas L&I, libro de precios, productividad). El agente usa Claude Fable 5.2 por defecto, decide GO/NO-GO antes de estimar, pasa una revisión independiente y controles automáticos. Ver [guía 3.6](docs/APP_V3_6.md).


**Nuevo en 3.5 — Agente estimador (API de Anthropic):** lee planos, specs y addenda (carpeta o ZIP) y produce el paquete de 3 documentos con el método ALKAN, más un reporte con fechas clave, riesgos y lo que hay que verificar. Ver [guía del agente](docs/AGENTE_ESTIMADOR.md).

```powershell
.\Configure-ClaudeAPI.ps1
.\Start-EstimateAgent.ps1 -Docs 'C:\ruta\Proyecto.zip' -Key PROYECTO
```


**En 3.4 — Paquete de 3 documentos (método S&S, nov 2026):** 01 Cost Analysis, 02 Material List & Price List y 03 Estimate/Proposal, generados desde un solo cálculo con prevailing wage + carga, markups secuenciales (contingencia → overhead → utilidad), redondeo a $50, comisión Alkan informativa y verificación cruzada entre los tres PDFs. Ver [metodología](docs/METODOLOGIA_PAQUETE_3_DOCUMENTOS.md).

```powershell
.\Start-Package.ps1 -InputFile 'examples\packages\*.json' -OutputDir ENTREGAS\PAQUETES
```

Motor de expedientes, estimación, costos y RFQ. Esta versión agrega compra por empaque, unidades US, medición calibrada y orquestador por fases con API configurable.

[Guía de entrega y validación](docs/RFQ_V3_3_ENTREGA.md).
[Paquete de prompts recibido](docs/PAQUETE_PROMPTS_ESTIMACION_RFQ.md).

## Instalar y abrir

Python 3.11 o posterior. Extraiga en una carpeta nueva; conserve los expedientes originales.

```powershell
.\Install-BidEngine.ps1
.\Start-BidEngine.ps1
```

Expedientes: http://127.0.0.1:8765

Medición y fases IA: http://127.0.0.1:8765/herramientas

La cuantificación y medición local no requieren una API. Para el orquestador configure su proveedor desde la misma ventana PowerShell:

```powershell
.\Configure-EstimationAPI.ps1 -BaseUrl 'https://SU_PROVEEDOR/v1' -Model 'NOMBRE_EXACTO'
.\Start-BidEngine.ps1
```

La clave se pide oculta, no se guarda en el ZIP. La conexión a su proveedor concreto sigue pendiente de comprobar.

## Ejemplos y pruebas

```powershell
.\Start-RFQ.ps1 -Tool calcular_takeoff -InputFile examples\rfq\rollos_request.json
.\Start-RFQ.ps1 -Tool peso_acero -InputFile examples\rfq\peso_us_request.json
.\Start-RFQ.ps1 -Tool esquemas
.\.venv\Scripts\python.exe -m pytest -q
```

230 LF con 5 % de desperdicio, en rollos de 50 LF: 5 rollos. Sin empaque explícito conserva la cantidad continua de la API anterior.

Los ejemplos DEMO son sintéticos. No se incluyen expedientes ni CSV históricos de clientes. Las ocho pruebas dependientes de esos datos se omiten mientras falten.

La IA produce borradores y pasa una auditoría separada; no aprueba por sí misma. La medición requiere marcar referencia y puntos. El laboratorio de reparación autónoma del Engineering Core no está implementado aquí.

[Guía histórica 3.2](docs/RFQ_V3_2_ENTREGA.md); prevalecen las instrucciones 3.3.
