import 'dart:io';

import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';
import 'mi_empresa_precios_screen.dart';
import 'nuevo_estimado_screen.dart';
import 'paquete_aprobacion_screen.dart';
import 'progreso_vivo_screen.dart';

/// Pantalla 1 — Mis Estimados (Inicio) con semáforo visual y sincronización offline.
class MisEstimadosScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final VoidCallback onLogout;

  const MisEstimadosScreen({
    super.key,
    required this.api,
    required this.store,
    required this.onLogout,
  });

  @override
  State<MisEstimadosScreen> createState() => _MisEstimadosScreenState();
}

class _MisEstimadosScreenState extends State<MisEstimadosScreen> with WidgetsBindingObserver {
  List<EstimateRunCard> _runs = [];
  List<PendingOfflineEstimate> _pendingOffline = [];
  bool _loading = true;
  bool _isOnline = true;
  bool _syncing = false;
  String _filter = 'all';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    _checkSharedFiles();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _checkSharedFiles();
    }
  }

  Future<void> _checkSharedFiles() async {
    final shared = await widget.api.consumeSharedFiles();
    if (shared.isNotEmpty && mounted) {
      await _openNewEstimate(initialFiles: shared);
    }
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    final pending = await widget.store.loadPendingDrafts();
    try {
      final runs = await widget.api.fetchRuns();
      await widget.store.saveCachedRuns(runs);
      if (mounted) {
        setState(() {
          _runs = runs;
          _pendingOffline = pending;
          _isOnline = true;
          _loading = false;
        });
      }
      if (pending.isNotEmpty) {
        await _syncPendingDrafts();
      }
    } catch (_) {
      final cached = await widget.store.loadCachedRuns();
      if (mounted) {
        setState(() {
          _runs = cached;
          _pendingOffline = pending;
          _isOnline = false;
          _loading = false;
        });
      }
    }
  }

  Future<void> _syncPendingDrafts() async {
    if (_syncing) return;
    final pending = await widget.store.loadPendingDrafts();
    if (pending.isEmpty) return;
    setState(() => _syncing = true);
    for (final draft in pending) {
      try {
        String? uploadId;
        if (draft.filePaths.isNotEmpty) {
          uploadId = widget.api.newUploadId();
          for (final p in draft.filePaths) {
            final f = File(p);
            if (await f.exists()) {
              await widget.api.uploadChunkedFile(uploadId: uploadId, file: f);
            }
          }
        }
        if (draft.useQuickPackage || uploadId == null) {
          await widget.api.startQuickPackage(
            key: draft.key,
            projectTitle: draft.projectTitle,
            profile: draft.profile,
            specialty: draft.specialty,
            county: draft.county,
            voiceNotes: draft.voiceNotes,
            uploadId: uploadId,
          );
        } else {
          await widget.api.startAgentRun(
            key: draft.key,
            profile: draft.profile,
            tradeScope: draft.specialty,
            uploadId: uploadId,
            notes: draft.voiceNotes,
          );
        }
        await widget.store.removePendingDraft(draft.localId);
      } catch (_) {
        break;
      }
    }
    if (mounted) setState(() => _syncing = false);
    await _refresh();
  }

  Future<void> _openNewEstimate({List<String> initialFiles = const []}) async {
    final created = await Navigator.push<String>(
      context,
      MaterialPageRoute(
        builder: (_) => NuevoEstimadoScreen(
          api: widget.api,
          store: widget.store,
          initialFiles: initialFiles,
        ),
      ),
    );
    await _refresh();
    if (created != null && mounted) {
      await _openRun(created, forceProgress: true);
    }
  }

  Future<void> _openRun(String runId, {bool forceProgress = false}) async {
    final matches = _runs.where((r) => r.id == runId);
    final card = matches.isNotEmpty ? matches.first : null;
    final analyzing = forceProgress || card?.badgeStatus == 'analyzing';
    if (analyzing) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ProgresoVivoScreen(api: widget.api, store: widget.store, runId: runId),
        ),
      );
    } else {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PaqueteAprobacionScreen(api: widget.api, store: widget.store, runId: runId),
        ),
      );
    }
    await _refresh();
  }

  Color _badgeColor(String status) {
    switch (status) {
      case 'analyzing':
        return AlkanColors.analyzing;
      case 'approved':
        return AlkanColors.approved;
      case 'no_go':
      case 'error':
        return AlkanColors.noGo;
      default:
        return AlkanColors.draft;
    }
  }

  String _badgeEmoji(String status) {
    switch (status) {
      case 'analyzing':
        return '🟡';
      case 'approved':
        return '🟢';
      case 'no_go':
      case 'error':
        return '🔴';
      default:
        return '🟠';
    }
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _runs.where((r) => _filter == 'all' || r.badgeStatus == _filter).toList();
    final actor = widget.api.session?.actor ?? '';
    final role = widget.api.session?.role ?? '';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Mis Estimados'),
        actions: [
          IconButton(
            tooltip: 'Mi Empresa y Precios',
            icon: const Icon(Icons.business_center, size: 26),
            onPressed: () async {
              await Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => MiEmpresaPreciosScreen(api: widget.api),
                ),
              );
            },
          ),
          IconButton(
            tooltip: 'Cerrar sesión',
            icon: const Icon(Icons.logout),
            onPressed: widget.onLogout,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Barra de sincronización Online / Offline
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: _isOnline ? Colors.green.shade50 : Colors.amber.shade50,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: _isOnline ? AlkanColors.approved : AlkanColors.accent,
                  width: 1.4,
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    _isOnline ? Icons.cloud_done : Icons.cloud_off,
                    color: _isOnline ? AlkanColors.approved : AlkanColors.accent,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      _isOnline
                          ? 'En línea · $actor ($role)'
                          : 'Modo Offline · Mostrando estimados guardados',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5),
                    ),
                  ),
                  if (_pendingOffline.isNotEmpty)
                    TextButton(
                      onPressed: _syncing ? null : _syncPendingDrafts,
                      child: Text(
                        _syncing ? 'Subiendo...' : 'Sincronizar (${_pendingOffline.length})',
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            // Botón gigante principal "+ NUEVO ESTIMADO"
            ElevatedButton.icon(
              onPressed: () => _openNewEstimate(),
              style: ElevatedButton.styleFrom(
                backgroundColor: AlkanColors.primary,
                minimumSize: const Size(double.infinity, 68),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              ),
              icon: const Icon(Icons.add_circle_outline, size: 30),
              label: const Text('+ NUEVO ESTIMADO', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900)),
            ),
            const SizedBox(height: 12),
            // Acceso rápido a Pantalla 5: Mi Empresa y Precios
            OutlinedButton.icon(
              onPressed: () async {
                await Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => MiEmpresaPreciosScreen(api: widget.api)),
                );
              },
              icon: const Icon(Icons.storefront),
              label: const Text('Mi Empresa, Logo y Cotizaciones'),
            ),
            const SizedBox(height: 16),
            // Filtros rápidos por semáforo
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  _chip('Todos', 'all'),
                  const SizedBox(width: 8),
                  _chip('🟡 Analizando', 'analyzing'),
                  const SizedBox(width: 8),
                  _chip('🟠 DRAFT', 'draft_ready'),
                  const SizedBox(width: 8),
                  _chip('🟢 Autorizado', 'approved'),
                  const SizedBox(width: 8),
                  _chip('🔴 NO-GO', 'no_go'),
                ],
              ),
            ),
            const SizedBox(height: 14),
            if (_pendingOffline.isNotEmpty) ...[
              for (final p in _pendingOffline)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Card(
                    child: ListTile(
                      contentPadding: const EdgeInsets.all(14),
                      leading: const Text('⏳', style: TextStyle(fontSize: 26)),
                      title: Text('${p.key} · En cola offline', style: const TextStyle(fontWeight: FontWeight.w800)),
                      subtitle: Text('${p.specialty.toUpperCase()} · ${p.county} Co.\nSe enviará al recuperar señal.'),
                    ),
                  ),
                ),
            ],
            if (_loading && _runs.isEmpty)
              const Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (filtered.isEmpty)
              Container(
                padding: const EdgeInsets.all(28),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: AlkanColors.border),
                ),
                child: const Column(
                  children: [
                    Icon(Icons.folder_open, size: 48, color: AlkanColors.muted),
                    SizedBox(height: 10),
                    Text(
                      'No hay estimados en esta vista.\nToca "+ NUEVO ESTIMADO" para subir tus planos o dictar un trabajo.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 15, color: AlkanColors.muted, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              )
            else
              for (final r in filtered)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Card(
                    child: InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: () => _openRun(r.id),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Text(_badgeEmoji(r.badgeStatus), style: const TextStyle(fontSize: 20)),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    r.key,
                                    style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                                  decoration: BoxDecoration(
                                    color: _badgeColor(r.badgeStatus).withOpacity(0.14),
                                    borderRadius: BorderRadius.circular(20),
                                    border: Border.all(color: _badgeColor(r.badgeStatus)),
                                  ),
                                  child: Text(
                                    r.badgeLabel,
                                    style: TextStyle(
                                      color: _badgeColor(r.badgeStatus),
                                      fontWeight: FontWeight.w800,
                                      fontSize: 12.5,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text(
                              r.contractor.isNotEmpty ? r.contractor : r.profile,
                              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AlkanColors.ink),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              r.stage,
                              style: const TextStyle(fontSize: 13.5, color: AlkanColors.muted),
                            ),
                            const SizedBox(height: 10),
                            Row(
                              children: [
                                if (r.price != null && r.price!.isNotEmpty)
                                  Text(
                                    '\$${r.price}',
                                    style: const TextStyle(
                                      fontSize: 22,
                                      fontWeight: FontWeight.w900,
                                      color: AlkanColors.primary,
                                    ),
                                  )
                                else
                                  Text(
                                    'Progreso: ${r.progressPct}%',
                                    style: const TextStyle(fontWeight: FontWeight.w800, color: AlkanColors.accent),
                                  ),
                                const Spacer(),
                                if (r.budgetCount > 0)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: Colors.red.shade50,
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: Text(
                                      '${r.budgetCount} BUDGET',
                                      style: const TextStyle(
                                        color: AlkanColors.noGo,
                                        fontWeight: FontWeight.w800,
                                        fontSize: 12,
                                      ),
                                    ),
                                  ),
                                const SizedBox(width: 8),
                                Icon(
                                  r.clientShareUnlocked ? Icons.lock_open : Icons.lock_outline,
                                  color: r.clientShareUnlocked ? AlkanColors.approved : AlkanColors.draft,
                                  size: 20,
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
          ],
        ),
      ),
    );
  }

  Widget _chip(String label, String key) {
    final selected = _filter == key;
    return ChoiceChip(
      label: Text(label, style: TextStyle(fontWeight: FontWeight.w800, color: selected ? Colors.white : AlkanColors.ink)),
      selected: selected,
      selectedColor: AlkanColors.primary,
      onSelected: (_) => setState(() => _filter = key),
    );
  }
}
