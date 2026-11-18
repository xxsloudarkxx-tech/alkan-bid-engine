import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_components.dart';

/// Calibración "Configurar una vez" — Módulos independientes A–G + % de calibración real.
class MiEmpresaPreciosScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore? store;
  final String? initialProfileName;
  final String? initialFocusModule;
  final bool embedded;
  final VoidCallback? onSaved;

  const MiEmpresaPreciosScreen({
    super.key,
    required this.api,
    this.store,
    this.initialProfileName,
    this.initialFocusModule,
    this.embedded = false,
    this.onSaved,
  });

  @override
  State<MiEmpresaPreciosScreen> createState() => _MiEmpresaPreciosScreenState();
}

class _MiEmpresaPreciosScreenState extends State<MiEmpresaPreciosScreen> {
  static const _specOptions = [
    {'id': 'metal', 'label': 'Metal / Acero', 'scope': 'Metal fabrication, structural steel, railings, fences and gates'},
    {'id': 'techado', 'label': 'Techado (Roofing)', 'scope': 'Commercial and residential roofing, TPO, shingles, flashing'},
    {'id': 'tablaroca', 'label': 'Tablaroca (Drywall)', 'scope': 'Metal framing, gypsum board, taping, finishing and acoustic insulation'},
    {'id': 'pintura', 'label': 'Pintura', 'scope': 'Interior and exterior architectural painting and high-performance coatings'},
    {'id': 'molduras', 'label': 'Molduras / Carpintería', 'scope': 'Finish carpentry, wood trim, millwork and casework'},
    {'id': 'cubiertas', 'label': 'Cubiertas (Countertops)', 'scope': 'Stone, quartz and solid surface countertops fabrication and installation'},
  ];

  late final OfflineStore _store = widget.store ?? OfflineStore();
  List<ContractorProfileItem> _profiles = List.of(defaultAlkanProfiles);
  late String? _selectedName = widget.initialProfileName ?? defaultAlkanProfiles.first.name;
  Map<String, dynamic>? _rawProfile;
  ProfileCalibration? _calibration;
  List<int>? _pendingLogoBytes;

  final _nameCtrl = TextEditingController(text: defaultAlkanProfiles.first.contractor);
  final _addressCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _contactCtrl = TextEditingController();
  final _licenseCtrl = TextEditingController();
  final _prefixCtrl = TextEditingController();
  final _scopePolicyCtrl = TextEditingController();

  final _shopRateCtrl = TextEditingController(text: '65.00');
  final _adminRateCtrl = TextEditingController(text: '75.00');
  final _burdenCtrl = TextEditingController(text: '15');

  final _contingencyCtrl = TextEditingController(text: '5');
  final _overheadCtrl = TextEditingController(text: '10');
  final _profitCtrl = TextEditingController(text: '10');
  final _roundingCtrl = TextEditingController(text: '50');
  final _validityCtrl = TextEditingController(text: '30');

  final _supplierCtrl = TextEditingController(text: 'Farwest Steel');
  final _newUserCtrl = TextEditingController();
  final _newUserPassCtrl = TextEditingController();
  String _newUserRole = 'estimator';
  List<Map<String, dynamic>> _orgUsers = [];

  final Set<String> _selectedSpecs = {};
  String _activeModule = 'ALL'; // ALL o A..G
  bool _syncing = true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    if (widget.initialFocusModule != null && widget.initialFocusModule!.isNotEmpty) {
      _activeModule = widget.initialFocusModule!;
    }
    _loadProfiles();
  }

  @override
  void didUpdateWidget(covariant MiEmpresaPreciosScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialProfileName != null && widget.initialProfileName != oldWidget.initialProfileName) {
      _selectProfile(widget.initialProfileName!);
    }
    if (widget.initialFocusModule != null && widget.initialFocusModule != oldWidget.initialFocusModule) {
      setState(() => _activeModule = widget.initialFocusModule!);
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

  Future<void> _loadProfiles() async {
    final cached = await _store.loadCachedProfiles();
    if (cached.isNotEmpty && mounted) {
      final merged = _mergeProfiles(cached);
      setState(() {
        _profiles = merged;
        if (_selectedName == null || !merged.any((p) => p.name == _selectedName)) {
          _selectedName = merged.first.name;
        }
      });
    }
    if (_selectedName != null) {
      final cachedDetail = await _store.loadCachedProfileDetail(_selectedName!);
      if (cachedDetail != null && mounted) {
        _applyDetailToFields(_selectedName!, cachedDetail);
      }
    }

    try {
      final target = _selectedName;
      final results = await Future.wait<dynamic>([
        widget.api.fetchProfiles(),
        target != null ? widget.api.fetchProfileDetail(target).catchError((_) => <String, dynamic>{}) : Future.value(<String, dynamic>{}),
        target != null ? widget.api.fetchCalibration(target).catchError((_) => null) : Future.value(null),
        widget.api.session?.role == 'admin'
            ? widget.api.fetchUsers().catchError((_) => <Map<String, dynamic>>[])
            : Future.value(<Map<String, dynamic>>[]),
      ]);
      if (!mounted) return;
      final remoteProfiles = results[0] as List<ContractorProfileItem>;
      final remoteDetail = results[1] as Map<String, dynamic>;
      final remoteCal = results[2] as ProfileCalibration?;
      final remoteUsers = results[3] as List<Map<String, dynamic>>;

      final merged = _mergeProfiles([...cached, ...remoteProfiles]);
      await _store.saveCachedProfiles(merged);
      setState(() {
        _profiles = merged;
        _orgUsers = remoteUsers;
        if (remoteCal != null) _calibration = remoteCal;
        if (_selectedName == null || !merged.any((p) => p.name == _selectedName)) {
          _selectedName = merged.first.name;
        }
      });
      if (remoteDetail.isNotEmpty && _selectedName != null) {
        await _store.saveCachedProfileDetail(_selectedName!, remoteDetail);
        _applyDetailToFields(_selectedName!, remoteDetail);
      }
    } catch (_) {
      // Silencioso en modo offline
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  void _applyDetailToFields(String name, Map<String, dynamic> detail) {
    final prof = Map<String, dynamic>.from(detail['profile'] as Map? ?? const {});
    final c = Map<String, dynamic>.from((prof['contractor'] as Map?) ?? {});
    final mk = Map<String, dynamic>.from((prof['markups'] as Map?) ?? {});
    final lr = Map<String, dynamic>.from((prof['labor_rates'] as Map?) ?? {});
    final scopeList = (prof['scope_policy'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList();
    final scopeTxt = scopeList.join('\n').toLowerCase();

    _selectedSpecs.clear();
    if (scopeTxt.contains('metal') || scopeTxt.contains('steel') || scopeTxt.contains('rail')) _selectedSpecs.add('metal');
    if (scopeTxt.contains('roof') || scopeTxt.contains('tpo') || scopeTxt.contains('shingle')) _selectedSpecs.add('techado');
    if (scopeTxt.contains('drywall') || scopeTxt.contains('gypsum') || scopeTxt.contains('tablaroca')) _selectedSpecs.add('tablaroca');
    if (scopeTxt.contains('paint') || scopeTxt.contains('coating') || scopeTxt.contains('pintura')) _selectedSpecs.add('pintura');
    if (scopeTxt.contains('carpentry') || scopeTxt.contains('millwork') || scopeTxt.contains('moldura')) _selectedSpecs.add('molduras');
    if (scopeTxt.contains('countertop') || scopeTxt.contains('quartz') || scopeTxt.contains('granite')) _selectedSpecs.add('cubiertas');

    setState(() {
      _selectedName = name;
      _rawProfile = prof;
      _pendingLogoBytes = null;
      _nameCtrl.text = (c['name'] ?? '').toString();
      _licenseCtrl.text = (c['license'] ?? '').toString();
      _phoneCtrl.text = (c['phone'] ?? '').toString();
      _addressCtrl.text = (c['address'] ?? '').toString();
      _contactCtrl.text = (c['contact'] ?? '').toString();
      _prefixCtrl.text = (prof['estimate_prefix'] ?? '').toString();
      _scopePolicyCtrl.text = scopeList.join('\n');

      _contingencyCtrl.text = (mk['contingency_pct'] ?? '5').toString();
      _overheadCtrl.text = (mk['overhead_pct'] ?? '10').toString();
      _profitCtrl.text = (mk['profit_pct'] ?? '10').toString();
      _roundingCtrl.text = (mk['rounding'] ?? '50').toString();
      _validityCtrl.text = (prof['validity_days'] ?? '30').toString();

      _shopRateCtrl.text = ((lr['SHOP'] as Map?)?['rate'] ?? '65.00').toString();
      _adminRateCtrl.text = ((lr['ADMIN'] as Map?)?['rate'] ?? '75.00').toString();
      _burdenCtrl.text = (prof['burden_pct'] ?? '15').toString();
    });
  }

  Future<void> _selectProfile(String name) async {
    setState(() {
      _selectedName = name;
      _syncing = true;
    });
    final cachedDetail = await _store.loadCachedProfileDetail(name);
    if (cachedDetail != null && mounted) {
      _applyDetailToFields(name, cachedDetail);
    }
    try {
      final results = await Future.wait<dynamic>([
        widget.api.fetchProfileDetail(name),
        widget.api.fetchCalibration(name).catchError((_) => null),
      ]);
      final detail = results[0] as Map<String, dynamic>;
      final cal = results[1] as ProfileCalibration?;
      await _store.saveCachedProfileDetail(name, detail);
      if (!mounted) return;
      _applyDetailToFields(name, detail);
      if (cal != null) setState(() => _calibration = cal);
    } catch (_) {
      // Mantiene vista cacheada
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<void> _pickLogo() async {
    final picked = await ImagePicker().pickImage(source: ImageSource.gallery, imageQuality: 90);
    if (picked == null) return;
    final bytes = await File(picked.path).readAsBytes();
    setState(() => _pendingLogoBytes = bytes);
  }

  Future<void> _saveProfile({String moduleLabel = 'Calibración'}) async {
    if (_selectedName == null || _rawProfile == null) return;
    setState(() => _saving = true);
    try {
      final updated = Map<String, dynamic>.from(_rawProfile!);
      final c = Map<String, dynamic>.from((updated['contractor'] as Map?) ?? {});
      c['name'] = _nameCtrl.text.trim();
      c['license'] = _licenseCtrl.text.trim();
      c['phone'] = _phoneCtrl.text.trim();
      c['address'] = _addressCtrl.text.trim();
      c['contact'] = _contactCtrl.text.trim();
      updated['contractor'] = c;

      if (_prefixCtrl.text.trim().isNotEmpty) {
        updated['estimate_prefix'] = _prefixCtrl.text.trim();
      }

      // Combinar scope_policy manual con chips de especialidad seleccionados
      final scopes = _scopePolicyCtrl.text
          .split('\n')
          .map((e) => e.trim())
          .where((e) => e.isNotEmpty)
          .toList();
      for (final sid in _selectedSpecs) {
        final found = _specOptions.firstWhere((s) => s['id'] == sid);
        final scopeLine = found['scope']!;
        if (!scopes.any((s) => s.toLowerCase().contains(sid))) {
          scopes.add(scopeLine);
        }
      }
      if (scopes.isNotEmpty) updated['scope_policy'] = scopes;

      final mk = Map<String, dynamic>.from((updated['markups'] as Map?) ?? {});
      mk['contingency_pct'] = _contingencyCtrl.text.trim();
      mk['overhead_pct'] = _overheadCtrl.text.trim();
      mk['profit_pct'] = _profitCtrl.text.trim();
      mk['rounding'] = _roundingCtrl.text.trim().isEmpty ? '50' : _roundingCtrl.text.trim();
      updated['markups'] = mk;
      updated['validity_days'] = int.tryParse(_validityCtrl.text.trim()) ?? 30;
      updated['burden_pct'] = _burdenCtrl.text.trim().isEmpty ? '15' : _burdenCtrl.text.trim();

      final lr = Map<String, dynamic>.from((updated['labor_rates'] as Map?) ?? {});
      if (_shopRateCtrl.text.trim().isNotEmpty) {
        final shop = Map<String, dynamic>.from((lr['SHOP'] as Map?) ?? {'label': 'Shop / Taller', 'kind': 'loaded'});
        shop['rate'] = _shopRateCtrl.text.trim();
        lr['SHOP'] = shop;
      }
      if (_adminRateCtrl.text.trim().isNotEmpty) {
        final adm = Map<String, dynamic>.from((lr['ADMIN'] as Map?) ?? {'label': 'PM / Oficina', 'kind': 'loaded'});
        adm['rate'] = _adminRateCtrl.text.trim();
        lr['ADMIN'] = adm;
      }
      updated['labor_rates'] = lr;

      await widget.api.saveProfile(
        name: _selectedName!,
        profile: updated,
        logoBytes: _pendingLogoBytes,
      );
      await _selectProfile(_selectedName!);
      widget.onSaved?.call();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ $moduleLabel guardado. No se volverá a pedir al dictar.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo guardar: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _registerNewCompanyDialog() async {
    final cnameCtrl = TextEditingController();
    final contactCtrl = TextEditingController();
    final phoneCtrl = TextEditingController();
    final addrCtrl = TextEditingController();
    final licCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Registrar Empresa / Contratista', style: TextStyle(fontWeight: FontWeight.w900)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: cnameCtrl, decoration: const InputDecoration(labelText: 'Nombre legal / empresa *')),
              const SizedBox(height: 10),
              TextField(controller: contactCtrl, decoration: const InputDecoration(labelText: 'Persona de contacto')),
              const SizedBox(height: 10),
              TextField(controller: phoneCtrl, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Teléfono')),
              const SizedBox(height: 10),
              TextField(controller: addrCtrl, decoration: const InputDecoration(labelText: 'Dirección / Ciudad WA')),
              const SizedBox(height: 10),
              TextField(controller: licCtrl, decoration: const InputDecoration(labelText: 'Licencia WA / UBI (opcional)')),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('GUARDAR')),
        ],
      ),
    );
    if (ok != true || cnameCtrl.text.trim().isEmpty) return;
    setState(() => _saving = true);
    try {
      final res = await widget.api.registerQuickProfile(
        contractorName: cnameCtrl.text.trim(),
        contact: contactCtrl.text.trim(),
        phone: phoneCtrl.text.trim(),
        address: addrCtrl.text.trim(),
        license: licCtrl.text.trim(),
      );
      final created = Map<String, dynamic>.from(res['profile'] as Map);
      final newName = (created['name'] ?? '').toString();
      final remoteList = (res['profiles'] as List<dynamic>? ?? const [])
          .map((e) => ContractorProfileItem.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
      final merged = _mergeProfiles([..._profiles, ...remoteList]);
      await _store.saveCachedProfiles(merged);
      await _store.saveCachedProfileDetail(newName, created);
      if (mounted) {
        setState(() => _profiles = merged);
        await _selectProfile(newName);
        widget.onSaved?.call();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Contratista "${cnameCtrl.text.trim()}" registrado y activo.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al registrar: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _uploadSupplierQuote() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.any);
    if (result == null || result.files.single.path == null) return;
    final file = File(result.files.single.path!);
    setState(() => _saving = true);
    try {
      final res = await widget.api.importSupplierQuote(
        fileName: result.files.single.name,
        bytes: await file.readAsBytes(),
        supplier: _supplierCtrl.text.trim().isEmpty ? 'Proveedor WA' : _supplierCtrl.text.trim(),
      );
      final count = res['imported_count'] ?? 0;
      if (_selectedName != null) {
        await _selectProfile(_selectedName!);
      }
      widget.onSaved?.call();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Cotización cargada ($count renglones QUOTE importados).')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al importar: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _createRealUser() async {
    final uname = _newUserCtrl.text.trim();
    final pwd = _newUserPassCtrl.text;
    if (uname.length < 3 || pwd.length < 8) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Usuario (mín. 3 chars) y contraseña temporal (mín. 8 chars) requeridos.')),
      );
      return;
    }
    setState(() => _saving = true);
    try {
      await widget.api.createUser(
        username: uname,
        password: pwd,
        userRole: _newUserRole,
        mustChangePassword: true,
      );
      _newUserCtrl.clear();
      _newUserPassCtrl.clear();
      _orgUsers = await widget.api.fetchUsers();
      if (mounted) {
        setState(() {});
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Usuario $uname creado (deberá cambiar contraseña al entrar).')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al crear usuario: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  int _localFallbackPercent() {
    int pct = 0;
    if (_nameCtrl.text.trim().isNotEmpty &&
        _licenseCtrl.text.trim().isNotEmpty &&
        !_licenseCtrl.text.toLowerCase().contains('pending') &&
        _phoneCtrl.text.trim().isNotEmpty &&
        _addressCtrl.text.trim().isNotEmpty) {
      pct += 20;
    }
    final profItem = _profiles.where((p) => p.name == _selectedName).toList();
    if ((profItem.isNotEmpty && profItem.first.hasLogo) || _pendingLogoBytes != null) pct += 20;
    if (_shopRateCtrl.text.trim().isNotEmpty && _adminRateCtrl.text.trim().isNotEmpty) pct += 20;
    if (_contingencyCtrl.text.trim().isNotEmpty && _overheadCtrl.text.trim().isNotEmpty && _profitCtrl.text.trim().isNotEmpty) pct += 20;
    return pct;
  }

  bool _showModule(String code) => _activeModule == 'ALL' || _activeModule == code;

  Widget _moduleCard({
    required String code,
    required String title,
    required String subtitle,
    required bool? complete,
    required Widget child,
    VoidCallback? onSaveModule,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 30,
                    height: 30,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: complete == true ? AlkanColors.approved.withOpacity(0.14) : AlkanColors.azulSuave,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      code,
                      style: TextStyle(
                        fontWeight: FontWeight.w900,
                        color: complete == true ? AlkanColors.approved : AlkanColors.primary,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                        Text(subtitle, style: const TextStyle(fontSize: 12.5, color: AlkanColors.textSecondary)),
                      ],
                    ),
                  ),
                  if (complete != null)
                    Icon(
                      complete ? Icons.check_circle : Icons.pending_outlined,
                      color: complete ? AlkanColors.approved : AlkanColors.analyzing,
                      size: 22,
                    ),
                ],
              ),
              const SizedBox(height: 14),
              child,
              if (onSaveModule != null) ...[
                const SizedBox(height: 14),
                AlkanPrimaryButton(
                  label: 'Guardar módulo $code',
                  icon: Icons.save_outlined,
                  loading: _saving,
                  onPressed: onSaveModule,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _addressCtrl.dispose();
    _phoneCtrl.dispose();
    _contactCtrl.dispose();
    _licenseCtrl.dispose();
    _prefixCtrl.dispose();
    _scopePolicyCtrl.dispose();
    _shopRateCtrl.dispose();
    _adminRateCtrl.dispose();
    _burdenCtrl.dispose();
    _contingencyCtrl.dispose();
    _overheadCtrl.dispose();
    _profitCtrl.dispose();
    _roundingCtrl.dispose();
    _validityCtrl.dispose();
    _supplierCtrl.dispose();
    _newUserCtrl.dispose();
    _newUserPassCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final calPct = _calibration?.percent ?? _localFallbackPercent();
    final modById = {
      for (final m in (_calibration?.modules ?? const <CalibrationModule>[])) m.id: m.complete,
    };

    final bodyContent = Column(
      children: [
        if (_syncing) const LinearProgressIndicator(minHeight: 3),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Tarjeta de Calibración Real (0-100%)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      DropdownButtonFormField<String>(
                        value: _profiles.any((p) => p.name == _selectedName) ? _selectedName : null,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: 'Contratista en calibración'),
                        items: _profiles
                            .map((p) => DropdownMenuItem(value: p.name, child: Text(p.contractor, overflow: TextOverflow.ellipsis)))
                            .toList(),
                        onChanged: (v) {
                          if (v != null) _selectProfile(v);
                        },
                      ),
                      const SizedBox(height: 14),
                      AlkanProgressIndicator(
                        percent: calPct,
                        label: 'Calibración real del perfil',
                        helper: _calibration != null && _calibration!.missingData.isNotEmpty
                            ? 'Faltante en empresa: ${_calibration!.missingData.join(", ")}'
                            : 'Lo guardado aquí ya no se vuelve a pedir al dictar.',
                      ),
                      const SizedBox(height: 12),
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Row(
                          children: [
                            for (final item in const [
                              ('ALL', 'Todos'),
                              ('A', 'A Empresa'),
                              ('B', 'B Logo'),
                              ('C', 'C Licencias'),
                              ('D', 'D Oficios'),
                              ('E', 'E Tarifas'),
                              ('F', 'F Markups'),
                              ('G', 'G Proveedores'),
                            ])
                              Padding(
                                padding: const EdgeInsets.only(right: 6),
                                child: ChoiceChip(
                                  label: Text(item.$2),
                                  selected: _activeModule == item.$1,
                                  selectedColor: AlkanColors.primary,
                                  labelStyle: TextStyle(
                                    color: _activeModule == item.$1 ? Colors.white : AlkanColors.textPrimary,
                                    fontWeight: FontWeight.w700,
                                    fontSize: 12.5,
                                  ),
                                  onSelected: (_) => setState(() => _activeModule = item.$1),
                                ),
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 10),
                      AlkanSecondaryButton(
                        label: '+ Registrar Nueva Empresa / Contratista',
                        icon: Icons.add_business,
                        onPressed: _saving ? null : _registerNewCompanyDialog,
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 14),

              // Módulo A · Empresa
              if (_showModule('A'))
                _moduleCard(
                  code: 'A',
                  title: 'Empresa',
                  subtitle: 'Datos generales impresos en encabezado de tus 3 documentos',
                  complete: modById['A'],
                  onSaveModule: () => _saveProfile(moduleLabel: 'Módulo A (Empresa)'),
                  child: Column(
                    children: [
                      TextField(controller: _nameCtrl, decoration: const InputDecoration(labelText: 'Nombre legal')),
                      const SizedBox(height: 10),
                      TextField(controller: _addressCtrl, decoration: const InputDecoration(labelText: 'Dirección fiscal / ciudad')),
                      const SizedBox(height: 10),
                      TextField(controller: _phoneCtrl, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Teléfono')),
                      const SizedBox(height: 10),
                      TextField(controller: _contactCtrl, decoration: const InputDecoration(labelText: 'Contacto principal')),
                    ],
                  ),
                ),

              // Módulo B · Identidad / Logo
              if (_showModule('B'))
                _moduleCard(
                  code: 'B',
                  title: 'Identidad / Logo',
                  subtitle: 'Aparece junto al co-branding ALKAN Assistant en cada PDF',
                  complete: modById['B'],
                  onSaveModule: () => _saveProfile(moduleLabel: 'Módulo B (Logo)'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Container(
                            width: 68,
                            height: 68,
                            decoration: BoxDecoration(
                              color: AlkanColors.background,
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(color: AlkanColors.border),
                            ),
                            child: _pendingLogoBytes != null
                                ? const Icon(Icons.check_circle, color: AlkanColors.approved, size: 34)
                                : (_selectedName != null && widget.api.session != null)
                                    ? ClipRRect(
                                        borderRadius: BorderRadius.circular(12),
                                        child: Image.network(
                                          widget.api.profileLogoUrl(_selectedName!),
                                          headers: widget.api.authHeaders(),
                                          fit: BoxFit.contain,
                                          errorBuilder: (_, __, ___) => const Icon(Icons.image_outlined, color: AlkanColors.muted, size: 32),
                                        ),
                                      )
                                    : const Icon(Icons.image_outlined, color: AlkanColors.muted, size: 32),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: AlkanSecondaryButton(
                              label: _pendingLogoBytes != null ? 'Logo listo para guardar' : 'Seleccionar Logo (PNG/JPG)',
                              icon: Icons.upload_outlined,
                              onPressed: _saving ? null : _pickLogo,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),

              // Módulo C · Contratista (Licencias / Folio)
              if (_showModule('C'))
                _moduleCard(
                  code: 'C',
                  title: 'Contratista y Licencias WA',
                  subtitle: 'Licencia L&I, UBI y prefijo de folio de propuesta',
                  complete: modById['A'],
                  onSaveModule: () => _saveProfile(moduleLabel: 'Módulo C (Licencias)'),
                  child: Column(
                    children: [
                      TextField(controller: _licenseCtrl, decoration: const InputDecoration(labelText: 'Licencia WA Contractor y UBI')),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _prefixCtrl,
                        textCapitalization: TextCapitalization.characters,
                        decoration: const InputDecoration(labelText: 'Prefijo de folio (ej. SS-EST-2026)'),
                      ),
                    ],
                  ),
                ),

              // Módulo D · Especialidades (6)
              if (_showModule('D'))
                _moduleCard(
                  code: 'D',
                  title: 'Especialidades (6)',
                  subtitle: 'Oficios activos y política de alcance predeterminada',
                  complete: _selectedSpecs.isNotEmpty || _scopePolicyCtrl.text.trim().isNotEmpty,
                  onSaveModule: () => _saveProfile(moduleLabel: 'Módulo D (Especialidades)'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: _specOptions.map((s) {
                          final id = s['id']!;
                          final sel = _selectedSpecs.contains(id);
                          return FilterChip(
                            label: Text(s['label']!),
                            selected: sel,
                            selectedColor: AlkanColors.primary,
                            checkmarkColor: Colors.white,
                            labelStyle: TextStyle(
                              color: sel ? Colors.white : AlkanColors.textPrimary,
                              fontWeight: FontWeight.w700,
                            ),
                            onSelected: (v) {
                              setState(() {
                                if (v) {
                                  _selectedSpecs.add(id);
                                } else {
                                  _selectedSpecs.remove(id);
                                }
                              });
                            },
                          );
                        }).toList(),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _scopePolicyCtrl,
                        maxLines: 3,
                        decoration: const InputDecoration(labelText: 'Alcance / Scope Policy del perfil'),
                      ),
                    ],
                  ),
                ),

              // Módulo E · Tarifas
              if (_showModule('E'))
                _moduleCard(
                  code: 'E',
                  title: 'Tarifas de Mano de Obra',
                  subtitle: 'Tarifas de taller y oficina (prevailing wage viene por condado)',
                  complete: modById['E'],
                  onSaveModule: () => _saveProfile(moduleLabel: 'Módulo E (Tarifas)'),
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Expanded(child: TextField(controller: _shopRateCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Taller \$/h'))),
                          const SizedBox(width: 8),
                          Expanded(child: TextField(controller: _adminRateCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Oficina \$/h'))),
                        ],
                      ),
                      const SizedBox(height: 10),
                      TextField(controller: _burdenCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Burden (% carga social)')),
                    ],
                  ),
                ),

              // Módulo F · Markups
              if (_showModule('F'))
                _moduleCard(
                  code: 'F',
                  title: 'Markups y Vigencia',
                  subtitle: 'Aplicados automáticamente por el motor de cálculo',
                  complete: modById['F'],
                  onSaveModule: () => _saveProfile(moduleLabel: 'Módulo F (Markups)'),
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Expanded(child: TextField(controller: _contingencyCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Conting. %'))),
                          const SizedBox(width: 8),
                          Expanded(child: TextField(controller: _overheadCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Overhead %'))),
                          const SizedBox(width: 8),
                          Expanded(child: TextField(controller: _profitCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Utilidad %'))),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(child: TextField(controller: _roundingCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Redondeo \$'))),
                          const SizedBox(width: 8),
                          Expanded(child: TextField(controller: _validityCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Vigencia (días)'))),
                        ],
                      ),
                    ],
                  ),
                ),

              // Módulo G · Proveedores y Cotizaciones
              if (_showModule('G'))
                _moduleCard(
                  code: 'G',
                  title: 'Proveedores y Cotizaciones (BUDGET → QUOTE)',
                  subtitle: _calibration != null
                      ? '${_calibration!.quoteCount} renglones QUOTE activos en el libro de precios'
                      : 'Sube cotizaciones CSV/XLSX/PDF/Foto para volver reales los precios',
                  complete: modById['G'],
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextField(controller: _supplierCtrl, decoration: const InputDecoration(labelText: 'Nombre del proveedor')),
                      const SizedBox(height: 10),
                      AlkanPrimaryButton(
                        label: 'Subir Cotización (CSV / XLSX / PDF / Foto)',
                        icon: Icons.upload_file,
                        loading: _saving,
                        onPressed: _uploadSupplierQuote,
                      ),
                    ],
                  ),
                ),

              // Sección de Administración de Usuarios (solo admin)
              if (_activeModule == 'ALL') ...[
                const SizedBox(height: 8),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text('Seguridad y Usuarios (Producción)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                        const SizedBox(height: 6),
                        Text(
                          'Sesión activa: ${widget.api.session?.actor ?? ''} (${widget.api.session?.role ?? ''})',
                          style: const TextStyle(color: AlkanColors.textSecondary, fontWeight: FontWeight.w700),
                        ),
                        if (widget.api.session?.role == 'admin') ...[
                          const SizedBox(height: 12),
                          TextField(controller: _newUserCtrl, decoration: const InputDecoration(labelText: 'Nuevo usuario (ej. carlos_obra)')),
                          const SizedBox(height: 10),
                          TextField(controller: _newUserPassCtrl, obscureText: true, decoration: const InputDecoration(labelText: 'Contraseña temporal (mín. 8 chars)')),
                          const SizedBox(height: 10),
                          DropdownButtonFormField<String>(
                            value: _newUserRole,
                            decoration: const InputDecoration(labelText: 'Rol asignado'),
                            items: const [
                              DropdownMenuItem(value: 'estimator', child: Text('Estimador (obra / campo)')),
                              DropdownMenuItem(value: 'reviewer', child: Text('Revisor / Aprobador independiente')),
                              DropdownMenuItem(value: 'admin', child: Text('Administrador')),
                            ],
                            onChanged: (v) {
                              if (v != null) setState(() => _newUserRole = v);
                            },
                          ),
                          const SizedBox(height: 12),
                          AlkanPrimaryButton(
                            label: 'Crear Usuario Real',
                            icon: Icons.person_add,
                            loading: _saving,
                            onPressed: _createRealUser,
                          ),
                          if (_orgUsers.isNotEmpty) ...[
                            const SizedBox(height: 12),
                            const Text('Usuarios activos:', style: TextStyle(fontWeight: FontWeight.w800)),
                            for (final u in _orgUsers)
                              ListTile(
                                dense: true,
                                contentPadding: EdgeInsets.zero,
                                leading: const Icon(Icons.verified_user_outlined, color: AlkanColors.primary),
                                title: Text('${u['username']} (${u['role']})', style: const TextStyle(fontWeight: FontWeight.w700)),
                                subtitle: Text(u['must_change_password'] == true ? 'Pendiente cambio de contraseña' : 'Contraseña personal activa'),
                              ),
                          ],
                        ] else ...[
                          const SizedBox(height: 6),
                          const Text(
                            'Solo un usuario con rol Administrador puede dar de alta nuevas cuentas.',
                            style: TextStyle(fontSize: 13, color: AlkanColors.textSecondary),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 24),
            ],
          ),
        ),
      ],
    );

    if (widget.embedded) {
      return bodyContent;
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Calibración · Configurar una vez')),
      body: bodyContent,
    );
  }
}
