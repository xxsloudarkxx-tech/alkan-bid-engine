import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';

/// Pantalla 5 — Mi Empresa y Precios (Logo, Licencia WA, UBI, Markups y Cotizaciones).
class MiEmpresaPreciosScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore? store;

  const MiEmpresaPreciosScreen({super.key, required this.api, this.store});

  @override
  State<MiEmpresaPreciosScreen> createState() => _MiEmpresaPreciosScreenState();
}

class _MiEmpresaPreciosScreenState extends State<MiEmpresaPreciosScreen> {
  late final OfflineStore _store = widget.store ?? OfflineStore();
  List<ContractorProfileItem> _profiles = List.of(defaultAlkanProfiles);
  String? _selectedName = defaultAlkanProfiles.first.name;
  Map<String, dynamic>? _rawProfile;
  List<int>? _pendingLogoBytes;

  final _nameCtrl = TextEditingController(text: defaultAlkanProfiles.first.contractor);
  final _licenseCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _addressCtrl = TextEditingController();
  final _contactCtrl = TextEditingController();
  final _contingencyCtrl = TextEditingController(text: '5');
  final _overheadCtrl = TextEditingController(text: '10');
  final _profitCtrl = TextEditingController(text: '10');
  final _shopRateCtrl = TextEditingController(text: '65.00');
  final _adminRateCtrl = TextEditingController(text: '75.00');
  final _supplierCtrl = TextEditingController(text: 'Farwest Steel');
  final _newUserCtrl = TextEditingController();
  final _newUserPassCtrl = TextEditingController();
  String _newUserRole = 'estimator';
  List<Map<String, dynamic>> _orgUsers = [];

  bool _syncing = true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _loadProfiles();
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
    // 1. Pintar caché local al instante sin trabar la UI
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

    // 2. Sincronizar con servidor en paralelo sin bloquear la pantalla
    try {
      final profilesFuture = widget.api.fetchProfiles();
      final detailFuture = _selectedName != null ? widget.api.fetchProfileDetail(_selectedName!) : Future<Map<String, dynamic>?>.value(null);
      final usersFuture = widget.api.session?.role == 'admin'
          ? widget.api.fetchUsers().catchError((_) => <Map<String, dynamic>>[])
          : Future.value(<Map<String, dynamic>>[]);

      final results = await Future.wait<dynamic>([profilesFuture, detailFuture, usersFuture]);
      if (!mounted) return;
      final remoteProfiles = results[0] as List<ContractorProfileItem>;
      final remoteDetail = results[1] as Map<String, dynamic>?;
      final remoteUsers = results[2] as List<Map<String, dynamic>>;

      final merged = _mergeProfiles([...cached, ...remoteProfiles]);
      await _store.saveCachedProfiles(merged);
      setState(() {
        _profiles = merged;
        _orgUsers = remoteUsers;
        if (_selectedName == null || !merged.any((p) => p.name == _selectedName)) {
          _selectedName = merged.first.name;
        }
      });
      if (remoteDetail != null && _selectedName != null) {
        await _store.saveCachedProfileDetail(_selectedName!, remoteDetail);
        _applyDetailToFields(_selectedName!, remoteDetail);
      } else if (_selectedName != null) {
        await _selectProfile(_selectedName!);
      }
    } catch (_) {
      // Silencioso en modo offline: ya mostramos datos cacheados
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  void _applyDetailToFields(String name, Map<String, dynamic> detail) {
    final prof = Map<String, dynamic>.from(detail['profile'] as Map? ?? const {});
    final c = Map<String, dynamic>.from((prof['contractor'] as Map?) ?? {});
    final mk = Map<String, dynamic>.from((prof['markups'] as Map?) ?? {});
    final lr = Map<String, dynamic>.from((prof['labor_rates'] as Map?) ?? {});
    setState(() {
      _selectedName = name;
      _rawProfile = prof;
      _pendingLogoBytes = null;
      _nameCtrl.text = (c['name'] ?? '').toString();
      _licenseCtrl.text = (c['license'] ?? '').toString();
      _phoneCtrl.text = (c['phone'] ?? '').toString();
      _addressCtrl.text = (c['address'] ?? '').toString();
      _contactCtrl.text = (c['contact'] ?? '').toString();
      _contingencyCtrl.text = (mk['contingency_pct'] ?? '5').toString();
      _overheadCtrl.text = (mk['overhead_pct'] ?? '10').toString();
      _profitCtrl.text = (mk['profit_pct'] ?? '10').toString();
      _shopRateCtrl.text = ((lr['SHOP'] as Map?)?['rate'] ?? '65.00').toString();
      _adminRateCtrl.text = ((lr['ADMIN'] as Map?)?['rate'] ?? '75.00').toString();
    });
  }

  Future<void> _selectProfile(String name) async {
    setState(() => _selectedName = name);
    final cachedDetail = await _store.loadCachedProfileDetail(name);
    if (cachedDetail != null && mounted) {
      _applyDetailToFields(name, cachedDetail);
    }
    try {
      final detail = await widget.api.fetchProfileDetail(name);
      await _store.saveCachedProfileDetail(name, detail);
      if (mounted) _applyDetailToFields(name, detail);
    } catch (_) {
      // Mantiene vista sin trabar si falla red
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
        title: const Text('Registrar Empresa / Cliente', style: TextStyle(fontWeight: FontWeight.w900)),
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
        setState(() {
          _profiles = merged;
        });
        _applyDetailToFields(newName, created);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✅ Empresa "${cnameCtrl.text.trim()}" registrada y seleccionada.')),
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

  Future<void> _pickLogo() async {
    final picked = await ImagePicker().pickImage(source: ImageSource.gallery, imageQuality: 90);
    if (picked == null) return;
    final bytes = await File(picked.path).readAsBytes();
    setState(() => _pendingLogoBytes = bytes);
  }

  Future<void> _saveProfile() async {
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

      final mk = Map<String, dynamic>.from((updated['markups'] as Map?) ?? {});
      mk['contingency_pct'] = _contingencyCtrl.text.trim();
      mk['overhead_pct'] = _overheadCtrl.text.trim();
      mk['profit_pct'] = _profitCtrl.text.trim();
      mk.putIfAbsent('rounding', () => '50');
      updated['markups'] = mk;

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
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Perfil de empresa y logo actualizados.')),
        );
      }
      await _selectProfile(_selectedName!);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error al guardar: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _uploadSupplierQuote() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['csv', 'xlsx', 'pdf', 'jpg', 'jpeg', 'png'],
    );
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
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Cotización cargada ($count renglones QUOTE importados).')),
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

  @override
  void dispose() {
    _nameCtrl.dispose();
    _licenseCtrl.dispose();
    _phoneCtrl.dispose();
    _addressCtrl.dispose();
    _contactCtrl.dispose();
    _contingencyCtrl.dispose();
    _overheadCtrl.dispose();
    _profitCtrl.dispose();
    _shopRateCtrl.dispose();
    _adminRateCtrl.dispose();
    _supplierCtrl.dispose();
    _newUserCtrl.dispose();
    _newUserPassCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mi Empresa y Precios')),
      body: Column(
        children: [
          if (_syncing) const LinearProgressIndicator(minHeight: 3),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                DropdownButtonFormField<String>(
                  value: _profiles.any((p) => p.name == _selectedName) ? _selectedName : null,
                  decoration: const InputDecoration(labelText: 'Perfil Activo'),
                  items: _profiles
                      .map((p) => DropdownMenuItem(value: p.name, child: Text(p.contractor)))
                      .toList(),
                  onChanged: (v) {
                    if (v != null) _selectProfile(v);
                  },
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _saving ? null : _registerNewCompanyDialog,
                  icon: const Icon(Icons.add_business),
                  label: const Text('+ Registrar Nueva Empresa / Cliente'),
                ),
                const SizedBox(height: 14),
                OutlinedButton.icon(
                  onPressed: _saving ? null : _pickLogo,
                  icon: const Icon(Icons.image),
                  label: Text(_pendingLogoBytes != null ? 'Logo seleccionado (Listo para guardar)' : 'Cambiar Logo de Empresa'),
                ),
                const SizedBox(height: 14),
                TextField(controller: _nameCtrl, decoration: const InputDecoration(labelText: 'Nombre Legal')),
                const SizedBox(height: 10),
                TextField(controller: _licenseCtrl, decoration: const InputDecoration(labelText: 'Licencia WA y UBI')),
                const SizedBox(height: 10),
                TextField(controller: _phoneCtrl, decoration: const InputDecoration(labelText: 'Teléfono')),
                const SizedBox(height: 10),
                TextField(controller: _addressCtrl, decoration: const InputDecoration(labelText: 'Dirección')),
                const SizedBox(height: 10),
                TextField(controller: _contactCtrl, decoration: const InputDecoration(labelText: 'Contacto Principal')),
                const SizedBox(height: 14),
                const Text('Tarifas por Defecto (\$/hr) y Markups (%)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(child: TextField(controller: _shopRateCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Tarifa Taller \$/h'))),
                    const SizedBox(width: 8),
                    Expanded(child: TextField(controller: _adminRateCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Tarifa Oficina \$/h'))),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(child: TextField(controller: _contingencyCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Conting. %'))),
                    const SizedBox(width: 8),
                    Expanded(child: TextField(controller: _overheadCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Overhead %'))),
                    const SizedBox(width: 8),
                    Expanded(child: TextField(controller: _profitCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Utilidad %'))),
                  ],
                ),
                const SizedBox(height: 14),
                ElevatedButton.icon(
                  onPressed: _saving ? null : _saveProfile,
                  icon: const Icon(Icons.save),
                  label: const Text('GUARDAR DATOS DE EMPRESA'),
                ),
                const SizedBox(height: 22),
                const Divider(),
                const SizedBox(height: 10),
                const Text('Cotizaciones de Proveedores (BUDGET → QUOTE)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 10),
                TextField(controller: _supplierCtrl, decoration: const InputDecoration(labelText: 'Nombre del Proveedor')),
                const SizedBox(height: 10),
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(backgroundColor: AlkanColors.accent),
                  onPressed: _saving ? null : _uploadSupplierQuote,
                  icon: const Icon(Icons.upload_file),
                  label: const Text('SUBIR COTIZACIÓN (CSV / XLSX / PDF / FOTO)'),
                ),
                const SizedBox(height: 22),
                const Divider(),
                const SizedBox(height: 10),
                const Text('Seguridad y Usuarios (Producción)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
                const SizedBox(height: 8),
                Text(
                  'Sesión activa: ${widget.api.session?.actor ?? ''} (${widget.api.session?.role ?? ''})',
                  style: const TextStyle(color: AlkanColors.muted, fontWeight: FontWeight.w700),
                ),
                if (widget.api.session?.role == 'admin') ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _newUserCtrl,
                    decoration: const InputDecoration(labelText: 'Nuevo usuario (ej. carlos_obra)'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _newUserPassCtrl,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: 'Contraseña temporal (mín. 8 caracteres)'),
                  ),
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
                  ElevatedButton.icon(
                    onPressed: _saving ? null : _createRealUser,
                    icon: const Icon(Icons.person_add),
                    label: const Text('CREAR USUARIO REAL'),
                  ),
                  if (_orgUsers.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    const Text('Usuarios activos:', style: TextStyle(fontWeight: FontWeight.w800)),
                    const SizedBox(height: 6),
                    for (final u in _orgUsers)
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.verified_user_outlined),
                        title: Text('${u['username']} (${u['role']})', style: const TextStyle(fontWeight: FontWeight.w700)),
                        subtitle: Text(
                          u['must_change_password'] == true
                              ? 'Pendiente cambio de contraseña'
                              : 'Contraseña personal activa',
                        ),
                      ),
                  ],
                ] else ...[
                  const SizedBox(height: 6),
                  const Text(
                    'Solo un usuario con rol Administrador puede dar de alta nuevas cuentas.',
                    style: TextStyle(fontSize: 13, color: AlkanColors.muted),
                  ),
                ],
                const SizedBox(height: 24),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
