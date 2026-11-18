import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../theme/alkan_theme.dart';

/// Pantalla 5 — Mi Empresa y Precios (Logo, Licencia WA, UBI, Markups y Cotizaciones).
class MiEmpresaPreciosScreen extends StatefulWidget {
  final BidKitApiClient api;

  const MiEmpresaPreciosScreen({super.key, required this.api});

  @override
  State<MiEmpresaPreciosScreen> createState() => _MiEmpresaPreciosScreenState();
}

class _MiEmpresaPreciosScreenState extends State<MiEmpresaPreciosScreen> {
  List<ContractorProfileItem> _profiles = [];
  String? _selectedName;
  Map<String, dynamic>? _rawProfile;
  List<int>? _pendingLogoBytes;

  final _nameCtrl = TextEditingController();
  final _licenseCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _addressCtrl = TextEditingController();
  final _contactCtrl = TextEditingController();
  final _contingencyCtrl = TextEditingController();
  final _overheadCtrl = TextEditingController();
  final _profitCtrl = TextEditingController();
  final _shopRateCtrl = TextEditingController();
  final _adminRateCtrl = TextEditingController();
  final _supplierCtrl = TextEditingController(text: 'Farwest Steel');

  bool _loading = true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _loadProfiles();
  }

  Future<void> _loadProfiles() async {
    setState(() => _loading = true);
    try {
      final list = await widget.api.fetchProfiles();
      if (!mounted) return;
      _profiles = list;
      if (list.isNotEmpty) {
        final target = _selectedName ?? list.first.name;
        await _selectProfile(target);
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _selectProfile(String name) async {
    final detail = await widget.api.fetchProfileDetail(name);
    final prof = Map<String, dynamic>.from(detail['profile'] as Map);
    final c = Map<String, dynamic>.from((prof['contractor'] as Map?) ?? {});
    final mk = Map<String, dynamic>.from((prof['markups'] as Map?) ?? {});
    final lr = Map<String, dynamic>.from((prof['labor_rates'] as Map?) ?? {});
    if (!mounted) return;
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
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mi Empresa y Precios')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                DropdownButtonFormField<String>(
                  value: _selectedName,
                  decoration: const InputDecoration(labelText: 'Perfil Activo'),
                  items: _profiles
                      .map((p) => DropdownMenuItem(value: p.name, child: Text(p.contractor)))
                      .toList(),
                  onChanged: (v) {
                    if (v != null) _selectProfile(v);
                  },
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
                const Text('Tarifas por Defecto ($/hr) y Markups (%)', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900)),
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
                const SizedBox(height: 24),
              ],
            ),
    );
  }
}
