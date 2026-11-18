import 'package:flutter/material.dart';

import 'alkan_flow.dart';
import 'alkan_loading_logo.dart';

/// Contenedor global para el flujo guiado P1–P7 usando los widgets de alkan_flow.dart.
class StepCoachShell extends StatelessWidget {
  final int stepNumber; // 1..7
  final int totalSteps;
  final String title;
  final String whyLabel;
  final String? feedsDocument;
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
    this.totalSteps = AlkanFlowCopy.totalSteps,
    required this.title,
    required this.whyLabel,
    this.feedsDocument,
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
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 8,
        title: const Row(
          children: [
            AlkanLogoBadge(size: 28, withBorder: false),
            SizedBox(width: 10),
            Text('Nuevo Estimado', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
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
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
            child: AlkanStepHeader(
              current: stepNumber,
              total: totalSteps,
              title: title,
              why: whyLabel,
              feedsDocument: feedsDocument,
            ),
          ),
          if (showCoachTip && firstTimeCoachTip != null && firstTimeCoachTip!.isNotEmpty && onDismissCoachTip != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
              child: AlkanCoachTip(
                text: firstTimeCoachTip!,
                onDismiss: onDismissCoachTip!,
              ),
            ),
          const Divider(height: 1),
          Expanded(child: child),
        ],
      ),
      bottomNavigationBar: showBottomBar
          ? AlkanStepNav(
              onBack: onBack,
              onNext: nextEnabled ? onNext : null,
              nextLabel: nextLabel,
            )
          : null,
    );
  }
}
