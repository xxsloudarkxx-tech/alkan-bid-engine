// alkan_flow.dart — Widgets de flujo guiado para ALKAN Bid Engine.
//
// Piezas reutilizables para el flujo paso a paso del contratista, pensadas para
// adoptarse de forma INCREMENTAL sin reescribir las pantallas existentes:
//
//   • AlkanStepHeader   -> barra de progreso "Paso X de N" + título + "qué va aquí y por qué".
//   • AlkanStepNav      -> barra inferior fija con Atrás / Siguiente (o Generar), tamaño pulgar.
//   • AlkanSectionCard  -> envuelve una sección con número, título y la etiqueta de contexto;
//                          sirve YA en la pantalla actual de una sola página.
//   • AlkanCoachTip     -> tip de primer uso, descartable (sin dependencias externas).
//   • AlkanFlowCopy     -> textos "qué va aquí y por qué" de cada paso (del brief).
//
// Colócalo en: mobile_app/lib/widgets/alkan_flow.dart
// Importa el tema:  import '../theme/alkan_theme.dart';

import 'package:flutter/material.dart';
import '../theme/alkan_theme.dart';

/// Encabezado de paso: progreso + título + por qué. Úsalo arriba de cada paso/sección.
class AlkanStepHeader extends StatelessWidget {
  final int current; // 1-based
  final int total;
  final String title;
  final String why; // "qué va aquí y por qué"
  final String? feedsDocument; // opcional: a cuál de los 3 documentos alimenta

  const AlkanStepHeader({
    super.key,
    required this.current,
    required this.total,
    required this.title,
    required this.why,
    this.feedsDocument,
  });

  @override
  Widget build(BuildContext context) {
    final progress = total <= 0 ? 0.0 : current / total;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text('Paso $current de $total',
                style: const TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w800, color: AlkanColors.muted)),
            const Spacer(),
            if (feedsDocument != null)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AlkanColors.primary.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(feedsDocument!,
                    style: const TextStyle(
                        fontSize: 11, fontWeight: FontWeight.w700, color: AlkanColors.primary)),
              ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            value: progress,
            minHeight: 7,
            backgroundColor: AlkanColors.border,
            valueColor: const AlwaysStoppedAnimation<Color>(AlkanColors.accent),
          ),
        ),
        const SizedBox(height: 12),
        Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: AlkanColors.ink)),
        const SizedBox(height: 4),
        Text(why, style: const TextStyle(fontSize: 14, height: 1.3, color: AlkanColors.muted)),
      ],
    );
  }
}

/// Barra inferior fija con navegación. Botones grandes (zona del pulgar).
class AlkanStepNav extends StatelessWidget {
  final VoidCallback? onBack;
  final VoidCallback? onNext; // null => deshabilitado
  final String nextLabel;
  final bool loading;

  const AlkanStepNav({
    super.key,
    this.onBack,
    required this.onNext,
    this.nextLabel = 'Siguiente',
    this.loading = false,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Row(
          children: [
            if (onBack != null) ...[
              Expanded(
                flex: 2,
                child: OutlinedButton(
                  onPressed: loading ? null : onBack,
                  child: const Text('Atrás'),
                ),
              ),
              const SizedBox(width: 12),
            ],
            Expanded(
              flex: 3,
              child: ElevatedButton(
                onPressed: (loading || onNext == null) ? null : onNext,
                child: loading
                    ? const SizedBox(
                        height: 22, width: 22,
                        child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                    : Text(nextLabel),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Envuelve una sección con número, título y la etiqueta "qué va aquí y por qué".
/// Sirve YA en la pantalla actual de una sola página, sin convertir a stepper.
class AlkanSectionCard extends StatelessWidget {
  final int number;
  final String title;
  final String why;
  final Widget child;

  const AlkanSectionCard({
    super.key,
    required this.number,
    required this.title,
    required this.why,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 7),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CircleAvatar(
                  radius: 14,
                  backgroundColor: AlkanColors.primary,
                  child: Text('$number',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 14)),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(title,
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: AlkanColors.ink)),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(why, style: const TextStyle(fontSize: 13, height: 1.3, color: AlkanColors.muted)),
            const SizedBox(height: 14),
            child,
          ],
        ),
      ),
    );
  }
}

/// Tip de primer uso, descartable. Sin dependencias: el "ya lo vi" lo maneja el padre
/// (pásale un flag persistido con tu almacenamiento si quieres que no vuelva a salir).
class AlkanCoachTip extends StatelessWidget {
  final String text;
  final VoidCallback onDismiss;

  const AlkanCoachTip({super.key, required this.text, required this.onDismiss});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
      decoration: BoxDecoration(
        color: AlkanColors.accent.withOpacity(0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AlkanColors.accent.withOpacity(0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.lightbulb_outline, size: 20, color: AlkanColors.draft),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text,
                style: const TextStyle(fontSize: 13, height: 1.3, color: AlkanColors.ink)),
          ),
          IconButton(
            icon: const Icon(Icons.close, size: 18),
            color: AlkanColors.muted,
            onPressed: onDismiss,
            tooltip: 'Entendido',
          ),
        ],
      ),
    );
  }
}

/// Textos "qué va aquí y por qué" de cada paso (del brief). Úsalos tal cual.
class AlkanFlowCopy {
  static const int totalSteps = 7;

  static const proyectoWhy =
      'El condado define los salarios de la obra. Esto va en el Cost Analysis.';
  static const clienteWhy =
      'Al elegir el cliente, el documento sale con su nombre, su logo y sus exclusiones.';
  static const especialidadWhy =
      'Con la especialidad, el motor elige rendimientos y proveedores correctos.';
  static const alcanceWhy =
      'Habla como le dirías a tu ayudante. De aquí sale el alcance de los 3 documentos.';
  static const cantidadesWhy =
      'Revisa los números. Puedes corregir cualquiera con un toque. Siguen siendo presupuestarios hasta cotizar.';
  static const ajustesWhy =
      'Dejamos tus defaults. Toca solo si quieres cambiar el margen.';
  static const generarWhy =
      'Esto arma tus 3 documentos. Dura unos segundos.';

  // Etiquetas de a cuál documento alimenta cada paso (para el chip del header).
  static const feedsCostAnalysis = 'Cost Analysis';
  static const feedsLos3 = 'Los 3 documentos';
}

/*
EJEMPLO DE USO (adopción incremental, sin romper la pantalla actual):

  AlkanSectionCard(
    number: 1,
    title: 'Contratista y Especialidad',
    why: AlkanFlowCopy.clienteWhy,
    child: Column(children: [ ...tus dropdowns actuales... ]),
  ),

EJEMPLO como stepper (una pantalla por paso):

  Scaffold(
    appBar: AppBar(title: const Text('Nuevo Estimado')),
    body: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(children: [
        AlkanStepHeader(
          current: 1, total: AlkanFlowCopy.totalSteps,
          title: 'Proyecto',
          why: AlkanFlowCopy.proyectoWhy,
          feedsDocument: AlkanFlowCopy.feedsCostAnalysis,
        ),
        const SizedBox(height: 16),
        Expanded(child: SingleChildScrollView(child: ...campos del paso...)),
      ]),
    ),
    bottomNavigationBar: AlkanStepNav(
      onBack: _step > 1 ? _prev : null,
      onNext: _canAdvance ? _next : null,
      nextLabel: _step == AlkanFlowCopy.totalSteps ? 'Generar estimado' : 'Siguiente',
      loading: _busy,
    ),
  );
*/
