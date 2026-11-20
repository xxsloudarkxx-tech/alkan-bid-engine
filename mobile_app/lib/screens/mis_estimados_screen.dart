import 'dart:io';

import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_components.dart';
import '../widgets/alkan_loading_logo.dart';
import 'estimate_flow_screen.dart';
import 'mi_empresa_precios_screen.dart';
import 'paquete_aprobacion_screen.dart';
import 'progreso_vivo_screen.dart';

/// Centro de Operaciones ALKAN BidEngine 2.0 — Home, Pipeline CRM, Contratistas y Calibración.
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
  int _tabIndex = 0; // 0 = Inicio, 2 = Contratistas, 3 = Calibración (1 = Dictar abre flujo)
  String _calFocusModule = 'ALL';

  List<EstimateRunCard> _runs = [];
  List<PendingOfflineEstimate> _pendingOffline = [];
  List<ContractorProfileItem> _profiles = List.of(defaultAlkanProfiles);
  String _activeProfile = defaultAlkanProfiles.first.name;
  ProfileCalibration? _calibration;

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

  List<ContractorProfileItem> _mergeProfiles(List<ContractorProfileItem> incoming) {
    final byName = <String, ContractorProfileItem>{
      for (final p in defaultAlkanProfiles) p.name: p,
    };
    for (final p in incoming) {
      byName[p.name] = p;
    }
    return byName.values.toList();
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    final pending = await widget.store.loadPendingDrafts();
    final cachedRuns = await widget.store.loadCachedRuns();
    final cachedProfs = await widget.store.loadCachedProfiles();
    if (mounted) {
      setState(() {
        _pendingOffline = pending;
        if (cachedRuns.isNotEmpty) _runs = cachedRuns;
        if (cachedProfs.isNotEmpty) _profiles = _mergeProfiles(cachedProfs);
      });
    }

    try {
      final results = await Future.wait<dynamic>([
        widget.api.fetchRuns(),
        widget.api.fetchProfiles(),
      ]);
      final runs = results[0] as List<EstimateRunCard>;
      final profs = _mergeProfiles([...cachedProfs, ...(results[1] as List<ContractorProfileItem>)]);
      await widget.store.saveCachedRuns(runs);
      await widget.store.saveCachedProfiles(profs);
      if (!profs.any((p) => p.name == _activeProfile) && profs.isNotEmpty) {
        _activeProfile = profs.first.name;
      }
      ProfileCalibration? cal;
      try {
        cal = await widget.api.fetchCalibration(_activeProfile);
      } catch (_) {}
      if (mounted) {
        setState(() {
          _runs = runs;
          _profiles = profs;
          _calibration = cal;
          _pendingOffline = pending;
          _isOnline = true;
          _loading = false;
        });
      }
      if (pending.isNotEmpty) {
        await _syncPendingDrafts();
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _runs = cachedRuns;
          _pendingOffline = pending;
          _isOnline = false;
          _loading = false;
        });
      }
    }
  }

  Future<void> _selectActiveProfile(String name) async {
    setState(() => _activeProfile = name);
    try {
      final cal = await widget.api.fetchCalibration(name);
      if (mounted) setState(() => _calibration = cal);
    } catch (_) {
      if (mounted) setState(() => _calibration = null);
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
            specialties: draft.specialties,
            county: draft.county,
            voiceNotes: draft.voiceNotes,
            uploadId: uploadId,
            materialsOverrides: draft.materialsOverrides,
            laborOverrides: draft.laborOverrides,
            markups: draft.markups,
            validityDays: draft.validityDays,
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
        builder: (_) => EstimateFlowScreen(
          api: widget.api,
          store: widget.store,
          initialFiles: initialFiles,
          initialProfile: _activeProfile,
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

  Future<bool> _confirmDeleteRun(EstimateRunCard run) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Eliminar Estimado', style: TextStyle(fontWeight: FontWeight.w900)),
        content: Text('¿Deseas eliminar "${run.key}"? Se borrará de la lista y del almacenamiento del servidor.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: AlkanColors.noGo),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('ELIMINAR'),
          ),
        ],
      ),
    );
    if (confirmed != true) return false;

    try {
      await widget.api.deleteRun(run.id);
    } catch (_) {}
    if (mounted) {
      setState(() {
        _runs.removeWhere((r) => r.id == run.id);
      });
      await widget.store.saveCachedRuns(_runs);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Estimado ${run.key} eliminado correctamente.')),
      );
    }
    return true;
  }

  Future<void> _resumeOrEditRun(EstimateRunCard run) async {
    String? voiceNotes;
    try {
      final summary = await widget.api.fetchRunSummary(run.id);
      final rawNotes = summary.run['voice_notes'] ?? summary.run['notes'];
      if (rawNotes is String) voiceNotes = rawNotes;
    } catch (_) {}

    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => EstimateFlowScreen(
          api: widget.api,
          store: widget.store,
          initialProfile: run.profile,
          initialTitle: run.key,
          initialVoiceNotes: voiceNotes,
          initialCounty: run.county,
          initialSpecialties: [run.specialty],
        ),
      ),
    );
    await _refresh();
  }

  void _showRunOptionsSheet(EstimateRunCard run) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 12),
                decoration: BoxDecoration(color: Colors.grey.shade400, borderRadius: BorderRadius.circular(2)),
              ),
              ListTile(
                leading: const Icon(Icons.remove_red_eye_outlined, color: AlkanColors.primary),
                title: const Text('Ver paquete de documentos', style: TextStyle(fontWeight: FontWeight.w700)),
                subtitle: Text('${run.key} · ${run.badgeLabel}'),
                onTap: () {
                  Navigator.pop(ctx);
                  _openRun(run.id);
                },
              ),
              ListTile(
                leading: const Icon(Icons.edit_note_rounded, color: Colors.blue),
                title: const Text('Editar / Continuar estimado', style: TextStyle(fontWeight: FontWeight.w700)),
                subtitle: const Text('Abre el asistente con los datos de este estimado'),
                onTap: () {
                  Navigator.pop(ctx);
                  _resumeOrEditRun(run);
                },
              ),
              const Divider(),
              ListTile(
                leading: const Icon(Icons.delete_outline_rounded, color: AlkanColors.noGo),
                title: const Text('Eliminar estimado', style: TextStyle(fontWeight: FontWeight.w700, color: AlkanColors.noGo)),
                subtitle: const Text('Borra este estimado del servidor'),
                onTap: () {
                  Navigator.pop(ctx);
                  _confirmDeleteRun(run);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _registerContractorIsolated() async {
    final cnameCtrl = TextEditingController();
    final contactCtrl = TextEditingController();
    final phoneCtrl = TextEditingController();
    final addrCtrl = TextEditingController();
    final licCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Nuevo Contratista', style: TextStyle(fontWeight: FontWeight.w900)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: cnameCtrl, decoration: const InputDecoration(labelText: 'Nombre empresa / contratista *')),
              const SizedBox(height: 10),
              TextField(controller: contactCtrl, decoration: const InputDecoration(labelText: 'Contacto principal')),
              const SizedBox(height: 10),
              TextField(controller: phoneCtrl, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Teléfono')),
              const SizedBox(height: 10),
              TextField(controller: addrCtrl, decoration: const InputDecoration(labelText: 'Dirección WA')),
              const SizedBox(height: 10),
              TextField(controller: licCtrl, decoration: const InputDecoration(labelText: 'Licencia WA / UBI')),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Crear Perfil')),
        ],
      ),
    );
    if (ok != true || cnameCtrl.text.trim().isEmpty) return;
    try {
      final res = await widget.api.registerQuickProfile(
        contractorName: cnameCtrl.text.trim(),
        contact: contactCtrl.text.trim(),
        phone: phoneCtrl.text.trim(),
        address: addrCtrl.text.trim(),
        license: licCtrl.text.trim(),
      );
      final created = Map<String, dynamic>.from(res['profile'] as Map);
      final slug = (created['name'] ?? '').toString();
      await widget.store.saveCachedProfileDetail(slug, created);
      await _refresh();
      await _selectActiveProfile(slug);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Contratista "${cnameCtrl.text.trim()}" creado y aislado en su perfil.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo crear el contratista: $e')));
      }
    }
  }

  void _onNavSelected(int idx) {
    if (idx == 1) {
      _openNewEstimate();
      return;
    }
    setState(() => _tabIndex = idx);
  }

  int _computedCalibrationPercent() {
    if (_calibration != null) return _calibration!.percent;
    final active = _profiles.where((p) => p.name == _activeProfile).toList();
    if (active.isNotEmpty && active.first.calibrationPct != null) {
      return active.first.calibrationPct!;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _tabIndex == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && _tabIndex != 0) {
          setState(() => _tabIndex = 0);
        }
      },
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isWide = constraints.maxWidth >= 720;
          final body = Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 920),
              child: _tabIndex == 0
                  ? _buildHomeTab()
                  : _tabIndex == 2
                      ? _buildContractorsTab()
                      : MiEmpresaPreciosScreen(
                          api: widget.api,
                          store: widget.store,
                          initialProfileName: _activeProfile,
                          initialFocusModule: _calFocusModule,
                          embedded: true,
                          onSaved: _refresh,
                        ),
            ),
          );

          return Scaffold(
            appBar: AppBar(
              title: const AlkanLogo(badgeSize: 34, showDescriptor: true),
              actions: [
                IconButton(
                  tooltip: _isOnline ? 'En línea' : 'Sin conexión (Offline)',
                  icon: Icon(
                    _isOnline ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
                    color: _isOnline ? AlkanColors.azulLuminoso : AlkanColors.analyzing,
                  ),
                  onPressed: _refresh,
                ),
                IconButton(
                  tooltip: 'Cerrar sesión',
                  icon: const Icon(Icons.logout),
                  onPressed: widget.onLogout,
                ),
              ],
            ),
            body: isWide
                ? Row(
                    children: [
                      NavigationRail(
                        selectedIndex: _tabIndex,
                        onDestinationSelected: _onNavSelected,
                        labelType: NavigationRailLabelType.all,
                        backgroundColor: AlkanColors.surface,
                        selectedIconTheme: const IconThemeData(color: AlkanColors.primary),
                        destinations: const [
                          NavigationRailDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: Text('Inicio')),
                          NavigationRailDestination(icon: Icon(Icons.mic_none), selectedIcon: Icon(Icons.mic), label: Text('Dictar')),
                          NavigationRailDestination(icon: Icon(Icons.groups_outlined), selectedIcon: Icon(Icons.groups), label: Text('Contratistas')),
                          NavigationRailDestination(icon: Icon(Icons.tune_outlined), selectedIcon: Icon(Icons.tune), label: Text('Calibración')),
                        ],
                      ),
                      const VerticalDivider(width: 1),
                      Expanded(child: body),
                    ],
                  )
                : body,
            bottomNavigationBar: isWide
                ? null
                : NavigationBar(
                    selectedIndex: _tabIndex,
                    onDestinationSelected: _onNavSelected,
                    destinations: const [
                      NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Inicio'),
                      NavigationDestination(icon: Icon(Icons.mic, color: AlkanColors.primary), label: 'Dictar'),
                      NavigationDestination(icon: Icon(Icons.groups_outlined), selectedIcon: Icon(Icons.groups), label: 'Contratistas'),
                      NavigationDestination(icon: Icon(Icons.tune_outlined), selectedIcon: Icon(Icons.tune), label: 'Calibración'),
                    ],
                  ),
          );
        },
      ),
    );
  }

  Widget _buildHomeTab() {
    final actor = widget.api.session?.actor ?? '';
    final role = widget.api.session?.role ?? '';
    final activeProf = _profiles.firstWhere((p) => p.name == _activeProfile, orElse: () => defaultAlkanProfiles.first);
    final calPct = _computedCalibrationPercent();
    final filtered = _runs.where((r) => _filter == 'all' || r.badgeStatus == _filter).toList();

    final countAnalyzing = _runs.where((r) => r.badgeStatus == 'analyzing').length;
    final countDraft = _runs.where((r) => r.badgeStatus == 'draft_ready').length;
    final countApproved = _runs.where((r) => r.badgeStatus == 'approved').length;

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Encabezado ALKAN Blue con selector de perfil activo
          AlkanHeader(
            greeting: 'Hola, ${actor.isEmpty ? "Estimador" : actor}',
            subtitle: '$role · ${_isOnline ? "Conectado a Railway" : "Modo Obra Offline"}',
            trailing: IconButton(
              tooltip: 'Calibración',
              icon: const Icon(Icons.settings_outlined, color: Colors.white),
              onPressed: () => setState(() {
                _calFocusModule = 'ALL';
                _tabIndex = 3;
              }),
            ),
            bottom: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AlkanColors.azulLuminoso.withOpacity(0.35)),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _profiles.any((p) => p.name == _activeProfile) ? _activeProfile : null,
                  dropdownColor: AlkanColors.azulProfundo,
                  isExpanded: true,
                  iconEnabledColor: AlkanColors.azulLuminoso,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 14),
                  items: _profiles
                      .map((p) => DropdownMenuItem(value: p.name, child: Text(p.contractor, overflow: TextOverflow.ellipsis)))
                      .toList(),
                  onChanged: (v) {
                    if (v != null) _selectActiveProfile(v);
                  },
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),

          // Indicador de Calibración REAL (nunca fijo)
          Card(
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: () => setState(() {
                _calFocusModule = _calibration?.nextPendingModule ?? 'ALL';
                _tabIndex = 3;
              }),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    AlkanProgressIndicator(
                      percent: calPct,
                      label: 'Calibración de ${activeProf.contractor}',
                      helper: _calibration?.nextPendingModule != null
                          ? 'Pendiente: Módulo ${_calibration!.nextPendingModule} · Toca para completar →'
                          : 'Perfil calibrado al $calPct%. Solo dicta en campo.',
                    ),
                    if (_calibration != null && _calibration!.modules.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: _calibration!.modules.map((m) {
                          return Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: m.complete ? AlkanColors.approved.withOpacity(0.1) : AlkanColors.azulSuave,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: Text(
                              '${m.complete ? "✓" : "○"} ${m.id} ${m.key}',
                              style: TextStyle(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w700,
                                color: m.complete ? AlkanColors.approved : AlkanColors.azulInstitucional,
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),

          // Acción Dominante: DICTAR ESTIMADO
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: AlkanColors.azulPrincipal,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Describe el trabajo. ALKAN prepara tus 3 documentos.',
                  style: TextStyle(color: Color(0xFFDCEEFF), fontSize: 13.5, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 12),
                ElevatedButton.icon(
                  onPressed: () => _openNewEstimate(),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: AlkanColors.azulProfundo,
                    minimumSize: const Size(double.infinity, 56),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  ),
                  icon: const Icon(Icons.mic, size: 26),
                  label: const Text('DICTAR ESTIMADO', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          if (_pendingOffline.isNotEmpty) ...[
            Card(
              child: ListTile(
                leading: const Icon(Icons.cloud_upload_outlined, color: AlkanColors.analyzing),
                title: Text('${_pendingOffline.length} estimado(s) en cola offline', style: const TextStyle(fontWeight: FontWeight.w800)),
                subtitle: const Text('Listos para enviar al recuperar red'),
                trailing: TextButton(
                  onPressed: _syncing ? null : _syncPendingDrafts,
                  child: Text(_syncing ? 'Subiendo...' : 'Sincronizar'),
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Pipeline tipo CRM
          Row(
            children: [
              const Expanded(child: Text('Pipeline de Estimaciones', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900))),
              Text('${_runs.length} total', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AlkanColors.textSecondary)),
            ],
          ),
          const SizedBox(height: 10),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                _filterChip('Todos (${_runs.length})', 'all'),
                const SizedBox(width: 8),
                _filterChip('Dictado ($countAnalyzing)', 'analyzing'),
                const SizedBox(width: 8),
                _filterChip('Borrador ($countDraft)', 'draft_ready'),
                const SizedBox(width: 8),
                _filterChip('Revisado ($countApproved)', 'approved'),
                const SizedBox(width: 8),
                _filterChip('NO-GO', 'no_go'),
              ],
            ),
          ),
          const SizedBox(height: 12),

          if (_loading && _runs.isEmpty)
            const Padding(
              padding: EdgeInsets.all(36),
              child: Center(child: AlkanLoadingAnimation(size: 80, label: 'Sincronizando pipeline...')),
            )
          else if (filtered.isEmpty)
            AlkanEmptyState(
              icon: Icons.mic_none,
              title: 'Tu próximo estimado empieza aquí.',
              subtitle: 'Toca "Dictar Estimado", describe la obra por voz o adjunta tus planos para generar los 3 PDFs.',
              actionLabel: 'Dictar Estimado',
              onAction: () => _openNewEstimate(),
            )
          else
            for (final r in filtered)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Dismissible(
                  key: Key(r.id),
                  direction: DismissDirection.horizontal,
                  background: Container(
                    alignment: Alignment.centerLeft,
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    decoration: BoxDecoration(
                      color: Colors.blue.shade700,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: const Row(
                      children: [
                        Icon(Icons.edit_note_rounded, color: Colors.white, size: 28),
                        SizedBox(width: 8),
                        Text('Editar / Continuar', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14)),
                      ],
                    ),
                  ),
                  secondaryBackground: Container(
                    alignment: Alignment.centerRight,
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    decoration: BoxDecoration(
                      color: AlkanColors.noGo,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: const Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Text('Eliminar', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14)),
                        SizedBox(width: 8),
                        Icon(Icons.delete_outline_rounded, color: Colors.white, size: 28),
                      ],
                    ),
                  ),
                  confirmDismiss: (direction) async {
                    if (direction == DismissDirection.endToStart) {
                      return await _confirmDeleteRun(r);
                    } else {
                      await _resumeOrEditRun(r);
                      return false;
                    }
                  },
                  child: AlkanProjectCard(
                    run: r,
                    onTap: () => _openRun(r.id),
                    onOptions: () => _showRunOptionsSheet(r),
                  ),
                ),
              ),
          const SizedBox(height: 20),
        ],
      ),
    );
  }

  Widget _buildContractorsTab() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Contratistas', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
                  Text('Cada perfil mantiene su logo, tarifas, exclusiones y folios aislados.',
                      style: TextStyle(fontSize: 13, color: AlkanColors.textSecondary)),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        AlkanPrimaryButton(
          label: 'Agregar Contratista Nuevo',
          icon: Icons.add_business_outlined,
          onPressed: _registerContractorIsolated,
        ),
        const SizedBox(height: 14),
        for (final p in _profiles)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AlkanContractorCard(
              profile: p,
              selected: p.name == _activeProfile,
              calibrationPercent: p.calibrationPct,
              logoUrl: (_isOnline && widget.api.session != null) ? widget.api.profileLogoUrl(p.name) : null,
              authHeaders: widget.api.session != null ? widget.api.authHeaders() : null,
              onTap: () => _selectActiveProfile(p.name),
              onEdit: () {
                _selectActiveProfile(p.name);
                setState(() {
                  _calFocusModule = p.nextPendingModule ?? 'ALL';
                  _tabIndex = 3;
                });
              },
            ),
          ),
      ],
    );
  }

  Widget _filterChip(String label, String key) {
    final selected = _filter == key;
    return ChoiceChip(
      label: Text(
        label,
        style: TextStyle(
          fontWeight: FontWeight.w800,
          fontSize: 13,
          color: selected ? Colors.white : AlkanColors.textPrimary,
        ),
      ),
      selected: selected,
      selectedColor: AlkanColors.primary,
      onSelected: (_) => setState(() => _filter = key),
    );
  }
}
