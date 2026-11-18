import 'dart:io';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:share_plus/share_plus.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../services/voice_dictation_service.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_components.dart';
import '../widgets/alkan_loading_logo.dart';

/// Documentos reales (01 Cost Analysis, 02 Material List, 03 Client Proposal) + Control Humano.
class PaqueteAprobacionScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final String runId;

  const PaqueteAprobacionScreen({
    super.key,
    required this.api,
    required this.store,
    required this.runId,
  });

  @override
  State<PaqueteAprobacionScreen> createState() => _PaqueteAprobacionScreenState();
}

class _PaqueteAprobacionScreenState extends State<PaqueteAprobacionScreen> {
  RunExecutiveSummary? _summary;
  bool _loading = true;
  bool _busyAction = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final sum = await widget.api.fetchRunSummary(widget.runId);
      if (mounted) {
        setState(() {
          _summary = sum;
          _error = null;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  Future<File?> _ensurePdfDownloaded(DeliverableDocItem doc) async {
    final cached = await widget.store.getCachedPdf(widget.runId, doc.filename);
    if (cached != null && _summary?.isApproved == false) {
      return cached;
    }
    try {
      final bytes = await widget.api.downloadRunFile(widget.runId, doc.filename);
      return widget.store.saveLocalPdf(widget.runId, doc.filename, bytes);
    } catch (_) {
      if (cached != null) return cached;
      rethrow;
    }
  }

  Future<void> _openPdf(DeliverableDocItem doc) async {
    setState(() => _busyAction = true);
    try {
      final file = await _ensurePdfDownloaded(doc);
      if (file == null) throw Exception('Archivo no disponible');
      await OpenFilex.open(file.path);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo abrir: $e')));
      }
    } finally {
      if (mounted) setState(() => _busyAction = false);
    }
  }

  Future<void> _shareProposalToClient(DeliverableDocItem proposalDoc) async {
    if (_summary?.clientShareUnlocked != true || !proposalDoc.shareToClientAllowed) return;
    setState(() => _busyAction = true);
    try {
      final bytes = await widget.api.downloadRunFile(widget.runId, proposalDoc.filename);
      final file = await widget.store.saveLocalPdf(widget.runId, proposalDoc.filename, bytes);
      await Share.shareXFiles(
        [XFile(file.path)],
        subject: 'Propuesta Oficial — ${proposalDoc.filename}',
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al compartir: $e')));
      }
    } finally {
      if (mounted) setState(() => _busyAction = false);
    }
  }

  Future<void> _openVoiceAdjustmentDialog() async {
    final ctrl = TextEditingController();
    final voice = VoiceDictationService();
    bool listening = false;

    final saved = await showDialog<String>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) => AlertDialog(
          title: const Text('Pedir Ajuste por Voz', style: TextStyle(fontWeight: FontWeight.w900)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ElevatedButton.icon(
                style: ElevatedButton.styleFrom(backgroundColor: listening ? AlkanColors.noGo : AlkanColors.primary),
                onPressed: () async {
                  if (listening) {
                    await voice.stopListening();
                    setModalState(() => listening = false);
                  } else {
                    final ok = await voice.startListening(
                      onText: (t, isFinal) {
                        ctrl.text = t;
                        if (isFinal) setModalState(() => listening = false);
                      },
                    );
                    if (ok) setModalState(() => listening = true);
                  }
                },
                icon: Icon(listening ? Icons.stop : Icons.mic),
                label: Text(listening ? 'Detener dictado' : 'Dictar ajuste por voz'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: ctrl,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Instrucción de ajuste',
                  hintText: 'Ej. Subir utilidad a 12% y revisar partida M003',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('Guardar Nota'),
            ),
          ],
        ),
      ),
    );
    if (saved != null && saved.isNotEmpty) {
      await widget.api.recordVoiceNote(runId: widget.runId, transcript: saved, kind: 'adjustment_request');
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Ajuste registrado en bitácora.')));
      }
    }
  }

  Future<void> _authorizePackage() async {
    final sum = _summary;
    if (sum == null) return;
    final session = widget.api.session!;
    final preparedBy = (sum.humanLock['prepared_by'] ?? '').toString();
    final needsIndependentLogin =
        session.actor.toLowerCase() == preparedBy.toLowerCase() || (session.role != 'reviewer' && session.role != 'admin');

    final userCtrl = TextEditingController(text: needsIndependentLogin ? '' : session.actor);
    final passCtrl = TextEditingController();
    final noteCtrl = TextEditingController();

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Autorizar Paquete Final', style: TextStyle(fontWeight: FontWeight.w900)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                needsIndependentLogin
                    ? 'Control humano estricto: quien preparó el estimado ($preparedBy) no puede auto-aprobarlo. Ingresa credenciales de un revisor/aprobador independiente:'
                    : 'Confirmas que revisaste los 3 documentos y autorizas liberar la Propuesta 03 (sin marca DRAFT).',
                style: const TextStyle(fontSize: 13.5, color: AlkanColors.textSecondary),
              ),
              if (needsIndependentLogin) ...[
                const SizedBox(height: 12),
                TextField(controller: userCtrl, decoration: const InputDecoration(labelText: 'Usuario Aprobador')),
                const SizedBox(height: 10),
                TextField(controller: passCtrl, obscureText: true, decoration: const InputDecoration(labelText: 'Contraseña')),
              ],
              const SizedBox(height: 10),
              TextField(
                controller: noteCtrl,
                decoration: const InputDecoration(labelText: 'Nota de autorización (opcional)'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AlkanColors.approved),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('AUTORIZAR AHORA'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;
    setState(() => _busyAction = true);
    try {
      String? reviewerToken;
      if (needsIndependentLogin) {
        final tempClient = BidKitApiClient();
        final revSession = await tempClient.login(
          baseUrl: session.baseUrl,
          username: userCtrl.text.trim(),
          password: passCtrl.text,
        );
        reviewerToken = revSession.token;
      }
      await widget.api.approveRun(
        runId: widget.runId,
        note: noteCtrl.text.trim(),
        reviewerToken: reviewerToken,
      );
      await _load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Paquete autorizado. Propuesta 03 desbloqueada para compartir.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo autorizar: $e')));
      }
    } finally {
      if (mounted) setState(() => _busyAction = false);
    }
  }

  Future<void> _rejectPackage() async {
    final reasonCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Marcar NO-GO / Rechazar', style: TextStyle(fontWeight: FontWeight.w900)),
        content: TextField(
          controller: reasonCtrl,
          maxLines: 3,
          decoration: const InputDecoration(
            labelText: 'Motivo de rechazo o NO-GO',
            hintText: 'Ej. Fuera de alcance, fecha vencida o margen insuficiente',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AlkanColors.noGo),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('MARCAR NO-GO'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busyAction = true);
    try {
      await widget.api.rejectRun(runId: widget.runId, reason: reasonCtrl.text.trim());
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al rechazar: $e')));
      }
    } finally {
      if (mounted) setState(() => _busyAction = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sum = _summary;
    if (_loading) {
      return const Scaffold(
        body: Center(child: AlkanLoadingAnimation(size: 84, label: 'Cargando paquete de documentos...')),
      );
    }
    if (sum == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Paquete de Documentos')),
        body: Center(child: Text(_error ?? 'No se pudo cargar el resumen')),
      );
    }

    final run = sum.run;
    final fin = sum.financials;
    final alerts = fin['pricing_alerts'] as Map<String, dynamic>? ?? const {};
    final budgetCount = (alerts['budget_count'] as num? ?? 0).toInt();
    final quoteCount = (alerts['quote_count'] as num? ?? 0).toInt();
    final propMatches = sum.documents.where((d) => d.docType == 'proposal');
    final proposalDoc = propMatches.isNotEmpty ? propMatches.first : null;

    final lockColor = sum.isApproved
        ? AlkanColors.approved
        : sum.isRejectedOrNoGo
            ? AlkanColors.noGo
            : AlkanColors.draft;

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const AlkanLogoBadge(size: 30, withBorder: false),
            const SizedBox(width: 10),
            Expanded(child: Text('Documentos · ${run['key'] ?? ''}', overflow: TextOverflow.ellipsis)),
          ],
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Estado de Control Humano
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: lockColor.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: lockColor.withOpacity(0.7), width: 1.5),
                ),
                child: Row(
                  children: [
                    Icon(
                      sum.isApproved
                          ? Icons.verified
                          : sum.isRejectedOrNoGo
                              ? Icons.block
                              : Icons.lock_outline,
                      color: lockColor,
                      size: 28,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        (sum.humanLock['lock_message'] ?? '').toString(),
                        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5, color: AlkanColors.textPrimary),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),

              // Totales calculados exclusivamente por el motor
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text((run['contractor'] ?? '').toString(), style: const TextStyle(fontWeight: FontWeight.w800, color: AlkanColors.textSecondary)),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 12,
                        crossAxisAlignment: WrapCrossAlignment.end,
                        children: [
                          Text(
                            '\$${fin['sell_price'] ?? '0.00'}',
                            style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900, color: AlkanColors.primary),
                          ),
                          Padding(
                            padding: const EdgeInsets.only(bottom: 5),
                            child: Text(
                              'Margen bruto: \$${fin['gross_margin'] ?? '--'}',
                              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: AlkanColors.approved),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          _statPill('Directo: \$${fin['direct_cost'] ?? '0.00'}', AlkanColors.azulInstitucional),
                          _statPill('QA: ${run['qa'] ?? 'N/A'}', run['qa'] == 'PASS' ? AlkanColors.approved : AlkanColors.noGo),
                          _statPill('Decisión: ${run['decision'] ?? 'GO'}', run['decision'] == 'NO_GO' ? AlkanColors.noGo : AlkanColors.approved),
                          _statPill('$quoteCount QUOTE · $budgetCount BUDGET', budgetCount > 0 ? AlkanColors.noGo : AlkanColors.approved),
                        ],
                      ),
                      if (budgetCount > 0) ...[
                        const SizedBox(height: 10),
                        Text(
                          '⚠️ Hay $budgetCount partidas BUDGET (marcadas en rojo en 02 Material List) pendientes de cotización real.',
                          style: const TextStyle(color: AlkanColors.noGo, fontWeight: FontWeight.w700, fontSize: 13),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 18),

              const Text('Los 3 Documentos del Motor', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: AlkanColors.azulSuave,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Text(
                  '01 Cost Analysis es confidencial interno. 03 Client Proposal solo se libera tras aprobación independiente.',
                  style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AlkanColors.azulInstitucional),
                ),
              ),
              const SizedBox(height: 10),
              for (final doc in sum.documents)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: AlkanDocumentCard(
                    doc: doc,
                    busy: _busyAction,
                    onView: () => _openPdf(doc),
                    onShare: doc.shareToClientAllowed ? () => _shareProposalToClient(doc) : null,
                  ),
                ),

              const SizedBox(height: 8),
              AlkanPrimaryButton(
                label: sum.clientShareUnlocked
                    ? 'Enviar al GC (03 Proposal autorizado)'
                    : 'Enviar al GC (bloqueado hasta autorización)',
                icon: sum.clientShareUnlocked ? Icons.share : Icons.lock_outline,
                backgroundColor: sum.clientShareUnlocked ? AlkanColors.primary : AlkanColors.textSecondary,
                onPressed: (_busyAction || !sum.clientShareUnlocked || proposalDoc == null)
                    ? null
                    : () => _shareProposalToClient(proposalDoc),
              ),

              const SizedBox(height: 14),
              const Divider(),
              const SizedBox(height: 10),

              if (!sum.isApproved && !sum.isRejectedOrNoGo) ...[
                AlkanPrimaryButton(
                  label: 'Mandar a revisión / Autorizar paquete',
                  icon: Icons.check_circle_outline,
                  backgroundColor: AlkanColors.approved,
                  loading: _busyAction,
                  onPressed: _authorizePackage,
                ),
                const SizedBox(height: 10),
              ],
              Row(
                children: [
                  Expanded(
                    child: AlkanSecondaryButton(
                      label: 'Ajuste por voz',
                      icon: Icons.mic_outlined,
                      onPressed: _busyAction ? null : _openVoiceAdjustmentDialog,
                    ),
                  ),
                  if (!sum.isApproved && !sum.isRejectedOrNoGo) ...[
                    const SizedBox(width: 10),
                    Expanded(
                      child: AlkanSecondaryButton(
                        label: 'Marcar NO-GO',
                        icon: Icons.cancel_outlined,
                        foregroundColor: AlkanColors.noGo,
                        borderColor: AlkanColors.noGo,
                        onPressed: _busyAction ? null : _rejectPackage,
                      ),
                    ),
                  ],
                ],
              ),

              if (sum.voiceNotes.isNotEmpty) ...[
                const SizedBox(height: 18),
                const Text('Notas de Voz Registradas', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w900)),
                const SizedBox(height: 8),
                for (final vn in sum.voiceNotes)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Card(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Text('🎙️ ${vn['actor']}: ${vn['transcript']}'),
                      ),
                    ),
                  ),
              ],
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Widget _statPill(String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12.5)),
    );
  }
}
