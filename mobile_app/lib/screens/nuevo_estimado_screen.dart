import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../services/voice_dictation_service.dart';
import '../theme/alkan_theme.dart';

/// Pantalla 2 — Nuevo Estimado: Contratista, Especialidad, Planos (WhatsApp/PDF/Cámara) y Dictado por Voz.
class NuevoEstimadoScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final List<String> initialFiles;

  const NuevoEstimadoScreen({
    super.key,
    required this.api,
    required this.store,
    this.initialFiles = const [],
  });

  @override
  State<NuevoEstimadoScreen> createState() => _NuevoEstimadoScreenState();
}

class _NuevoEstimadoScreenState extends State<NuevoEstimadoScreen> {
  static const _counties = ['King', 'Pierce', 'Snohomish', 'Kitsap', 'Thurston', 'Spokane', 'Clark', 'Whatcom', 'Skagit'];
  static const _specialties = [
    {'id': 'metal', 'label': 'Metal / Acero', 'defaultProfile': 'ss_custom_iron_works'},
    {'id': 'techado', 'label': 'Techado (Roofing)', 'defaultProfile': 'pj_roofing'},
    {'id': 'tablaroca', 'label': 'Tablaroca (Drywall)', 'defaultProfile': 'diaz_finish_carpenter'},
    {'id': 'pintura', 'label': 'Pintura', 'defaultProfile': 'diaz_finish_carpenter'},
    {'id': 'molduras', 'label': 'Molduras / Carpintería', 'defaultProfile': 'diaz_finish_carpenter'},
    {'id': 'cubiertas', 'label': 'Cubiertas (Countertops)', 'defaultProfile': 'jc_granite_design'},
  ];

  final _keyCtrl = TextEditingController();
  final _titleCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  final _voice = VoiceDictationService();
  final _imagePicker = ImagePicker();

  List<ContractorProfileItem> _profiles = [];
  String _selectedProfile = 'ss_custom_iron_works';
  String _selectedSpecialty = 'metal';
  String _selectedCounty = 'King';
  final List<File> _selectedFiles = [];
  bool _hasAnthropicKey = false;
  bool _useFullAgent = false;
  bool _listening = false;
  bool _submitting = false;
  double _uploadProgress = 0;
  String? _statusMsg;

  @override
  void initState() {
    super.initState();
    for (final p in widget.initialFiles) {
      final f = File(p);
      if (f.existsSync()) _selectedFiles.add(f);
    }
    _loadMetadata();
  }

  Future<void> _loadMetadata() async {
    try {
      final profiles = await widget.api.fetchProfiles();
      final health = await widget.api.fetchHealth(widget.api.session!.baseUrl);
      if (!mounted) return;
      setState(() {
        _profiles = profiles;
        if (profiles.isNotEmpty && !profiles.any((p) => p.name == _selectedProfile)) {
          _selectedProfile = profiles.first.name;
        }
        _hasAnthropicKey = health['has_anthropic_key'] == true;
        _useFullAgent = _hasAnthropicKey && _selectedFiles.isNotEmpty;
      });
    } catch (_) {
      // Mantiene valores por defecto si está offline
    }
  }

  Future<void> _pickPdfOrZip() async {
    final result = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      type: FileType.custom,
      allowedExtensions: ['pdf', 'zip'],
    );
    if (result == null) return;
    setState(() {
      for (final f in result.files) {
        if (f.path != null) _selectedFiles.add(File(f.path!));
      }
      if (_hasAnthropicKey) _useFullAgent = true;
    });
  }

  Future<void> _importFromWhatsAppOrFiles() async {
    final shared = await widget.api.consumeSharedFiles();
    if (shared.isNotEmpty) {
      setState(() {
        for (final p in shared) {
          _selectedFiles.add(File(p));
        }
      });
      return;
    }
    // Abre el selector del sistema donde Android lista Documentos de WhatsApp / Descargas
    final result = await FilePicker.platform.pickFiles(allowMultiple: true, type: FileType.any);
    if (result == null) return;
    setState(() {
      for (final f in result.files) {
        if (f.path != null) _selectedFiles.add(File(f.path!));
      }
    });
  }

  Future<void> _takePhoto() async {
    final photo = await _imagePicker.pickImage(source: ImageSource.camera, imageQuality: 85);
    if (photo == null) return;
    setState(() => _selectedFiles.add(File(photo.path)));
  }

  Future<void> _toggleVoice() async {
    if (_listening) {
      await _voice.stopListening();
      setState(() => _listening = false);
      return;
    }
    final started = await _voice.startListening(
      onText: (text, isFinal) {
        if (!mounted) return;
        setState(() {
          _notesCtrl.text = text;
          if (_keyCtrl.text.trim().isEmpty && text.trim().isNotEmpty) {
            final firstWord = text.trim().split(RegExp(r'\s+')).first.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9_-]'), '');
            if (firstWord.length >= 2) {
              _keyCtrl.text = firstWord.substring(0, firstWord.length.clamp(2, 14));
            }
          }
          if (isFinal) _listening = false;
        });
      },
    );
    if (!started && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Dictado por voz no disponible en este dispositivo; puedes escribir tus notas abajo.')),
      );
      return;
    }
    setState(() => _listening = true);
  }

  String _normalizedKey() {
    var k = _keyCtrl.text.trim().toUpperCase().replaceAll(RegExp(r'[^A-Z0-9_-]+'), '_');
    if (k.length < 2) {
      k = 'OBRA_${DateTime.now().millisecondsSinceEpoch % 10000}';
    }
    return k.substring(0, k.length.clamp(2, 24));
  }

  Future<void> _submit() async {
    final key = _normalizedKey();
    final title = _titleCtrl.text.trim().isEmpty ? key : _titleCtrl.text.trim();
    setState(() {
      _submitting = true;
      _uploadProgress = 0;
      _statusMsg = 'Preparando envío...';
    });

    try {
      String? uploadId;
      if (_selectedFiles.isNotEmpty) {
        uploadId = widget.api.newUploadId();
        for (int i = 0; i < _selectedFiles.length; i++) {
          final file = _selectedFiles[i];
          setState(() => _statusMsg = 'Subiendo ${file.uri.pathSegments.last} (${i + 1}/${_selectedFiles.length})...');
          await widget.api.uploadChunkedFile(
            uploadId: uploadId,
            file: file,
            onProgress: (frac) {
              if (mounted) {
                setState(() => _uploadProgress = (i + frac) / _selectedFiles.length);
              }
            },
          );
        }
      }

      setState(() => _statusMsg = 'Generando paquete ALKAN (DRAFT)...');
      String runId;
      if (_useFullAgent && uploadId != null) {
        final spec = _specialties.firstWhere((s) => s['id'] == _selectedSpecialty);
        final res = await widget.api.startAgentRun(
          key: key,
          profile: _selectedProfile,
          tradeScope: spec['label']!,
          uploadId: uploadId,
          notes: _notesCtrl.text.trim(),
        );
        runId = (res['id'] ?? '').toString();
      } else {
        final summary = await widget.api.startQuickPackage(
          key: key,
          projectTitle: title,
          profile: _selectedProfile,
          specialty: _selectedSpecialty,
          county: _selectedCounty,
          voiceNotes: _notesCtrl.text.trim(),
          uploadId: uploadId,
        );
        runId = (summary.run['id'] ?? '').toString();
      }

      if (mounted) {
        Navigator.pop(context, runId);
      }
    } catch (e) {
      // Si falla la red, guardar borrador en cola offline para sincronizar al volver la señal
      await widget.store.addPendingDraft(
        PendingOfflineEstimate(
          localId: 'LOCAL_${DateTime.now().millisecondsSinceEpoch}',
          key: key,
          projectTitle: title,
          profile: _selectedProfile,
          specialty: _selectedSpecialty,
          county: _selectedCounty,
          voiceNotes: _notesCtrl.text.trim(),
          filePaths: _selectedFiles.map((f) => f.path).toList(),
          useQuickPackage: !_useFullAgent,
          createdAt: DateTime.now().toIso8601String(),
        ),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Sin conexión o error ($e). Guardado en cola offline para sincronizar luego.')),
        );
        Navigator.pop(context);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  void dispose() {
    _keyCtrl.dispose();
    _titleCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final profMatches = _profiles.where((p) => p.name == _selectedProfile);
    final currentProf = profMatches.isNotEmpty ? profMatches.first : null;
    return Scaffold(
      appBar: AppBar(title: const Text('Nuevo Estimado')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Selector de Contratista con Logo visible
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AlkanColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('1. Contratista y Especialidad', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Container(
                      width: 56,
                      height: 56,
                      decoration: BoxDecoration(
                        color: AlkanColors.background,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: AlkanColors.border),
                      ),
                      child: (currentProf != null && currentProf.hasLogo && widget.api.session != null)
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(10),
                              child: Image.network(
                                widget.api.profileLogoUrl(currentProf.name),
                                headers: widget.api.authHeaders(),
                                fit: BoxFit.contain,
                                errorBuilder: (_, __, ___) => const Icon(Icons.apartment, size: 30, color: AlkanColors.primary),
                              ),
                            )
                          : const Icon(Icons.apartment, size: 30, color: AlkanColors.primary),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        value: _profiles.any((p) => p.name == _selectedProfile) ? _selectedProfile : null,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: 'Empresa Contratista'),
                        items: _profiles
                            .map((p) => DropdownMenuItem(value: p.name, child: Text(p.contractor, overflow: TextOverflow.ellipsis)))
                            .toList(),
                        onChanged: (val) {
                          if (val != null) setState(() => _selectedProfile = val);
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _selectedSpecialty,
                  decoration: const InputDecoration(labelText: 'Especialidad (Washington)'),
                  items: _specialties
                      .map((s) => DropdownMenuItem(value: s['id'], child: Text(s['label']!)))
                      .toList(),
                  onChanged: (val) {
                    if (val == null) return;
                    setState(() {
                      _selectedSpecialty = val;
                      final defProf = _specialties.firstWhere((s) => s['id'] == val)['defaultProfile'];
                      if (defProf != null && _profiles.any((p) => p.name == defProf)) {
                        _selectedProfile = defProf;
                      }
                    });
                  },
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _selectedCounty,
                  decoration: const InputDecoration(labelText: 'Condado WA (Prevailing Wage L&I)'),
                  items: _counties.map((c) => DropdownMenuItem(value: c, child: Text('$c County'))).toList(),
                  onChanged: (val) {
                    if (val != null) setState(() => _selectedCounty = val);
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // 3 botones grandes de carga de archivos
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AlkanColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('2. Planos, Especificaciones o Fotos', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _submitting ? null : _pickPdfOrZip,
                  icon: const Icon(Icons.picture_as_pdf, size: 26),
                  label: const Text('Subir PDF / ZIP de Planos'),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _submitting ? null : _importFromWhatsAppOrFiles,
                  icon: const Icon(Icons.chat, size: 26),
                  label: const Text('Traer desde WhatsApp / Archivos'),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _submitting ? null : _takePhoto,
                  icon: const Icon(Icons.camera_alt, size: 26),
                  label: const Text('Foto de Plano o Cotización'),
                ),
                if (_selectedFiles.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  for (int i = 0; i < _selectedFiles.length; i++)
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.insert_drive_file, color: AlkanColors.primary),
                      title: Text(_selectedFiles[i].uri.pathSegments.last, overflow: TextOverflow.ellipsis),
                      trailing: IconButton(
                        icon: const Icon(Icons.close, color: AlkanColors.noGo),
                        onPressed: () => setState(() => _selectedFiles.removeAt(i)),
                      ),
                    ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 14),

          // Clave del proyecto + Dictado por Voz Push-to-Talk
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AlkanColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('3. Proyecto y Dictado por Voz', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                TextField(
                  controller: _keyCtrl,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(
                    labelText: 'Clave corta del proyecto (ej. WSJ, HC3)',
                    hintText: 'MADISON_ES',
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _titleCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Nombre de la obra',
                    hintText: 'Ej. Remodelación Escuela Madison',
                  ),
                ),
                const SizedBox(height: 12),
                ElevatedButton.icon(
                  onPressed: _submitting ? null : _toggleVoice,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _listening ? AlkanColors.noGo : AlkanColors.accent,
                    minimumSize: const Size(double.infinity, 64),
                  ),
                  icon: Icon(_listening ? Icons.stop_circle : Icons.mic, size: 30),
                  label: Text(_listening ? 'ESCUCHANDO... TOCA PARA PARAR' : '🎙️ TOCA PARA DICTAR POR VOZ'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _notesCtrl,
                  maxLines: 3,
                  decoration: const InputDecoration(
                    labelText: 'Notas e instrucciones (dictadas o escritas)',
                    hintText: 'Ej. Solo base bid, excluir pintura en campo...',
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          if (_hasAnthropicKey && _selectedFiles.isNotEmpty)
            SwitchListTile(
              title: const Text('Leer planos completos con Agente IA', style: TextStyle(fontWeight: FontWeight.w800)),
              subtitle: Text(
                _useFullAgent
                    ? 'Tarda 2-6 min (takeoff completo de PDFs/fotos)'
                    : 'Modo rápido con plantilla base + perfil contratista',
              ),
              value: _useFullAgent,
              onChanged: (v) => setState(() => _useFullAgent = v),
            ),

          if (_submitting) ...[
            const SizedBox(height: 10),
            LinearProgressIndicator(value: _uploadProgress > 0 ? _uploadProgress : null, minHeight: 8),
            const SizedBox(height: 6),
            Text(_statusMsg ?? 'Procesando...', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700)),
          ],
          const SizedBox(height: 14),
          ElevatedButton.icon(
            onPressed: _submitting ? null : _submit,
            style: ElevatedButton.styleFrom(minimumSize: const Size(double.infinity, 68)),
            icon: const Icon(Icons.rocket_launch, size: 28),
            label: const Text('GENERAR ESTIMADO', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900)),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
