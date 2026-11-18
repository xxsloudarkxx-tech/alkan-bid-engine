import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../services/voice_dictation_service.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_components.dart';
import '../widgets/alkan_flow.dart';
import '../widgets/alkan_loading_logo.dart';
import 'paquete_aprobacion_screen.dart';
import 'progreso_vivo_screen.dart';

/// Dictar Estimado (Captura-Primero) + Confirmación por Excepción ("¿Esto es lo que entendí?").
class EstimateFlowScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final List<String> initialFiles;
  final String? initialProfile;

  const EstimateFlowScreen({
    super.key,
    required this.api,
    required this.store,
    this.initialFiles = const [],
    this.initialProfile,
  });

  @override
  State<EstimateFlowScreen> createState() => _EstimateFlowScreenState();
}

class _EstimateFlowScreenState extends State<EstimateFlowScreen> {
  static const _counties = [
    'King',
    'Snohomish',
    'Pierce',
    'Kitsap',
    'Thurston',
    'Spokane',
    'Clark',
    'Whatcom',
    'Skagit',
  ];
  static const _verifiedWageCounties = {'King', 'Snohomish'};

  static const _specialties = [
    {'id': 'metal', 'label': 'Metal / Acero', 'sub': 'Acero, baranda, cerca', 'icon': Icons.construction},
    {'id': 'techado', 'label': 'Techado', 'sub': 'Roofing, TPO, shingle', 'icon': Icons.roofing},
    {'id': 'tablaroca', 'label': 'Tablaroca', 'sub': 'Drywall, framing, cinta', 'icon': Icons.grid_view},
    {'id': 'pintura', 'label': 'Pintura', 'sub': 'Interior / recubrimiento', 'icon': Icons.format_paint},
    {'id': 'molduras', 'label': 'Molduras', 'sub': 'Carpintería y puertas', 'icon': Icons.carpenter},
    {'id': 'cubiertas', 'label': 'Cubiertas', 'sub': 'Granito y cuarzo', 'icon': Icons.countertops},
  ];

  final _titleCtrl = TextEditingController();
  final _clientNameCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  final _contCtrl = TextEditingController(text: '5');
  final _ohCtrl = TextEditingController(text: '10');
  final _profCtrl = TextEditingController(text: '10');
  final _daysCtrl = TextEditingController(text: '30');

  final _voice = VoiceDictationService();
  final _imagePicker = ImagePicker();

  int _view = 1; // 1 = Dictar & Adjuntar, 2 = ¿Esto es lo que entendí?
  bool _isOnline = true;
  bool _hasAnthropicKey = false;
  bool _useAiAgent = false;
  String _voiceState = 'idle'; // idle | recording | processing | done | error
  String? _voiceError;
  bool _loadingPreview = false;
  bool _generating = false;
  bool _savingClient = false;
  bool _expandAdjustments = false;
  double _uploadProgress = 0;
  String _genStatus = 'Preparando paquete ALKAN...';

  String _selectedCounty = 'King';
  late String _selectedProfile = widget.initialProfile ?? 'ss_custom_iron_works';
  List<String> _selectedSpecialties = ['metal'];
  final List<File> _files = [];

  List<ContractorProfileItem> _profiles = List.of(defaultAlkanProfiles);
  List<String> _exclusionsPreview = [];
  List<EditableMaterialLine> _materials = [];
  List<EditableLaborLine> _labor = [];
  String? _countyWageWarning;
  String? _detectedCountyHint;
  List<String> _detectedSpecsHint = [];

  @override
  void initState() {
    super.initState();
    for (final p in widget.initialFiles) {
      final f = File(p);
      if (f.existsSync()) _files.add(f);
    }
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    await _restoreLocalDraft();
    if (widget.initialProfile != null && widget.initialProfile!.isNotEmpty) {
      _selectedProfile = widget.initialProfile!;
    }
    await _loadProfilesAndHealth();
  }

  List<ContractorProfileItem> _mergeProfiles(List<ContractorProfileItem> incoming) {
    final map = <String, ContractorProfileItem>{
      for (final p in defaultAlkanProfiles) p.name: p,
    };
    for (final p in incoming) {
      map[p.name] = p;
    }
    return map.values.toList();
  }

  Future<void> _restoreLocalDraft() async {
    final saved = await widget.store.loadWizardDraft();
    if (saved == null || !mounted) return;
    setState(() {
      _titleCtrl.text = (saved['projectTitle'] ?? '').toString();
      _clientNameCtrl.text = (saved['clientName'] ?? '').toString();
      _selectedCounty = (saved['county'] ?? 'King').toString();
      if (widget.initialProfile == null) {
        _selectedProfile = (saved['profile'] ?? _selectedProfile).toString();
      }
      final specs = (saved['specialties'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList();
      if (specs.isNotEmpty) _selectedSpecialties = specs;
      _notesCtrl.text = (saved['voiceNotes'] ?? '').toString();
      _contCtrl.text = (saved['contingencyPct'] ?? '5').toString();
      _ohCtrl.text = (saved['overheadPct'] ?? '10').toString();
      _profCtrl.text = (saved['profitPct'] ?? '10').toString();
      _daysCtrl.text = (saved['validityDays'] ?? '30').toString();
      for (final p in (saved['filePaths'] as List<dynamic>? ?? const [])) {
        final f = File(p.toString());
        if (f.existsSync() && !_files.any((x) => x.path == f.path)) {
          _files.add(f);
        }
      }
    });
  }

  Future<void> _persistLocalDraft() async {
    await widget.store.saveWizardDraft({
      'projectTitle': _titleCtrl.text,
      'clientName': _clientNameCtrl.text,
      'county': _selectedCounty,
      'profile': _selectedProfile,
      'specialties': _selectedSpecialties,
      'voiceNotes': _notesCtrl.text,
      'filePaths': _files.map((f) => f.path).toList(),
      'contingencyPct': _contCtrl.text,
      'overheadPct': _ohCtrl.text,
      'profitPct': _profCtrl.text,
      'validityDays': _daysCtrl.text,
    });
  }

  Future<void> _loadProfilesAndHealth() async {
    final cached = await widget.store.loadCachedProfiles();
    if (cached.isNotEmpty && mounted) {
      setState(() => _profiles = _mergeProfiles(cached));
    }
    try {
      final results = await Future.wait<dynamic>([
        widget.api.fetchProfiles(),
        widget.api.fetchHealth(widget.api.session!.baseUrl),
      ]);
      final profiles = results[0] as List<ContractorProfileItem>;
      final health = results[1] as Map<String, dynamic>;
      final merged = _mergeProfiles([...cached, ...profiles]);
      await widget.store.saveCachedProfiles(merged);
      if (!mounted) return;
      setState(() {
        _isOnline = true;
        _profiles = merged;
        _hasAnthropicKey = health['has_anthropic_key'] == true;
        if (!_hasAnthropicKey) {
          _useAiAgent = false;
        } else if (_files.any((f) => f.path.toLowerCase().endsWith('.pdf') || f.path.toLowerCase().endsWith('.zip'))) {
          _useAiAgent = true;
        }
        if (merged.isNotEmpty && !merged.any((p) => p.name == _selectedProfile)) {
          _selectedProfile = merged.first.name;
        }
      });
      await _applyProfilePreconfig(_selectedProfile);
    } catch (_) {
      if (mounted) setState(() => _isOnline = false);
      await _applyProfilePreconfig(_selectedProfile);
    }
  }

  Future<void> _applyProfilePreconfig(String profileName) async {
    _selectedProfile = profileName;
    Map<String, dynamic>? detail;
    try {
      detail = await widget.api.fetchProfileDetail(profileName);
      await widget.store.saveCachedProfileDetail(profileName, detail);
    } catch (_) {
      detail = await widget.store.loadCachedProfileDetail(profileName);
    }
    if (detail == null || !mounted) return;
    final prof = Map<String, dynamic>.from(detail['profile'] as Map? ?? const {});
    final mk = Map<String, dynamic>.from(prof['markups'] as Map? ?? const {});
    final excl = (prof['exclusiones_base'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList();
    setState(() {
      _exclusionsPreview = excl;
      if (mk['contingency_pct'] != null) _contCtrl.text = mk['contingency_pct'].toString();
      if (mk['overhead_pct'] != null) _ohCtrl.text = mk['overhead_pct'].toString();
      if (mk['profit_pct'] != null) _profCtrl.text = mk['profit_pct'].toString();
      if (prof['validity_days'] != null) _daysCtrl.text = prof['validity_days'].toString();
    });
    await _persistLocalDraft();
  }

  String _projectKey() {
    final raw = _titleCtrl.text.trim().toUpperCase().replaceAll(RegExp(r'[^A-Z0-9_-]+'), '_');
    final cleaned = raw.replaceAll(RegExp(r'^_+|_+$'), '');
    if (cleaned.length >= 2) return cleaned.substring(0, cleaned.length.clamp(2, 24));
    return 'OBRA_${DateTime.now().millisecondsSinceEpoch % 10000}';
  }

  Future<void> _toggleVoiceDictation() async {
    if (_voiceState == 'recording') {
      setState(() => _voiceState = 'processing');
      await _voice.stopListening();
      if (mounted) {
        setState(() => _voiceState = _notesCtrl.text.trim().isNotEmpty ? 'done' : 'idle');
      }
      return;
    }
    setState(() {
      _voiceState = 'recording';
      _voiceError = null;
    });
    final ok = await _voice.startListening(
      onText: (text, isFinal) {
        if (!mounted) return;
        setState(() {
          _notesCtrl.text = text;
          if (isFinal) _voiceState = 'done';
        });
        _persistLocalDraft();
      },
    );
    if (!ok && mounted) {
      setState(() {
        _voiceState = 'error';
        _voiceError = 'Micrófono o reconocimiento de voz no disponible aquí. Escribe el alcance directamente abajo.';
      });
    }
  }

  Future<void> _pickPdfOrZip() async {
    try {
      final result = await FilePicker.platform.pickFiles(allowMultiple: true, type: FileType.any);
      if (result == null) return;
      const validExts = {'pdf', 'zip', 'jpg', 'jpeg', 'png', 'webp'};
      int addedCount = 0;
      int totalBytes = 0;
      bool hasPlanDoc = false;
      final rejected = <String>[];

      for (final f in result.files) {
        final path = f.path;
        if (path == null) continue;
        final lower = path.toLowerCase();
        final ext = lower.contains('.') ? lower.split('.').last : '';
        if (!validExts.contains(ext)) {
          rejected.add(f.name);
          continue;
        }
        final fileObj = File(path);
        if (!await fileObj.exists()) continue;
        totalBytes += await fileObj.length();
        if (!_files.any((x) => x.path == fileObj.path)) {
          _files.add(fileObj);
          addedCount++;
        }
        if (ext == 'pdf' || ext == 'zip') hasPlanDoc = true;
      }

      if (!mounted) return;
      setState(() {
        if (hasPlanDoc && _hasAnthropicKey) {
          _useAiAgent = true;
        }
      });
      await _persistLocalDraft();
      if (!mounted) return;
      if (addedCount > 0) {
        final kb = (totalBytes / 1024).toStringAsFixed(0);
        final aiNote = (hasPlanDoc && _hasAnthropicKey) ? ' · Lectura con Claude Sonnet 5 activada' : '';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ $addedCount archivo(s) adjuntado(s) ($kb KB)$aiNote')),
        );
      } else if (rejected.isNotEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Formato no compatible (${rejected.join(", ")}). Usa PDF, ZIP o imagen JPG/PNG.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('No se pudo abrir el selector de archivos: $e')),
        );
      }
    }
  }

  Future<void> _pickWhatsAppOrAny() async {
    try {
      final shared = await widget.api.consumeSharedFiles();
      if (shared.isNotEmpty) {
        setState(() {
          for (final p in shared) {
            final f = File(p);
            if (!_files.any((x) => x.path == f.path)) _files.add(f);
          }
          if (_hasAnthropicKey) _useAiAgent = true;
        });
        await _persistLocalDraft();
        return;
      }
      await _pickPdfOrZip();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al importar: $e')));
      }
    }
  }

  Future<void> _takePhoto() async {
    try {
      final photo = await _imagePicker.pickImage(source: ImageSource.camera, imageQuality: 85);
      if (photo == null) return;
      setState(() => _files.add(File(photo.path)));
      await _persistLocalDraft();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo abrir cámara: $e')));
      }
    }
  }

  Future<void> _openContractorPicker() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AlkanColors.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.72,
        maxChildSize: 0.92,
        minChildSize: 0.45,
        expand: false,
        builder: (ctx, scrollCtrl) => Column(
          children: [
            const SizedBox(height: 10),
            Container(width: 44, height: 4, decoration: BoxDecoration(color: AlkanColors.border, borderRadius: BorderRadius.circular(4))),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 8),
              child: Row(
                children: [
                  const Expanded(
                    child: Text('Seleccionar Contratista', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                  ),
                  TextButton.icon(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _registerNewClientDialog();
                    },
                    icon: const Icon(Icons.add_business),
                    label: const Text('+ Nuevo'),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView(
                controller: scrollCtrl,
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
                children: [
                  for (final p in _profiles)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: AlkanContractorCard(
                        profile: p,
                        selected: p.name == _selectedProfile,
                        calibrationPercent: p.calibrationPct,
                        logoUrl: (_isOnline && widget.api.session != null) ? widget.api.profileLogoUrl(p.name) : null,
                        authHeaders: widget.api.session != null ? widget.api.authHeaders() : null,
                        onTap: () {
                          Navigator.pop(ctx);
                          _applyProfilePreconfig(p.name);
                        },
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _registerNewClientDialog() async {
    final nameCtrl = TextEditingController();
    final contactCtrl = TextEditingController();
    final phoneCtrl = TextEditingController();
    final addrCtrl = TextEditingController();
    final licCtrl = TextEditingController();

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Registrar Cliente / Contratista', style: TextStyle(fontWeight: FontWeight.w900)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: 'Nombre del cliente / empresa *')),
              const SizedBox(height: 10),
              TextField(controller: contactCtrl, decoration: const InputDecoration(labelText: 'Persona de contacto')),
              const SizedBox(height: 10),
              TextField(controller: phoneCtrl, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Teléfono')),
              const SizedBox(height: 10),
              TextField(controller: addrCtrl, decoration: const InputDecoration(labelText: 'Dirección o ciudad WA')),
              const SizedBox(height: 10),
              TextField(controller: licCtrl, decoration: const InputDecoration(labelText: 'Licencia WA / UBI (opcional)')),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('REGISTRAR')),
        ],
      ),
    );
    if (ok != true || nameCtrl.text.trim().isEmpty) return;

    final enteredName = nameCtrl.text.trim();
    setState(() => _savingClient = true);
    try {
      final res = await widget.api.registerQuickProfile(
        contractorName: enteredName,
        contact: contactCtrl.text.trim(),
        phone: phoneCtrl.text.trim(),
        address: addrCtrl.text.trim(),
        license: licCtrl.text.trim(),
        specialty: _selectedSpecialties.join(', '),
      );
      final created = Map<String, dynamic>.from(res['profile'] as Map);
      final slug = (created['name'] ?? '').toString();
      final remoteList = (res['profiles'] as List<dynamic>? ?? const [])
          .map((e) => ContractorProfileItem.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
      final merged = _mergeProfiles([..._profiles, ...remoteList]);
      await widget.store.saveCachedProfiles(merged);
      await widget.store.saveCachedProfileDetail(slug, created);
      if (!mounted) return;
      setState(() {
        _profiles = merged;
        _clientNameCtrl.text = enteredName;
      });
      await _applyProfilePreconfig(slug);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Contratista "$enteredName" registrado y seleccionado.')),
        );
      }
    } catch (_) {
      if (mounted) {
        setState(() => _clientNameCtrl.text = enteredName);
        await _persistLocalDraft();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Cliente "$enteredName" guardado como destinatario (modo offline).')),
        );
      }
    } finally {
      if (mounted) setState(() => _savingClient = false);
    }
  }

  Future<void> _openCountyAndSpecSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AlkanColors.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) => Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 24),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('Especialidades y Condado WA', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                const SizedBox(height: 12),
                const Text('Especialidad (puedes elegir más de una)', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _specialties.map((s) {
                    final id = s['id'] as String;
                    final sel = _selectedSpecialties.contains(id);
                    return FilterChip(
                      label: Text(s['label'] as String),
                      selected: sel,
                      selectedColor: AlkanColors.primary,
                      checkmarkColor: Colors.white,
                      labelStyle: TextStyle(color: sel ? Colors.white : AlkanColors.textPrimary, fontWeight: FontWeight.w700),
                      onSelected: (val) {
                        setSheetState(() {
                          if (val) {
                            _selectedSpecialties.add(id);
                          } else if (_selectedSpecialties.length > 1) {
                            _selectedSpecialties.remove(id);
                          }
                        });
                        setState(() {});
                        _persistLocalDraft();
                      },
                    );
                  }).toList(),
                ),
                const SizedBox(height: 16),
                const Text('Condado de la obra (Salarios L&I)', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _counties.map((c) {
                    final sel = _selectedCounty == c;
                    final verif = _verifiedWageCounties.contains(c);
                    return ChoiceChip(
                      label: Text(verif ? '$c ✓' : c),
                      selected: sel,
                      selectedColor: AlkanColors.primary,
                      labelStyle: TextStyle(color: sel ? Colors.white : AlkanColors.textPrimary, fontWeight: FontWeight.w700),
                      onSelected: (_) {
                        setSheetState(() => _selectedCounty = c);
                        setState(() {});
                        _persistLocalDraft();
                      },
                    );
                  }).toList(),
                ),
                if (!_verifiedWageCounties.contains(_selectedCounty)) ...[
                  const SizedBox(height: 10),
                  Text(
                    '⚠️ Solo King y Snohomish tienen tasas L&I verificadas en wages.json; $_selectedCounty usará referencia preliminar.',
                    style: const TextStyle(fontSize: 12.5, color: AlkanColors.analyzing, fontWeight: FontWeight.w700),
                  ),
                ],
                const SizedBox(height: 18),
                AlkanPrimaryButton(
                  label: 'Listo',
                  onPressed: () => Navigator.pop(ctx),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _processAndGoToConfirmation() async {
    if (_notesCtrl.text.trim().isEmpty && _titleCtrl.text.trim().isEmpty && _files.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Dicta el alcance, escribe una descripción o adjunta un plano antes de procesar.')),
      );
      return;
    }
    setState(() => _loadingPreview = true);
    try {
      final preview = await widget.api.previewDraft(
        key: _projectKey(),
        projectTitle: _titleCtrl.text.trim().isEmpty ? 'Obra en $_selectedCounty Co.' : _titleCtrl.text.trim(),
        profile: _selectedProfile,
        specialties: _selectedSpecialties,
        county: _selectedCounty,
        voiceNotes: _notesCtrl.text.trim(),
        clientName: _clientNameCtrl.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _isOnline = true;
        _materials = preview.materials;
        _labor = preview.labor;
        _countyWageWarning = preview.countyWageWarning;
        _detectedCountyHint = preview.detectedCounty;
        _detectedSpecsHint = preview.detectedSpecialties;
        if (preview.exclusions.isNotEmpty) _exclusionsPreview = preview.exclusions;
        _view = 2;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isOnline = false;
        if (_materials.isEmpty) {
          _materials = [
            EditableMaterialLine(
              id: 'M001',
              section: 'Alcance principal',
              item: 'Materiales base (${_selectedSpecialties.join(", ")})',
              qty: '10',
              unit: 'EA',
              unitPrice: '0.00',
              priceBasis: 'BUDGET',
            ),
          ];
        }
        if (_labor.isEmpty) {
          _labor = [
            EditableLaborLine(
              id: 'L001',
              task: 'Mano de obra de instalación en campo',
              rate: 'SHOP',
              hours: '16',
            ),
          ];
        }
        _countyWageWarning = _verifiedWageCounties.contains(_selectedCounty)
            ? null
            : 'Solo King y Snohomish tienen tasas L&I verificadas en wages.json.';
        _view = 2;
      });
    } finally {
      if (mounted) setState(() => _loadingPreview = false);
    }
  }

  Future<void> _editQuantityDialog({
    required String title,
    required String unit,
    required String initialValue,
    required void Function(String newValue) onSave,
  }) async {
    final ctrl = TextEditingController(text: initialValue);
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title, style: const TextStyle(fontSize: 16.5, fontWeight: FontWeight.w900)),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(labelText: 'Cantidad ($unit)'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, ctrl.text.trim()), child: const Text('Guardar')),
        ],
      ),
    );
    if (result != null && result.isNotEmpty) {
      setState(() => onSave(result));
    }
  }

  Future<void> _addMaterialDialog() async {
    final itemCtrl = TextEditingController();
    final qtyCtrl = TextEditingController(text: '1');
    final unitCtrl = TextEditingController(text: 'EA');
    final priceCtrl = TextEditingController(text: '0.00');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Agregar Material', style: TextStyle(fontWeight: FontWeight.w900)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: itemCtrl, decoration: const InputDecoration(labelText: 'Descripción del material *')),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: qtyCtrl,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(labelText: 'Cantidad'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: TextField(controller: unitCtrl, decoration: const InputDecoration(labelText: 'Unidad (EA/LF/SF)'))),
                ],
              ),
              const SizedBox(height: 10),
              TextField(
                controller: priceCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Precio unitario presupuestario (\$)'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Agregar')),
        ],
      ),
    );
    if (ok != true || itemCtrl.text.trim().isEmpty) return;
    final nextId = 'M${(_materials.length + 101).toString().padLeft(3, '0')}';
    setState(() {
      _materials.add(
        EditableMaterialLine(
          id: nextId,
          section: 'A. Field Additions',
          item: itemCtrl.text.trim(),
          qty: qtyCtrl.text.trim().isEmpty ? '1' : qtyCtrl.text.trim(),
          unit: unitCtrl.text.trim().isEmpty ? 'EA' : unitCtrl.text.trim().toUpperCase(),
          unitPrice: priceCtrl.text.trim().isEmpty ? '0.00' : priceCtrl.text.trim(),
          priceBasis: 'BUDGET',
        ),
      );
    });
  }

  Future<void> _addLaborDialog() async {
    final taskCtrl = TextEditingController();
    final hoursCtrl = TextEditingController(text: '8');
    final rateCtrl = TextEditingController(text: 'SHOP');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Agregar Mano de Obra', style: TextStyle(fontWeight: FontWeight.w900)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: taskCtrl, decoration: const InputDecoration(labelText: 'Tarea / actividad *')),
              const SizedBox(height: 10),
              TextField(
                controller: hoursCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Horas'),
              ),
              const SizedBox(height: 10),
              TextField(controller: rateCtrl, decoration: const InputDecoration(labelText: 'Clave de tarifa (SHOP / ADMIN)')),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Agregar')),
        ],
      ),
    );
    if (ok != true || taskCtrl.text.trim().isEmpty) return;
    final nextId = 'L${(_labor.length + 101).toString().padLeft(3, '0')}';
    setState(() {
      _labor.add(
        EditableLaborLine(
          id: nextId,
          task: taskCtrl.text.trim(),
          rate: rateCtrl.text.trim().isEmpty ? 'SHOP' : rateCtrl.text.trim().toUpperCase(),
          hours: hoursCtrl.text.trim().isEmpty ? '8' : hoursCtrl.text.trim(),
        ),
      );
    });
  }

  Future<void> _generateFinalPackage() async {
    final key = _projectKey();
    final title = _titleCtrl.text.trim().isEmpty ? key : _titleCtrl.text.trim();
    final clientName = _clientNameCtrl.text.trim();
    final matOverrides = _materials
        .map((m) => {
              'id': m.id,
              'section': m.section,
              'item': m.item,
              'qty': m.qty,
              'unit': m.unit,
              'unit_price': m.unitPrice,
              'price_basis': m.priceBasis,
            })
        .toList();
    final labOverrides = _labor
        .map((l) => {
              'id': l.id,
              'task': l.task,
              'rate': l.rate,
              'hours': l.hours,
            })
        .toList();
    final markups = {
      'contingency_pct': _contCtrl.text.trim(),
      'overhead_pct': _ohCtrl.text.trim(),
      'profit_pct': _profCtrl.text.trim(),
      'rounding': '50',
    };
    final validityDays = int.tryParse(_daysCtrl.text.trim()) ?? 30;

    setState(() {
      _generating = true;
      _uploadProgress = 0;
      _genStatus = 'Subiendo planos y alcance...';
    });

    try {
      String? uploadId;
      if (_files.isNotEmpty) {
        uploadId = widget.api.newUploadId();
        for (int i = 0; i < _files.length; i++) {
          final file = _files[i];
          setState(() => _genStatus = 'Subiendo ${file.uri.pathSegments.last} (${i + 1}/${_files.length})...');
          await widget.api.uploadChunkedFile(
            uploadId: uploadId,
            file: file,
            onProgress: (frac) {
              if (mounted) setState(() => _uploadProgress = (i + frac) / _files.length);
            },
          );
        }
      }

      if (_useAiAgent && _hasAnthropicKey && uploadId != null) {
        setState(() => _genStatus = 'Arrancando Agente IA (claude-sonnet-5)...');
        final res = await widget.api.startAgentRun(
          key: key,
          profile: _selectedProfile,
          tradeScope: _selectedSpecialties.join(', '),
          uploadId: uploadId,
          notes: _notesCtrl.text.trim(),
        );
        final runId = (res['id'] ?? '').toString();
        await widget.store.clearWizardDraft();
        if (!mounted) return;
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (_) => ProgresoVivoScreen(api: widget.api, store: widget.store, runId: runId),
          ),
        );
      } else {
        setState(() => _genStatus = 'Motor ALKAN generando los 3 PDFs...');
        final summary = await widget.api.startQuickPackage(
          key: key,
          projectTitle: title,
          profile: _selectedProfile,
          specialty: _selectedSpecialties.first,
          specialties: _selectedSpecialties,
          county: _selectedCounty,
          voiceNotes: _notesCtrl.text.trim(),
          uploadId: uploadId,
          clientName: clientName,
          materialsOverrides: matOverrides,
          laborOverrides: labOverrides,
          markups: markups,
          validityDays: validityDays,
        );
        final runId = (summary.run['id'] ?? '').toString();
        await widget.store.clearWizardDraft();
        if (!mounted) return;
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (_) => PaqueteAprobacionScreen(api: widget.api, store: widget.store, runId: runId),
          ),
        );
      }
    } catch (_) {
      await widget.store.addPendingDraft(
        PendingOfflineEstimate(
          localId: 'LOCAL_${DateTime.now().millisecondsSinceEpoch}',
          key: key,
          projectTitle: title,
          profile: _selectedProfile,
          specialty: _selectedSpecialties.first,
          specialties: _selectedSpecialties,
          county: _selectedCounty,
          voiceNotes: _notesCtrl.text.trim(),
          filePaths: _files.map((f) => f.path).toList(),
          useQuickPackage: !(_useAiAgent && _hasAnthropicKey && _files.isNotEmpty),
          materialsOverrides: matOverrides,
          laborOverrides: labOverrides,
          markups: markups,
          validityDays: validityDays,
          createdAt: DateTime.now().toIso8601String(),
        ),
      );
      await widget.store.clearWizardDraft();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Sin conexión: borrador guardado en cola offline para sincronizar luego.')),
      );
      Navigator.pop(context);
    } finally {
      if (mounted) setState(() => _generating = false);
    }
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _clientNameCtrl.dispose();
    _notesCtrl.dispose();
    _contCtrl.dispose();
    _ohCtrl.dispose();
    _profCtrl.dispose();
    _daysCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _view == 1 && !_generating,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && _view == 2 && !_generating) {
          setState(() => _view = 1);
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: Row(
            children: [
              const AlkanLogoBadge(size: 28, withBorder: false),
              const SizedBox(width: 10),
              Text(_view == 1 ? 'Dictar Estimado' : '¿Esto es lo que entendí?'),
            ],
          ),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 14),
              child: Icon(
                _isOnline ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
                color: _isOnline ? AlkanColors.azulLuminoso : AlkanColors.analyzing,
              ),
            ),
          ],
        ),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 820),
            child: _generating
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          AlkanLoadingAnimation(size: 104, label: _genStatus),
                          if (_uploadProgress > 0) ...[
                            const SizedBox(height: 18),
                            LinearProgressIndicator(value: _uploadProgress, minHeight: 8),
                          ],
                        ],
                      ),
                    ),
                  )
                : _loadingPreview
                    ? const Center(
                        child: AlkanLoadingAnimation(size: 92, label: 'Analizando alcance con el motor ALKAN...'),
                      )
                    : Column(
                        children: [
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
                            child: AlkanStepHeader(
                              current: _view,
                              total: 2,
                              title: _view == 1 ? 'Describe el trabajo' : 'Confirma por excepción',
                              why: _view == 1 ? AlkanFlowCopy.alcanceWhy : AlkanFlowCopy.cantidadesWhy,
                              feedsDocument: AlkanFlowCopy.feedsLos3,
                            ),
                          ),
                          const Divider(height: 1),
                          Expanded(
                            child: _view == 1 ? _buildCaptureView() : _buildConfirmationView(),
                          ),
                        ],
                      ),
          ),
        ),
        bottomNavigationBar: (_generating || _loadingPreview)
            ? null
            : Container(
                color: AlkanColors.surface,
                child: AlkanStepNav(
                  onBack: _view == 2 ? () => setState(() => _view = 1) : () => Navigator.pop(context),
                  onNext: _view == 1 ? _processAndGoToConfirmation : _generateFinalPackage,
                  nextLabel: _view == 1 ? 'Procesar y Confirmar →' : 'Generar 3 Documentos (PDF)',
                ),
              ),
      ),
    );
  }

  Widget _buildCaptureView() {
    final activeProf = _profiles.firstWhere(
      (p) => p.name == _selectedProfile,
      orElse: () => defaultAlkanProfiles.first,
    );
    final countyVerified = _verifiedWageCounties.contains(_selectedCounty);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // 1. Ya configurado (con palomita ✓ — no vuelve a pedir formulario completo)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Ya configurado en tu perfil (toca solo si deseas cambiar):',
                  style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: AlkanColors.textSecondary),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ActionChip(
                      backgroundColor: AlkanColors.azulSuave,
                      side: const BorderSide(color: AlkanColors.azulPrincipal),
                      avatar: const Icon(Icons.check_circle, color: AlkanColors.approved, size: 18),
                      label: Text(activeProf.contractor, style: const TextStyle(fontWeight: FontWeight.w800)),
                      onPressed: _openContractorPicker,
                    ),
                    ActionChip(
                      backgroundColor: AlkanColors.azulSuave,
                      side: BorderSide(color: AlkanColors.azulPrincipal.withOpacity(0.5)),
                      avatar: const Icon(Icons.check_circle, color: AlkanColors.approved, size: 18),
                      label: Text('${_selectedSpecialties.join(", ").toUpperCase()} · $_selectedCounty Co.'),
                      onPressed: _openCountyAndSpecSheet,
                    ),
                    ActionChip(
                      backgroundColor: AlkanColors.background,
                      avatar: const Icon(Icons.verified_outlined, color: AlkanColors.primary, size: 18),
                      label: Text('Markups ${_contCtrl.text}/${_ohCtrl.text}/${_profCtrl.text}%'),
                      onPressed: () => setState(() => _view = 2),
                    ),
                  ],
                ),
                if (!countyVerified) ...[
                  const SizedBox(height: 10),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AlkanColors.analyzing.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: AlkanColors.analyzing.withOpacity(0.6)),
                    ),
                    child: Text(
                      '⚠️ Solo King y Snohomish tienen tasas L&I verificadas en wages.json. $_selectedCounty County usará tasa referencial.',
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AlkanColors.textPrimary),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),

        // 2. Consola de Dictado + Texto
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text('1. Describe o dicta el trabajo', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: (_voiceState == 'recording' ? AlkanColors.noGo : AlkanColors.azulSuave).withOpacity(_voiceState == 'recording' ? 0.14 : 1),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        _voiceState == 'recording'
                            ? 'Grabando...'
                            : _voiceState == 'processing'
                                ? 'Procesando...'
                                : _voiceState == 'done'
                                    ? 'Dictado listo ✓'
                                    : _voiceState == 'error'
                                        ? 'Error micrófono'
                                        : 'En español (es_MX)',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w800,
                          color: _voiceState == 'recording' || _voiceState == 'error' ? AlkanColors.noGo : AlkanColors.primary,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                AlkanPrimaryButton(
                  label: _voiceState == 'recording' ? 'Detener dictado' : 'Dictar por voz en español',
                  icon: _voiceState == 'recording' ? Icons.stop_circle : Icons.mic,
                  backgroundColor: _voiceState == 'recording' ? AlkanColors.noGo : AlkanColors.primary,
                  onPressed: _toggleVoiceDictation,
                ),
                if (_voiceError != null) ...[
                  const SizedBox(height: 8),
                  Text(_voiceError!, style: const TextStyle(color: AlkanColors.noGo, fontSize: 12.5, fontWeight: FontWeight.w700)),
                ],
                const SizedBox(height: 12),
                TextField(
                  controller: _notesCtrl,
                  onChanged: (_) => _persistLocalDraft(),
                  maxLines: 4,
                  decoration: const InputDecoration(
                    labelText: 'Alcance dictado o escrito',
                    hintText: 'Ej. Bodega Tacoma en King County: barandal metálico 120 LF, portón vehicular y dos manos de pintura...',
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _titleCtrl,
                  onChanged: (_) => _persistLocalDraft(),
                  decoration: const InputDecoration(
                    labelText: 'Nombre corto de la obra (opcional)',
                    hintText: 'Ej. Escuela Madison o Bodega Redmond',
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),

        // 3. Adjuntos: Planos PDF / ZIP / WhatsApp / Fotos
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('2. Adjunta planos o fotos (opcional)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                AlkanSecondaryButton(
                  label: 'Subir PDF / ZIP de Planos',
                  icon: Icons.picture_as_pdf_outlined,
                  onPressed: _pickPdfOrZip,
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: AlkanSecondaryButton(
                        label: 'WhatsApp / Archivos',
                        icon: Icons.chat_outlined,
                        onPressed: _pickWhatsAppOrAny,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: AlkanSecondaryButton(
                        label: 'Tomar Foto',
                        icon: Icons.camera_alt_outlined,
                        onPressed: _takePhoto,
                      ),
                    ),
                  ],
                ),
                if (_files.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  for (int i = 0; i < _files.length; i++)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.attach_file, color: AlkanColors.primary),
                      title: Text(_files[i].uri.pathSegments.last, overflow: TextOverflow.ellipsis),
                      trailing: IconButton(
                        icon: const Icon(Icons.close, color: AlkanColors.noGo),
                        onPressed: () {
                          setState(() => _files.removeAt(i));
                          _persistLocalDraft();
                        },
                      ),
                    ),
                ],
                const SizedBox(height: 8),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Leer planos con Agente IA (claude-sonnet-5)', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14.5)),
                  subtitle: Text(
                    _hasAnthropicKey
                        ? (_useAiAgent
                            ? 'Activado: analizará PDFs adjuntos (2-6 min).'
                            : 'Desactivado: usará plantilla rápida + tus cantidades.')
                        : 'No disponible sin ANTHROPIC_API_KEY activa en servidor; se usará captura rápida.',
                    style: const TextStyle(fontSize: 12.5, color: AlkanColors.textSecondary),
                  ),
                  value: _hasAnthropicKey && _useAiAgent,
                  onChanged: _hasAnthropicKey ? (v) => setState(() => _useAiAgent = v) : null,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildConfirmationView() {
    final activeProf = _profiles.firstWhere(
      (p) => p.name == _selectedProfile,
      orElse: () => defaultAlkanProfiles.first,
    );
    final budgetLines = _materials.where((m) => m.priceBasis == 'BUDGET').length;
    final quoteLines = _materials.where((m) => m.priceBasis == 'QUOTE').length;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Lo que ya venía calibrado del perfil
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.check_circle, color: AlkanColors.approved, size: 20),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text('Ya configurado desde tu perfil', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 14.5)),
                    ),
                    TextButton(onPressed: _openContractorPicker, child: const Text('Cambiar')),
                  ],
                ),
                Text(
                  '${activeProf.contractor} · ${_exclusionsPreview.length} exclusiones base · Márgenes ${_contCtrl.text}/${_ohCtrl.text}/${_profCtrl.text}%',
                  style: const TextStyle(fontSize: 13, color: AlkanColors.textSecondary, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),

        // Señales detectadas del dictado + edición en línea
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Proyecto detectado (toca para ajustar en línea)', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 15)),
                if (_detectedCountyHint != null || _detectedSpecsHint.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AlkanColors.azulSuave,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.auto_awesome, color: AlkanColors.primary, size: 18),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Detectado en tu texto: ${_detectedSpecsHint.isNotEmpty ? _detectedSpecsHint.join(", ") : _selectedSpecialties.join(", ")}'
                            '${_detectedCountyHint != null ? " · $_detectedCountyHint County" : ""}',
                            style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AlkanColors.azulInstitucional),
                          ),
                        ),
                        if (_detectedCountyHint != null && _detectedCountyHint != _selectedCounty)
                          TextButton(
                            onPressed: () => setState(() => _selectedCounty = _detectedCountyHint!),
                            child: const Text('Aplicar'),
                          ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 10),
                TextField(
                  controller: _titleCtrl,
                  onChanged: (_) => _persistLocalDraft(),
                  decoration: const InputDecoration(labelText: 'Nombre del proyecto / obra'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _clientNameCtrl,
                  onChanged: (_) => _persistLocalDraft(),
                  decoration: const InputDecoration(labelText: 'Cliente / GC destinatario (opcional)'),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ActionChip(
                      label: Text('Condado: $_selectedCounty'),
                      onPressed: _openCountyAndSpecSheet,
                    ),
                    ActionChip(
                      label: Text('Oficios: ${_selectedSpecialties.join(", ")}'),
                      onPressed: _openCountyAndSpecSheet,
                    ),
                    ActionChip(
                      label: Text(_expandAdjustments ? 'Ocultar márgenes' : 'Ajustar márgenes'),
                      onPressed: () => setState(() => _expandAdjustments = !_expandAdjustments),
                    ),
                  ],
                ),
                if (_countyWageWarning != null) ...[
                  const SizedBox(height: 8),
                  Text('⚠️ $_countyWageWarning', style: const TextStyle(color: AlkanColors.analyzing, fontSize: 12.5, fontWeight: FontWeight.w700)),
                ],
                if (_expandAdjustments) ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(child: TextField(controller: _contCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Conting. %'))),
                      const SizedBox(width: 8),
                      Expanded(child: TextField(controller: _ohCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'OH %'))),
                      const SizedBox(width: 8),
                      Expanded(child: TextField(controller: _profCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Utilidad %'))),
                      const SizedBox(width: 8),
                      Expanded(child: TextField(controller: _daysCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Días'))),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),

        // Transparencia BUDGET vs QUOTE
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: (budgetLines > 0 ? AlkanColors.analyzing : AlkanColors.approved).withOpacity(0.12),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: (budgetLines > 0 ? AlkanColors.analyzing : AlkanColors.approved).withOpacity(0.6)),
          ),
          child: Text(
            budgetLines > 0
                ? '⚠️ Transparencia: $quoteLines línea(s) QUOTE confirmadas y $budgetLines línea(s) BUDGET (presupuestarias hasta cotizar).'
                : '✓ Todas las partidas ($quoteLines) cuentan con base QUOTE confirmada.',
            style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: AlkanColors.textPrimary),
          ),
        ),
        const SizedBox(height: 12),

        Row(
          children: [
            const Expanded(child: Text('Materiales', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900))),
            TextButton.icon(onPressed: _addMaterialDialog, icon: const Icon(Icons.add_circle_outline, size: 19), label: const Text('+ Agregar')),
          ],
        ),
        for (final m in _materials)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Card(
              child: ListTile(
                onTap: () => _editQuantityDialog(title: m.item, unit: m.unit, initialValue: m.qty, onSave: (v) => m.qty = v),
                title: Text(m.item, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14)),
                subtitle: Row(
                  children: [
                    Text('${m.id} · ', style: const TextStyle(fontSize: 12)),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: (m.priceBasis == 'QUOTE' ? AlkanColors.approved : AlkanColors.draft).withOpacity(0.14),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        m.priceBasis,
                        style: TextStyle(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w800,
                          color: m.priceBasis == 'QUOTE' ? AlkanColors.approved : AlkanColors.draft,
                        ),
                      ),
                    ),
                  ],
                ),
                trailing: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(color: AlkanColors.azulSuave, borderRadius: BorderRadius.circular(10)),
                  child: Text('${m.qty} ${m.unit} ✏️', style: const TextStyle(fontWeight: FontWeight.w900, color: AlkanColors.primary)),
                ),
              ),
            ),
          ),
        const SizedBox(height: 10),
        Row(
          children: [
            const Expanded(child: Text('Mano de obra (Horas)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900))),
            TextButton.icon(onPressed: _addLaborDialog, icon: const Icon(Icons.add_circle_outline, size: 19), label: const Text('+ Agregar')),
          ],
        ),
        for (final l in _labor)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Card(
              child: ListTile(
                onTap: () => _editQuantityDialog(title: l.task, unit: 'HR', initialValue: l.hours, onSave: (v) => l.hours = v),
                title: Text(l.task, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14)),
                subtitle: Text('${l.id} · Tarifa ${l.rate}'),
                trailing: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(color: AlkanColors.azulSuave, borderRadius: BorderRadius.circular(10)),
                  child: Text('${l.hours} HR ✏️', style: const TextStyle(fontWeight: FontWeight.w900, color: AlkanColors.primary)),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
