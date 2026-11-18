import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';

/// Acceso rápido para contratistas y revisores en campo.
class LoginScreen extends StatefulWidget {
  final BidKitApiClient api;
  final OfflineStore store;
  final void Function(AuthSession session) onAuthenticated;

  const LoginScreen({
    super.key,
    required this.api,
    required this.store,
    required this.onAuthenticated,
  });

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  static const _railwayUrl = 'https://bidengine-mobile-api-production.up.railway.app';
  static const _emulatorLocalUrl = 'http://10.0.2.2:8000';

  final _urlCtrl = TextEditingController(text: _railwayUrl);
  final _userCtrl = TextEditingController(text: 'estimator');
  final _passCtrl = TextEditingController(text: 'Estimator!2026');
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadSavedUrl();
  }

  Future<void> _loadSavedUrl() async {
    final saved = await widget.store.loadServerUrl(fallback: _railwayUrl);
    if (mounted) setState(() => _urlCtrl.text = saved);
  }

  Future<void> _submit({bool bootstrap = true}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final session = bootstrap
          ? await widget.api.bootstrapAuth(
              baseUrl: _urlCtrl.text,
              username: _userCtrl.text,
              password: _passCtrl.text,
            )
          : await widget.api.login(
              baseUrl: _urlCtrl.text,
              username: _userCtrl.text,
              password: _passCtrl.text,
            );
      await widget.store.saveSession(session);
      widget.onAuthenticated(session);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _urlCtrl.dispose();
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 20),
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: AlkanColors.primary,
                  borderRadius: BorderRadius.circular(18),
                ),
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'ALKAN BID ENGINE',
                      style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w900),
                    ),
                    SizedBox(height: 6),
                    Text(
                      'Estimación Profesional · Estado de Washington\nControl Humano Obligatorio (DRAFT hasta autorización)',
                      style: TextStyle(color: Colors.white70, fontSize: 14, height: 1.35),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              TextField(
                controller: _urlCtrl,
                decoration: const InputDecoration(
                  labelText: 'Servidor API (Railway / Local)',
                  hintText: 'https://bidengine-mobile-api-production.up.railway.app',
                ),
                keyboardType: TextInputType.url,
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  ActionChip(
                    avatar: const Icon(Icons.cloud, size: 18),
                    label: const Text('Railway Cloud'),
                    onPressed: _loading ? null : () => setState(() => _urlCtrl.text = _railwayUrl),
                  ),
                  ActionChip(
                    avatar: const Icon(Icons.phone_android, size: 18),
                    label: const Text('Emulador Local (10.0.2.2)'),
                    onPressed: _loading ? null : () => setState(() => _urlCtrl.text = _emulatorLocalUrl),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              TextField(
                controller: _userCtrl,
                decoration: const InputDecoration(labelText: 'Usuario'),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: _passCtrl,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Contraseña'),
              ),
              if (_error != null) ...[
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AlkanColors.noGo),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: AlkanColors.noGo, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
              const SizedBox(height: 20),
              ElevatedButton.icon(
                onPressed: _loading ? null : () => _submit(bootstrap: true),
                icon: _loading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                      )
                    : const Icon(Icons.login, size: 24),
                label: Text(_loading ? 'CONECTANDO...' : 'ENTRAR A BID ENGINE'),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _loading
                          ? null
                          : () {
                              _userCtrl.text = 'estimator';
                              _passCtrl.text = 'Estimator!2026';
                            },
                      child: const Text('Rol: Estimador'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _loading
                          ? null
                          : () {
                              _userCtrl.text = 'reviewer';
                              _passCtrl.text = 'Reviewer!2026';
                            },
                      child: const Text('Rol: Aprobador'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
