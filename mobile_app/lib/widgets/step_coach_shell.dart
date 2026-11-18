import 'package:flutter/material.dart';

import '../theme/alkan_theme.dart';
import 'alkan_loading_logo.dart';

/// Contenedor global para el flujo guiado P1–P7 con stepper, etiqueta "qué va aquí y por qué",
/// pista descartable la primera vez y botones fijos abajo para el pulgar.
class StepCoachShell extends StatelessWidget {
  final int stepNumber; // 1..7
  final int totalSteps;
  final String title;
  final String whyLabel;
  final String? firstTimeCoachTip;
  final bool showCoachTip;
  final VoidCallback? onDismissCoachTip;
  final Widget child;
  final VoidCallback? onBack;
  final VoidCallback? onNext;
  final String nextLabel;
  final bool nextEnabled;
  final bool showBottomBar;
  final bool isOnline;

  const StepCoachShell({
    super.key,
    required this.stepNumber,
    this.totalSteps = 7,
    required this.title,
    required this.whyLabel,
    this.firstTimeCoachTip,
    this.showCoachTip = false,
    this.onDismissCoachTip,
    required this.child,
    this.onBack,
    this.onNext,
    this.nextLabel = 'Siguiente',
    this.nextEnabled = true,
    this.showBottomBar = true,
    this.isOnline = true,
  });

  @override
  Widget build(BuildContext context) {
    final progress = (stepNumber / totalSteps).clamp(0.0, 1.0);
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 8,
        title: Row(
          children: [
            const AlkanLogoBadge(size: 28, withBorder: false),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                'Paso $stepNumber de $totalSteps · $title',
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
              ),
            ),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Icon(
              isOnline ? Icons.cloud_done : Icons.cloud_off,
              color: isOnline ? Colors.greenAccent : Colors.amberAccent,
              size: 22,
            ),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(8),
          child: LinearProgressIndicator(
            value: progress,
            minHeight: 8,
            backgroundColor: Colors.white24,
            valueColor: const AlwaysStoppedAnimation<Color>(Colors.amberAccent),
          ),
        ),
      ),
      body: Column(
        children: [
          // Etiqueta visible "qué va aquí y por qué"
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              color: AlkanColors.primary.withOpacity(0.08),
              border: const Border(bottom: BorderSide(color: AlkanColors.border)),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.info_outline, size: 20, color: AlkanColors.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    whyLabel,
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                      color: AlkanColors.primary,
                      height: 1.3,
                    ),
                  ),
                ),
              ],
            ),
          ),
          // Pista contextual solo en el primer uso (descartable con un toque)
          if (showCoachTip && firstTimeCoachTip != null && firstTimeCoachTip!.isNotEmpty)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: Colors.amber.shade50,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AlkanColors.accent, width: 1.6),
              ),
              child: Row(
                children: [
                  const Icon(Icons.lightbulb, color: AlkanColors.accent, size: 22),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      firstTimeCoachTip!,
                      style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AlkanColors.ink),
                    ),
                  ),
                  TextButton(
                    onPressed: onDismissCoachTip,
                    child: const Text('Entendido', style: TextStyle(fontWeight: FontWeight.w900)),
                  ),
                ],
              ),
            ),
          Expanded(child: child),
        ],
      ),
      bottomNavigationBar: showBottomBar
          ? SafeArea(
              child: Container(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
                decoration: const BoxDecoration(
                  color: Colors.white,
                  border: Border(top: BorderSide(color: AlkanColors.border)),
                ),
                child: Row(
                  children: [
                    if (onBack != null)
                      Expanded(
                        flex: 4,
                        child: OutlinedButton.icon(
                          onPressed: onBack,
                          style: OutlinedButton.styleFrom(minimumSize: const Size(0, 54)),
                          icon: const Icon(Icons.arrow_back),
                          label: const Text('Atrás'),
                        ),
                      ),
                    if (onBack != null && onNext != null) const SizedBox(width: 12),
                    if (onNext != null)
                      Expanded(
                        flex: 6,
                        child: ElevatedButton.icon(
                          onPressed: nextEnabled ? onNext : null,
                          style: ElevatedButton.styleFrom(minimumSize: const Size(0, 54)),
                          icon: const Icon(Icons.arrow_forward),
                          label: Text(nextLabel),
                        ),
                      ),
                  ],
                ),
              ),
            )
          : null,
    );
  }
}
