import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../services/voice_dictation_service.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_flow.dart';
import '../widgets/alkan_loading_logo.dart';
import '../widgets/step_coach_shell.dart';
import 'paquete_aprobacion_screen.dart';
import 'progreso_vivo_screen.dart';

/// Flujo guiado paso a paso (P1 → P7) hasta generar los 3 PDFs (P8).
class EstimateFlowScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final List<String> initialFiles;

  const EstimateFlowScreen({
    super.key,
    required this.api,
    required this.store,
    this.initialFiles = const [],
  });

  @override
  State<EstimateFlowScreen> createState() => _EstimateFlowScreenState();
}

class _EstimateFlowScreenState extends State<EstimateFlowScreen> {
  static const _counties = [
    'King',
    'Pierce',
    'Snohomish',
    'Kitsap',
    'Thurston',
    'Spokane',
    'Clark',
    'Whatcom',
    'Skagit',
  ];

  static const _specialties = [
    {'id': 'metal', 'label': 'Metal / Acero', 'sub': 'Acero, baranda, cerca', 'icon': Icons.construction, 'profile': 'ss_custom_iron_works'},
    {'id': 'techado', 'label': 'Techado', 'sub': 'Roofing, TPO, shingle', 'icon': Icons.roofing, 'profile': 'pj_roofing'},
    {'id': 'tablaroca', 'label': 'Tablaroca', 'sub': 'Drywall, metal stud, cinta', 'icon': Icons.grid_view, 'profile': 'diaz_finish_carpenter'},
    {'id': 'pintura', 'label': 'Pintura', 'sub': 'Recubrimientos e interior', 'icon': Icons.format_paint, 'profile': 'diaz_finish_carpenter'},
    {'id': 'molduras', 'label': 'Molduras', 'sub': 'Carpintería y casework', 'icon': Icons.carpenter, 'profile': 'diaz_finish_carpenter'},
    {'id': 'cubiertas', 'label': 'Cubiertas', 'sub': 'Cuarzo, granito, piedra', 'icon': Icons.countertops, 'profile': 'jc_granite_design'},
  ];

  static const _stepTitles = [
    '¿Qué vas a cotizar?',
    '¿Para quién es?',
    '¿Qué especialidad?',
    'Alcance por voz y planos',
    'Confirma cantidades',
    'Ajustes finales',
    'Generar estimado',
  ];

  static const _stepWhyLabels = [
    AlkanFlowCopy.proyectoWhy,
    AlkanFlowCopy.clienteWhy,
    AlkanFlowCopy.especialidadWhy,
    AlkanFlowCopy.alcanceWhy,
    AlkanFlowCopy.cantidadesWhy,
    AlkanFlowCopy.ajustesWhy,
    AlkanFlowCopy.generarWhy,
  ];

  static const _stepFeeds = [
    AlkanFlowCopy.feedsCostAnalysis,
    AlkanFlowCopy.feedsLos3,
    AlkanFlowCopy.feedsCostAnalysis,
    AlkanFlowCopy.feedsLos3,
    AlkanFlowCopy.feedsCostAnalysis,
    AlkanFlowCopy.feedsLos3,
    AlkanFlowCopy.feedsLos3,
  ];

  static const _coachTips = [
    'Puedes dictar el nombre de la obra con el micrófono o escribirlo rápido.',
    'Un toque en la tarjeta del cliente carga su logo, tarifas y exclusiones automáticamente.',
    'Si el trabajo mezcla oficios (ej. tablaroca + pintura), puedes marcar más de uno.',
    'Adjunta planos o fotos desde WhatsApp/cámara y activa Agente IA si quieres takeoff automático.',
    'Toca cualquier número para ajustarlo antes de armar los PDFs.',
    'Los defaults de 5% contingencia, 10% OH y 10% utilidad ya vienen listos.',
    'Todo sale como BORRADOR (DRAFT) hasta que un revisor independiente autorice el envío.',
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

  int _step = 1; // 1..7
  bool _isOnline = true;
  bool _hasAnthropicKey = false;
  bool _useAiAgent = false;
  bool _listeningTitle = false;
  bool _listeningScope = false;
  bool _loadingPreview = false;
  bool _generating = false;
  bool _savingClient = false;
  bool _expandAdjustments = false;
  double _uploadProgress = 0;
  String _genStatus = 'Preparando paquete ALKAN...';

  String _selectedCounty = 'King';
  String _selectedProfile = 'ss_custom_iron_works';
  List<String> _selectedSpecialties = ['metal'];
  final List<File> _files = [];

  List<ContractorProfileItem> _profiles = List.of(defaultAlkanProfiles);
  List<String> _exclusionsPreview = [];
  List<EditableMaterialLine> _materials = [];
  List<EditableLaborLine> _labor = [];
  final Map<int, bool> _coachVisible = {};

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
    await _loadCoachFlags();
    await _restoreLocalDraft();
    await _loadProfilesAndHealth();
  }

  Future<void> _loadCoachFlags() async {
    for (int s = 1; s <= 7; s++) {
      final dismissed = await widget.store.isCoachDismissed(s);
      _coachVisible[s] = !dismissed;
    }
    if (mounted) setState(() {});
  }

  Future<void> _dismissCoach(int s) async {
    await widget.store.dismissCoach(s);
    if (mounted) setState(() => _coachVisible[s] = false);
  }

  Future<void> _restoreLocalDraft() async {
    final saved = await widget.store.loadWizardDraft();
    if (saved == null) return;
    if (!mounted) return;
    setState(() {
      _titleCtrl.text = (saved['projectTitle'] ?? '').toString();
      _clientNameCtrl.text = (saved['clientName'] ?? '').toString();
      _selectedCounty = (saved['county'] ?? 'King').toString();
      _selectedProfile = (saved['profile'] ?? _selectedProfile).toString();
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
      final mats = saved['materials'] as List<dynamic>? ?? const [];
      if (mats.isNotEmpty) {
        _materials = mats.map((e) => EditableMaterialLine.fromJson(Map<String, dynamic>.from(e as Map))).toList();
      }
      final labs = saved['labor'] as List<dynamic>? ?? const [];
      if (labs.isNotEmpty) {
        _labor = labs.map((e) => EditableLaborLine.fromJson(Map<String, dynamic>.from(e as Map))).toList();
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
      'materials': _materials.map((m) => m.toJson()).toList(),
      'labor': _labor.map((l) => l.toJson()).toList(),
    });
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
        if (_hasAnthropicKey && _files.any((f) {
          final p = f.path.toLowerCase();
          return p.endsWith('.pdf') || p.endsWith('.zip');
        })) {
          _useAiAgent = true;
        }
        if (merged.isNotEmpty && !merged.any((p) => p.name == _selectedProfile)) {
          _selectedProfile = merged.first.name;
        }
      });
      await _applyClientPreconfig(_selectedProfile, autoSelectSpecialty: false);
    } catch (_) {
      if (mounted) setState(() => _isOnline = false);
      await _applyClientPreconfig(_selectedProfile, autoSelectSpecialty: false);
    }
  }

  /// P2: Al elegir cliente, trae marca, exclusiones, markups y especialidad sugerida.
  Future<void> _applyClientPreconfig(String profileName, {bool autoSelectSpecialty = true}) async {
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
      if (autoSelectSpecialty) {
        final match = _specialties.where((s) => s['profile'] == profileName).toList();
        if (match.isNotEmpty) {
          _selectedSpecialties = [match.first['id'] as String];
        }
      }
    });
    await _persistLocalDraft();
  }

  String _projectKey() {
    final raw = _titleCtrl.text.trim().toUpperCase().replaceAll(RegExp(r'[^A-Z0-9_-]+'), '_');
    final cleaned = raw.replaceAll(RegExp(r'^_+|_+$'), '');
    if (cleaned.length >= 2) return cleaned.substring(0, cleaned.length.clamp(2, 24));
    return 'OBRA_${DateTime.now().millisecondsSinceEpoch % 10000}';
  }

  Future<void> _toggleDictation({required bool forTitle}) async {
    final active = forTitle ? _listeningTitle : _listeningScope;
    if (active) {
      await _voice.stopListening();
      setState(() {
        _listeningTitle = false;
        _listeningScope = false;
      });
      return;
    }
    final ok = await _voice.startListening(
      onText: (text, isFinal) {
        if (!mounted) return;
        setState(() {
          if (forTitle) {
            _titleCtrl.text = text;
          } else {
            _notesCtrl.text = text;
          }
          if (isFinal) {
            _listeningTitle = false;
            _listeningScope = false;
          }
        });
        _persistLocalDraft();
      },
    );
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Dictado por voz no disponible aquí; captura por texto debajo.')),
      );
      return;
    }
    setState(() {
      _listeningTitle = forTitle;
      _listeningScope = !forTitle;
    });
  }

  Future<void> _pickPdfOrZip() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: true,
        type: FileType.any,
      );
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
        final len = await fileObj.length();
        totalBytes += len;
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
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('✅ ${shared.length} archivo(s) recibidos desde WhatsApp/Archivos.')),
          );
        }
        return;
      }
      await _pickPdfOrZip();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al importar archivo: $e')));
      }
    }
  }

  Future<void> _takePhoto() async {
    try {
      final photo = await _imagePicker.pickImage(source: ImageSource.camera, imageQuality: 85);
      if (photo == null) return;
      setState(() => _files.add(File(photo.path)));
      await _persistLocalDraft();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Fotografía adjuntada al alcance.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo tomar foto: $e')));
      }
    }
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
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('REGISTRAR Y USAR')),
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
      await _applyClientPreconfig(slug, autoSelectSpecialty: false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Cliente "$enteredName" guardado y seleccionado.')),
        );
      }
    } catch (_) {
      // Respaldo offline: si no hay señal, guarda el nombre como destinatario con plantilla editable
      if (mounted) {
        setState(() {
          _clientNameCtrl.text = enteredName;
        });
        await _persistLocalDraft();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Cliente "$enteredName" aplicado al borrador (se sincronizará al tener señal).')),
        );
      }
    } finally {
      if (mounted) setState(() => _savingClient = false);
    }
  }

  /// Al avanzar de P4 → P5, prellena cantidades editables desde el servidor (o fallback offline local).
  Future<void> _preparePreviewForStep5() async {
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
        if (preview.exclusions.isNotEmpty) _exclusionsPreview = preview.exclusions;
      });
      await _persistLocalDraft();
    } catch (_) {
      // Modo offline: si aún no hay renglones cargados, prepara tarjetas base editables localmente.
      if (mounted) {
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
                rate: 'FIELD',
                hours: '16',
              ),
            ];
          }
        });
      }
    } finally {
      if (mounted) setState(() => _loadingPreview = false);
    }
  }

  Future<void> _goNext() async {
    await _persistLocalDraft();
    if (_step == 1 && _titleCtrl.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Escribe o dicta el nombre de la obra para continuar.')),
      );
      return;
    }
    if (_step == 3 && _selectedSpecialties.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Selecciona al menos una especialidad.')),
      );
      return;
    }
    if (_step == 4) {
      await _preparePreviewForStep5();
    }
    if (_step < 7) {
      setState(() => _step += 1);
    }
  }

  void _goBack() {
    _persistLocalDraft();
    if (_step > 1) {
      setState(() => _step -= 1);
    } else {
      Navigator.pop(context);
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
        title: Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(labelText: 'Cantidad ($unit)'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
            child: const Text('Guardar'),
          ),
        ],
      ),
    );
    if (result != null && result.isNotEmpty) {
      setState(() => onSave(result));
      await _persistLocalDraft();
    }
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
        setState(() => _genStatus = 'Arrancando Agente IA sobre los planos...');
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
        setState(() => _genStatus = 'Armando Cost Analysis, Material List y Proposal...');
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
      // Offline-first: encola el estimado completo con P1–P6 para sincronizar al recuperar red
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
        const SnackBar(content: Text('Sin conexión: borrador en cola offline. Se generará al reconectar.')),
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
    final idx = _step - 1;
    return StepCoachShell(
      stepNumber: _step,
      totalSteps: AlkanFlowCopy.totalSteps,
      title: _stepTitles[idx],
      whyLabel: _stepWhyLabels[idx],
      feedsDocument: _stepFeeds[idx],
      firstTimeCoachTip: _coachTips[idx],
      showCoachTip: _coachVisible[_step] ?? false,
      onDismissCoachTip: () => _dismissCoach(_step),
      isOnline: _isOnline,
      showBottomBar: !_generating && !_loadingPreview,
      onBack: _goBack,
      onNext: _step < 7 ? _goNext : null,
      nextLabel: _step == 6 ? 'Ir a Generar' : 'Siguiente',
      child: _loadingPreview
          ? const Center(child: AlkanLoadingAnimation(size: 88, label: 'Preparando cantidades del proyecto...'))
          : _buildCurrentStepBody(),
    );
  }

  Widget _buildCurrentStepBody() {
    switch (_step) {
      case 1:
        return _buildP1Project();
      case 2:
        return _buildP2Client();
      case 3:
        return _buildP3Specialty();
      case 4:
        return _buildP4ScopeVoice();
      case 5:
        return _buildP5Quantities();
      case 6:
        return _buildP6Adjustments();
      default:
        return _buildP7Generate();
    }
  }

  Widget _buildP1Project() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: _titleCtrl,
          onChanged: (_) => _persistLocalDraft(),
          decoration: const InputDecoration(
            labelText: 'Nombre del proyecto / obra',
            hintText: 'Ej. Escuela Madison o Bodega Tacoma',
          ),
        ),
        const SizedBox(height: 12),
        ElevatedButton.icon(
          onPressed: () => _toggleDictation(forTitle: true),
          style: ElevatedButton.styleFrom(
            backgroundColor: _listeningTitle ? AlkanColors.noGo : AlkanColors.accent,
            minimumSize: const Size(double.infinity, 56),
          ),
          icon: Icon(_listeningTitle ? Icons.stop : Icons.mic),
          label: Text(_listeningTitle ? 'Escuchando nombre...' : '🎙️ Dictar nombre del proyecto'),
        ),
        const SizedBox(height: 20),
        const Text('Condado de la obra (Washington)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
        const SizedBox(height: 10),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: _counties.map((county) {
            final selected = _selectedCounty == county;
            return ChoiceChip(
              label: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                child: Text(
                  county,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: selected ? Colors.white : AlkanColors.ink,
                  ),
                ),
              ),
              selected: selected,
              selectedColor: AlkanColors.primary,
              onSelected: (_) {
                setState(() => _selectedCounty = county);
                _persistLocalDraft();
              },
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _buildP2Client() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: _clientNameCtrl,
          onChanged: (_) => _persistLocalDraft(),
          decoration: const InputDecoration(
            labelText: 'Cliente / GC a quien va la propuesta (opcional)',
            hintText: 'Ej. Skanska USA, Absher Construction o dueño directo',
          ),
        ),
        const SizedBox(height: 12),
        ElevatedButton.icon(
          onPressed: _savingClient ? null : _registerNewClientDialog,
          style: ElevatedButton.styleFrom(
            backgroundColor: AlkanColors.accent,
            minimumSize: const Size(double.infinity, 54),
          ),
          icon: const Icon(Icons.person_add_alt_1),
          label: Text(_savingClient ? 'Registrando cliente...' : '+ REGISTRAR NUEVO CLIENTE / CONTRATISTA'),
        ),
        const SizedBox(height: 16),
        const Text('O selecciona un contratista / plantilla:', style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: AlkanColors.muted)),
        const SizedBox(height: 10),
        for (final p in _profiles)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InkWell(
              borderRadius: BorderRadius.circular(14),
              onTap: () => _applyClientPreconfig(p.name),
              child: Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: p.name == _selectedProfile ? AlkanColors.primary.withOpacity(0.22) : AlkanColors.surface,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: p.name == _selectedProfile ? AlkanColors.accent : AlkanColors.border,
                    width: p.name == _selectedProfile ? 2.4 : 1.2,
                  ),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 52,
                      height: 52,
                      decoration: BoxDecoration(
                        color: AlkanColors.surfaceAlt,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: p.hasLogo && widget.api.session != null && _isOnline
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(10),
                              child: Image.network(
                                widget.api.profileLogoUrl(p.name),
                                headers: widget.api.authHeaders(),
                                fit: BoxFit.contain,
                                errorBuilder: (_, __, ___) => const Icon(Icons.apartment, color: AlkanColors.accent),
                              ),
                            )
                          : const Icon(Icons.apartment, color: AlkanColors.accent, size: 28),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(p.contractor, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                          if (p.trade.isNotEmpty)
                            Text(
                              p.trade,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 12.5, color: AlkanColors.muted),
                            ),
                        ],
                      ),
                    ),
                    if (p.name == _selectedProfile)
                      const Icon(Icons.check_circle, color: AlkanColors.accent, size: 28),
                  ],
                ),
              ),
            ),
          ),
        if (_exclusionsPreview.isNotEmpty) ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AlkanColors.approved.withOpacity(0.16),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AlkanColors.approved),
            ),
            child: Text(
              '✓ Preconfigurado: ${_exclusionsPreview.length} exclusiones base cargadas automáticamente.',
              style: const TextStyle(fontWeight: FontWeight.w800, color: AlkanColors.ink),
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildP3Specialty() {
    return GridView.count(
      padding: const EdgeInsets.all(16),
      crossAxisCount: 2,
      mainAxisSpacing: 12,
      crossAxisSpacing: 12,
      childAspectRatio: 1.18,
      children: _specialties.map((spec) {
        final id = spec['id'] as String;
        final selected = _selectedSpecialties.contains(id);
        return InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () {
            setState(() {
              if (selected && _selectedSpecialties.length > 1) {
                _selectedSpecialties.remove(id);
              } else if (!selected) {
                _selectedSpecialties.add(id);
              }
            });
            _persistLocalDraft();
          },
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: selected ? AlkanColors.primary : AlkanColors.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: selected ? AlkanColors.accent : AlkanColors.border, width: 2),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(spec['icon'] as IconData, size: 36, color: selected ? Colors.amberAccent : AlkanColors.accent),
                const SizedBox(height: 8),
                Text(
                  spec['label'] as String,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 15.5,
                    fontWeight: FontWeight.w900,
                    color: selected ? Colors.white : AlkanColors.ink,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  spec['sub'] as String,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 11.5,
                    color: selected ? Colors.white70 : AlkanColors.muted,
                  ),
                ),
              ],
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildP4ScopeVoice() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ElevatedButton.icon(
          onPressed: () => _toggleDictation(forTitle: false),
          style: ElevatedButton.styleFrom(
            backgroundColor: _listeningScope ? AlkanColors.noGo : AlkanColors.accent,
            minimumSize: const Size(double.infinity, 72),
          ),
          icon: Icon(_listeningScope ? Icons.stop_circle : Icons.mic, size: 32),
          label: Text(
            _listeningScope ? 'ESCUCHANDO... TOCA PARA PARAR' : '🎙️ DICTAR ALCANCE EN ESPAÑOL',
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w900),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _notesCtrl,
          onChanged: (_) => _persistLocalDraft(),
          maxLines: 4,
          decoration: const InputDecoration(
            labelText: 'Alcance dictado o escrito',
            hintText: 'Ej. Son 26 aulas, muros de tablaroca de piso a losa, dos manos de pintura...',
          ),
        ),
        const SizedBox(height: 16),
        const Text('Adjuntar planos o fotos (opcional)', style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w900)),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: _pickPdfOrZip,
          icon: const Icon(Icons.picture_as_pdf),
          label: const Text('Subir PDF / ZIP de Planos'),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _pickWhatsAppOrAny,
          icon: const Icon(Icons.chat),
          label: const Text('Traer desde WhatsApp / Archivos'),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _takePhoto,
          icon: const Icon(Icons.camera_alt),
          label: const Text('Tomar Foto de Plano o Obra'),
        ),
        if (_files.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (int i = 0; i < _files.length; i++)
            ListTile(
              dense: true,
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
        const SizedBox(height: 10),
        SwitchListTile(
          title: const Text('Leer planos completos con Agente IA', style: TextStyle(fontWeight: FontWeight.w800)),
          subtitle: Text(
            _hasAnthropicKey
                ? 'Activado: la IA analizará los planos adjuntos (2-6 min).'
                : 'Se preparará alcance presupuestario y quedará listo para lectura IA al activar API key.',
          ),
          value: _useAiAgent,
          onChanged: (v) => setState(() => _useAiAgent = v),
        ),
      ],
    );
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
                  Expanded(
                    child: TextField(controller: unitCtrl, decoration: const InputDecoration(labelText: 'Unidad (EA/LF/SF)')),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              TextField(
                controller: priceCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Precio unitario estimado (\$)'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('AGREGAR')),
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
    await _persistLocalDraft();
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
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('AGREGAR')),
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
    await _persistLocalDraft();
  }

  Widget _buildP5Quantities() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AlkanColors.noGo.withOpacity(0.16),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AlkanColors.noGo),
          ),
          child: const Text(
            '⚠️ Precios presupuestarios (BUDGET) hasta confirmar con cotización real de proveedor.',
            style: TextStyle(color: AlkanColors.noGo, fontWeight: FontWeight.w800, fontSize: 13),
          ),
        ),
        const SizedBox(height: 14),
        Row(
          children: [
            const Expanded(child: Text('Materiales', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900))),
            TextButton.icon(
              onPressed: _addMaterialDialog,
              icon: const Icon(Icons.add_circle_outline, size: 20),
              label: const Text('+ Agregar'),
            ),
          ],
        ),
        const SizedBox(height: 8),
        for (final m in _materials)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Card(
              child: ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                onTap: () => _editQuantityDialog(
                  title: m.item,
                  unit: m.unit,
                  initialValue: m.qty,
                  onSave: (val) => m.qty = val,
                ),
                title: Text(m.item, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14.5)),
                subtitle: Text('${m.id} · ${m.priceBasis}'),
                trailing: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: AlkanColors.primary.withOpacity(0.18),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    '${m.qty} ${m.unit} ✏️',
                    style: const TextStyle(fontWeight: FontWeight.w900, color: Color(0xFF7DD3FC)),
                  ),
                ),
              ),
            ),
          ),
        const SizedBox(height: 12),
        Row(
          children: [
            const Expanded(child: Text('Mano de obra (Horas)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900))),
            TextButton.icon(
              onPressed: _addLaborDialog,
              icon: const Icon(Icons.add_circle_outline, size: 20),
              label: const Text('+ Agregar'),
            ),
          ],
        ),
        const SizedBox(height: 8),
        for (final l in _labor)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Card(
              child: ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                onTap: () => _editQuantityDialog(
                  title: l.task,
                  unit: 'HR',
                  initialValue: l.hours,
                  onSave: (val) => l.hours = val,
                ),
                title: Text(l.task, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14.5)),
                subtitle: Text('${l.id} · Tarifa ${l.rate}'),
                trailing: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: AlkanColors.accent.withOpacity(0.18),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    '${l.hours} HR ✏️',
                    style: const TextStyle(fontWeight: FontWeight.w900, color: AlkanColors.ink),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildP6Adjustments() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Configuración Comercial Lista', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
                const SizedBox(height: 8),
                Text(
                  '• Contingencia: ${_contCtrl.text}%\n• Overhead: ${_ohCtrl.text}%\n• Utilidad: ${_profCtrl.text}%\n• Vigencia: ${_daysCtrl.text} días',
                  style: const TextStyle(fontSize: 15, height: 1.5, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () => setState(() => _expandAdjustments = !_expandAdjustments),
                  icon: Icon(_expandAdjustments ? Icons.expand_less : Icons.tune),
                  label: Text(_expandAdjustments ? 'Ocultar ajustes' : 'Cambiar márgenes o vigencia'),
                ),
              ],
            ),
          ),
        ),
        if (_expandAdjustments) ...[
          const SizedBox(height: 14),
          TextField(
            controller: _contCtrl,
            keyboardType: TextInputType.number,
            onChanged: (_) => _persistLocalDraft(),
            decoration: const InputDecoration(labelText: 'Contingencia (%)'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _ohCtrl,
            keyboardType: TextInputType.number,
            onChanged: (_) => _persistLocalDraft(),
            decoration: const InputDecoration(labelText: 'Overhead (%)'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _profCtrl,
            keyboardType: TextInputType.number,
            onChanged: (_) => _persistLocalDraft(),
            decoration: const InputDecoration(labelText: 'Utilidad (%)'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _daysCtrl,
            keyboardType: TextInputType.number,
            onChanged: (_) => _persistLocalDraft(),
            decoration: const InputDecoration(labelText: 'Vigencia de la propuesta (días)'),
          ),
        ],
      ],
    );
  }

  Widget _buildP7Generate() {
    if (_generating) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AlkanLoadingAnimation(size: 108, label: _genStatus),
              if (_uploadProgress > 0) ...[
                const SizedBox(height: 18),
                LinearProgressIndicator(value: _uploadProgress, minHeight: 8),
              ],
            ],
          ),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Resumen listo para generar', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                Text('• Obra: ${_titleCtrl.text.trim()} ($_selectedCounty Co.)', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text('• Especialidad: ${_selectedSpecialties.join(", ")}', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text('• Planos/fotos adjuntos: ${_files.length}', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text('• Partidas revisadas: ${_materials.length} materiales · ${_labor.length} tareas', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                const Text(
                  'Se entregarán 3 documentos en formato DRAFT: 01 Cost Analysis, 02 Material List y 03 Client Proposal.',
                  style: TextStyle(fontSize: 13.5, color: AlkanColors.muted, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        ElevatedButton.icon(
          onPressed: _generateFinalPackage,
          style: ElevatedButton.styleFrom(
            backgroundColor: AlkanColors.approved,
            minimumSize: const Size(double.infinity, 70),
          ),
          icon: const Icon(Icons.rocket_launch, size: 30),
          label: const Text('GENERAR ESTIMADO (3 PDFs)', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
        ),
      ],
    );
  }
}
