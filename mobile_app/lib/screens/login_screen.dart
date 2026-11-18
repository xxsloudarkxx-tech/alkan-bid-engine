import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_loading_logo.dart';

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
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
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

  Future<AuthSession?> _promptPasswordChange({
    required String baseUrl,
    required String username,
    required String currentPassword,
    required bool mandatory,
  }) async {
    final userFieldCtrl = TextEditingController(text: username);
    final curPassCtrl = TextEditingController(text: currentPassword);
    final newPassCtrl = TextEditingController();
    final confirmCtrl = TextEditingController();
    String? modalError;
    bool saving = false;

    final updatedSession = await showDialog<AuthSession>(
      context: context,
      barrierDismissible: !mandatory,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) => PopScope(
          canPop: !mandatory,
          child: AlertDialog(
            title: Text(
              mandatory ? 'Cambio de Contraseña Obligatorio' : 'Cambiar Contraseña',
              style: const TextStyle(fontWeight: FontWeight.w900),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    mandatory
                        ? 'Tu cuenta tiene una contraseña temporal. Asigna una contraseña personal de al menos 8 caracteres para continuar.'
                        : 'Actualiza tu contraseña de acceso en ALKAN Bid Engine (mínimo 8 caracteres).',
                    style: const TextStyle(fontSize: 13.5),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: userFieldCtrl,
                    readOnly: mandatory && username.isNotEmpty,
                    decoration: const InputDecoration(labelText: 'Usuario'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: curPassCtrl,
                    readOnly: mandatory && currentPassword.isNotEmpty,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: 'Contraseña actual'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: newPassCtrl,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: 'Nueva contraseña (mín. 8 caracteres)'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: confirmCtrl,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: 'Confirmar nueva contraseña'),
                  ),
                  if (modalError != null) ...[
                    const SizedBox(height: 10),
                    Text(
                      modalError!,
                      style: const TextStyle(color: AlkanColors.noGo, fontWeight: FontWeight.w700, fontSize: 13),
                    ),
                  ],
                ],
              ),
            ),
            actions: [
              if (!mandatory)
                TextButton(
                  onPressed: saving ? null : () => Navigator.pop(ctx),
                  child: const Text('Cancelar'),
                ),
              ElevatedButton(
                onPressed: saving
                    ? null
                    : () async {
                        final u = userFieldCtrl.text.trim();
                        final c = curPassCtrl.text;
                        final n1 = newPassCtrl.text;
                        final n2 = confirmCtrl.text;
                        if (u.isEmpty || c.isEmpty) {
                          setModalState(() => modalError = 'Ingresa usuario y contraseña actual.');
                          return;
                        }
                        if (n1.length < 8) {
                          setModalState(() => modalError = 'La nueva contraseña debe tener al menos 8 caracteres.');
                          return;
                        }
                        if (n1 != n2) {
                          setModalState(() => modalError = 'Las contraseñas nuevas no coinciden.');
                          return;
                        }
                        if (n1 == c) {
                          setModalState(() => modalError = 'La nueva contraseña debe ser diferente de la actual.');
                          return;
                        }
                        setModalState(() {
                          saving = true;
                          modalError = null;
                        });
                        try {
                          final rotated = await widget.api.changePassword(
                            baseUrl: baseUrl,
                            username: u,
                            currentPassword: c,
                            newPassword: n1,
                          );
                          if (ctx.mounted) Navigator.pop(ctx, rotated);
                        } catch (e) {
                          setModalState(() {
                            saving = false;
                            modalError = e.toString();
                          });
                        }
                      },
                child: Text(saving ? 'Guardando...' : 'ACTUALIZAR CONTRASEÑA'),
              ),
            ],
          ),
        ),
      ),
    );
    return updatedSession;
  }

  Future<void> _submit() async {
    final user = _userCtrl.text.trim();
    final pass = _passCtrl.text;
    if (user.isEmpty || pass.isEmpty) {
      setState(() => _error = 'Ingresa usuario y contraseña.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      AuthSession session;
      try {
        session = await widget.api.login(
          baseUrl: _urlCtrl.text,
          username: user,
          password: pass,
        );
      } on ApiException catch (e) {
        if (e.statusCode == 401) {
          session = await widget.api.bootstrapAuth(
            baseUrl: _urlCtrl.text,
            username: user,
            password: pass,
          );
        } else {
          rethrow;
        }
      }
      if (!mounted) return;
      if (session.mustChangePassword) {
        setState(() => _loading = false);
        final updated = await _promptPasswordChange(
          baseUrl: _urlCtrl.text,
          username: user,
          currentPassword: pass,
          mandatory: true,
        );
        if (updated == null) return;
        session = updated;
      }
      await widget.store.saveSession(session);
      widget.onAuthenticated(session);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
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
                  color: const Color(0xFF041428),
                  borderRadius: BorderRadius.circular(18),
                ),
                child: const Row(
                  children: [
                    AlkanLogoBadge(size: 96),
                    SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'ALKAN BID ENGINE',
                            style: TextStyle(color: Colors.white, fontSize: 21, fontWeight: FontWeight.w900),
                          ),
                          SizedBox(height: 6),
                          Text(
                            'Estimación en obra · Washington\nControl Humano (DRAFT hasta autorización)',
                            style: TextStyle(color: Colors.white70, fontSize: 13.5, height: 1.35),
                          ),
                        ],
                      ),
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
              if (_loading)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: AlkanLoadingAnimation(size: 76, label: 'Conectando con ALKAN...'),
                  ),
                )
              else
                ElevatedButton.icon(
                  onPressed: _submit,
                  icon: const Icon(Icons.login, size: 24),
                  label: const Text('ENTRAR A BID ENGINE'),
                ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _loading
                    ? null
                    : () async {
                        final updated = await _promptPasswordChange(
                          baseUrl: _urlCtrl.text,
                          username: _userCtrl.text.trim(),
                          currentPassword: _passCtrl.text,
                          mandatory: false,
                        );
                        if (updated != null && mounted) {
                          await widget.store.saveSession(updated);
                          widget.onAuthenticated(updated);
                        }
                      },
                icon: const Icon(Icons.vpn_key_outlined),
                label: const Text('🔑 Cambiar mi contraseña'),
              ),
              const SizedBox(height: 10),
              TextButton.icon(
                onPressed: _loading
                    ? null
                    : () {
                        widget.onAuthenticated(
                          AuthSession(
                            baseUrl: _urlCtrl.text.trim(),
                            token: 'offline_local',
                            actor: _userCtrl.text.trim().isEmpty ? 'contratista_offline' : _userCtrl.text.trim(),
                            role: 'estimator',
                            orgId: 'default',
                          ),
                        );
                      },
                icon: const Icon(Icons.cloud_off),
                label: const Text('Trabajar sin señal (Modo Obra Offline)'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
