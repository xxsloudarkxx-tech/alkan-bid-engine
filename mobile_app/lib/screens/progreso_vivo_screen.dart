import 'dart:async';

import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';
import 'paquete_aprobacion_screen.dart';

/// Pantalla 3 — Progreso en Vivo conectado a RunManager con los 5 pasos del motor.
class ProgresoVivoScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final String runId;

  const ProgresoVivoScreen({
    super.key,
    required this.api,
    required this.store,
    required this.runId,
  });

  @override
  State<ProgresoVivoScreen> createState() => _ProgresoVivoScreenState();
}

class _ProgresoVivoScreenState extends State<ProgresoVivoScreen> {
  RunExecutiveSummary? _summary;
  String? _error;
  Timer? _timer;
  bool _navigated = false;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll() async {
    try {
      final sum = await widget.api.fetchRunSummary(widget.runId);
      if (!mounted) return;
      setState(() {
        _summary = sum;
        _error = null;
      });
      if (!sum.isRunning && !_navigated) {
        _timer?.cancel();
        _navigated = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted) return;
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(
              builder: (_) => PaqueteAprobacionScreen(
                api: widget.api,
                store: widget.store,
                runId: widget.runId,
              ),
            ),
          );
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final sum = _summary;
    final key = (sum?.run['key'] ?? widget.runId).toString();
    final percent = sum?.percent ?? 10;

    return Scaffold(
      appBar: AppBar(title: Text('Procesando $key')),
      body: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: AlkanColors.primary,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 3, color: Colors.amberAccent),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        sum?.stage.isNotEmpty == true ? sum!.stage : 'Iniciando agente estimador...',
                        style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w900),
                      ),
                    ),
                    Text(
                      '$percent%',
                      style: const TextStyle(color: Colors.amberAccent, fontSize: 22, fontWeight: FontWeight.w900),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: LinearProgressIndicator(
                    value: percent / 100.0,
                    minHeight: 12,
                    backgroundColor: Colors.white24,
                    valueColor: const AlwaysStoppedAnimation<Color>(Colors.amberAccent),
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Puedes salir de la app o apagar la pantalla. El servidor sigue trabajando y te avisará al terminar.',
                  style: TextStyle(color: Colors.white70, fontSize: 13.5),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const Text('Pasos del Motor ALKAN', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
          const SizedBox(height: 10),
          if (sum != null)
            for (final step in sum.steps) _buildStepTile(step)
          else
            const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text('Reintentando conexión: $_error', style: const TextStyle(color: AlkanColors.draft, fontWeight: FontWeight.w700)),
          ],
          if (sum != null && sum.events.isNotEmpty) ...[
            const SizedBox(height: 18),
            const Text('Actividad Reciente', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            for (final ev in sum.events.reversed.take(6))
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AlkanColors.border),
                  ),
                  child: Text(
                    '${ev['stage'] ?? 'Paso'}: ${ev['text'] ?? ''}',
                    style: const TextStyle(fontSize: 13.5, color: AlkanColors.ink),
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _buildStepTile(ProgressStepItem step) {
    IconData icon;
    Color color;
    switch (step.state) {
      case 'done':
        icon = Icons.check_circle;
        color = AlkanColors.approved;
        break;
      case 'active':
        icon = Icons.autorenew;
        color = AlkanColors.analyzing;
        break;
      case 'error':
        icon = Icons.error;
        color = AlkanColors.noGo;
        break;
      default:
        icon = Icons.radio_button_unchecked;
        color = AlkanColors.muted;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: step.state == 'active' ? AlkanColors.analyzing : AlkanColors.border,
          width: step.state == 'active' ? 2 : 1,
        ),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              '${step.index + 1}. ${step.label}',
              style: TextStyle(
                fontSize: 16,
                fontWeight: step.state == 'active' || step.state == 'done' ? FontWeight.w900 : FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
