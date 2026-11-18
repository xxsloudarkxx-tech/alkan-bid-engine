import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../services/bidkit_api_client.dart';
import '../services/offline_store.dart';
import '../theme/alkan_theme.dart';
import '../widgets/alkan_loading_logo.dart';

/// Login ALKAN Blue Experience — animación del logo real + auth segura + rotación de contraseña.
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

class _LoginScreenState extends State<LoginScreen> with TickerProviderStateMixin {
  static const _railwayUrl = 'https://bidengine-mobile-api-production.up.railway.app';
  static const _emulatorLocalUrl = 'http://10.0.2.2:8000';

  final _urlCtrl = TextEditingController(text: _railwayUrl);
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();

  late final AnimationController _introCtrl;
  late final AnimationController _shimmerCtrl;
  late final Animation<double> _logoFade;
  late final Animation<double> _logoScale;
  late final Animation<double> _formFade;
  late final Animation<Offset> _formSlide;

  bool _obscurePassword = true;
  bool _showServerOptions = false;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _introCtrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));
    _shimmerCtrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 2200));

    _logoFade = CurvedAnimation(parent: _introCtrl, curve: const Interval(0.0, 0.45, curve: Curves.easeOut));
    _logoScale = Tween<double>(begin: 0.88, end: 1.0).animate(
      CurvedAnimation(parent: _introCtrl, curve: const Interval(0.0, 0.5, curve: Curves.easeOutBack)),
    );
    _formFade = CurvedAnimation(parent: _introCtrl, curve: const Interval(0.35, 1.0, curve: Curves.easeOut));
    _formSlide = Tween<Offset>(begin: const Offset(0, 0.06), end: Offset.zero).animate(
      CurvedAnimation(parent: _introCtrl, curve: const Interval(0.35, 1.0, curve: Curves.easeOut)),
    );

    _loadSavedUrl();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final reduceMotion = MediaQuery.maybeOf(context)?.disableAnimations ?? false;
      if (reduceMotion) {
        _introCtrl.value = 1.0;
        _shimmerCtrl.value = 0.5;
      } else {
        _introCtrl.forward();
        _shimmerCtrl.forward();
      }
    });
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
              mandatory ? 'Cambio de Contraseña Obligatorio' : 'Cambiar / Recuperar Contraseña',
              style: const TextStyle(fontWeight: FontWeight.w900, color: AlkanColors.textPrimary),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    mandatory
                        ? 'Tu cuenta tiene una contraseña temporal. Asigna una contraseña personal de al menos 8 caracteres para continuar.'
                        : 'Actualiza tu contraseña de acceso en ALKAN BidEngine (mínimo 8 caracteres). Si olvidaste tu clave, solicita al administrador un restablecimiento temporal.',
                    style: const TextStyle(fontSize: 13.5, color: AlkanColors.textSecondary),
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
      setState(() => _error = 'Ingresa tu usuario y contraseña para continuar.');
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
    _introCtrl.dispose();
    _shimmerCtrl.dispose();
    _urlCtrl.dispose();
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  InputDecoration _darkLoginDecoration(String label, {String? hint, Widget? suffixIcon}) {
    return InputDecoration(
      labelText: label,
      hintText: hint,
      labelStyle: const TextStyle(color: Color(0xFFBFD8F8), fontWeight: FontWeight.w600),
      hintStyle: const TextStyle(color: Color(0xFF6B8CB8)),
      filled: true,
      fillColor: Colors.white.withOpacity(0.07),
      suffixIcon: suffixIcon,
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: AlkanColors.azulLuminoso.withOpacity(0.28), width: 1.3),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AlkanColors.azulLuminoso, width: 2.0),
      ),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AlkanColors.azulProfundo,
      body: Stack(
        children: [
          // Iluminación radial central sutil sobre ALKAN azul profundo
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: RadialGradient(
                  center: const Alignment(0, -0.42),
                  radius: 1.05,
                  colors: [
                    AlkanColors.azulElectrico.withOpacity(0.22),
                    AlkanColors.azulProfundo,
                  ],
                ),
              ),
            ),
          ),
          SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 460),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const SizedBox(height: 16),
                      // Logo animado con shimmer azul
                      FadeTransition(
                        opacity: _logoFade,
                        child: ScaleTransition(
                          scale: _logoScale,
                          child: Column(
                            children: [
                              AnimatedBuilder(
                                animation: _shimmerCtrl,
                                builder: (context, child) {
                                  final v = _shimmerCtrl.value;
                                  return ShaderMask(
                                    blendMode: BlendMode.srcATop,
                                    shaderCallback: (bounds) => LinearGradient(
                                      begin: Alignment(-1.4 + v * 2.8, -0.3),
                                      end: Alignment(-0.8 + v * 2.8, 0.3),
                                      colors: [
                                        Colors.transparent,
                                        AlkanColors.azulLuminoso.withOpacity(v < 0.99 ? 0.32 : 0.0),
                                        Colors.transparent,
                                      ],
                                    ).createShader(bounds),
                                    child: child,
                                  );
                                },
                                child: const AlkanLogoBadge(size: 104),
                              ),
                              const SizedBox(height: 16),
                              const Text(
                                'ALKAN',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 30,
                                  fontWeight: FontWeight.w900,
                                  letterSpacing: 3.0,
                                ),
                              ),
                              const SizedBox(height: 4),
                              const Text(
                                'BIDENGINE',
                                style: TextStyle(
                                  color: AlkanColors.azulLuminoso,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w800,
                                  letterSpacing: 4.5,
                                ),
                              ),
                              const SizedBox(height: 8),
                              const Text(
                                'Calibras una vez. Después, solo dictas.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Color(0xFFBFD8F8),
                                  fontSize: 13.5,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 30),

                      // Formulario integrado sobre el fondo azul profundo
                      FadeTransition(
                        opacity: _formFade,
                        child: SlideTransition(
                          position: _formSlide,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              TextField(
                                controller: _userCtrl,
                                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
                                textInputAction: TextInputAction.next,
                                decoration: _darkLoginDecoration('Usuario o correo', hint: 'ej. carlos_obra'),
                              ),
                              const SizedBox(height: 14),
                              TextField(
                                controller: _passCtrl,
                                obscureText: _obscurePassword,
                                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
                                textInputAction: TextInputAction.done,
                                onSubmitted: (_) => _loading ? null : _submit(),
                                decoration: _darkLoginDecoration(
                                  'Contraseña',
                                  suffixIcon: IconButton(
                                    tooltip: _obscurePassword ? 'Mostrar contraseña' : 'Ocultar contraseña',
                                    icon: Icon(
                                      _obscurePassword ? Icons.visibility_outlined : Icons.visibility_off_outlined,
                                      color: const Color(0xFFBFD8F8),
                                    ),
                                    onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                                  ),
                                ),
                              ),
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  TextButton.icon(
                                    style: TextButton.styleFrom(foregroundColor: const Color(0xFF93C5FD)),
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
                                    icon: const Icon(Icons.vpn_key_outlined, size: 17),
                                    label: const Text('Cambiar / recuperar clave', style: TextStyle(fontSize: 13)),
                                  ),
                                  const Spacer(),
                                  TextButton.icon(
                                    style: TextButton.styleFrom(foregroundColor: const Color(0xFF93C5FD)),
                                    onPressed: () => setState(() => _showServerOptions = !_showServerOptions),
                                    icon: const Icon(Icons.dns_outlined, size: 17),
                                    label: const Text('Servidor', style: TextStyle(fontSize: 13)),
                                  ),
                                ],
                              ),
                              if (_showServerOptions) ...[
                                const SizedBox(height: 8),
                                TextField(
                                  controller: _urlCtrl,
                                  style: const TextStyle(color: Colors.white, fontSize: 13.5),
                                  keyboardType: TextInputType.url,
                                  decoration: _darkLoginDecoration(
                                    'Servidor API',
                                    hint: _railwayUrl,
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Wrap(
                                  spacing: 8,
                                  children: [
                                    ActionChip(
                                      backgroundColor: Colors.white.withOpacity(0.1),
                                      side: BorderSide(color: AlkanColors.azulLuminoso.withOpacity(0.35)),
                                      avatar: const Icon(Icons.cloud_outlined, size: 17, color: AlkanColors.azulLuminoso),
                                      label: const Text('Railway Cloud', style: TextStyle(color: Colors.white)),
                                      onPressed: _loading ? null : () => setState(() => _urlCtrl.text = _railwayUrl),
                                    ),
                                    ActionChip(
                                      backgroundColor: Colors.white.withOpacity(0.1),
                                      side: BorderSide(color: AlkanColors.azulLuminoso.withOpacity(0.35)),
                                      avatar: const Icon(Icons.phone_android, size: 17, color: AlkanColors.azulLuminoso),
                                      label: const Text('Local (10.0.2.2)', style: TextStyle(color: Colors.white)),
                                      onPressed: _loading ? null : () => setState(() => _urlCtrl.text = _emulatorLocalUrl),
                                    ),
                                  ],
                                ),
                              ],
                              if (_error != null) ...[
                                const SizedBox(height: 12),
                                Container(
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                    color: AlkanColors.noGo.withOpacity(0.18),
                                    borderRadius: BorderRadius.circular(12),
                                    border: Border.all(color: const Color(0xFFFCA5A5)),
                                  ),
                                  child: Text(
                                    _error!,
                                    style: const TextStyle(color: Color(0xFFFEE2E2), fontWeight: FontWeight.w700),
                                  ),
                                ),
                              ],
                              const SizedBox(height: 18),
                              if (_loading)
                                const Center(
                                  child: Padding(
                                    padding: EdgeInsets.symmetric(vertical: 10),
                                    child: AlkanLoadingAnimation(
                                      size: 72,
                                      label: 'Autenticando en ALKAN...',
                                      textColor: Colors.white,
                                    ),
                                  ),
                                )
                              else
                                ElevatedButton.icon(
                                  onPressed: _submit,
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: AlkanColors.azulPrincipal,
                                    foregroundColor: Colors.white,
                                    minimumSize: const Size(double.infinity, 56),
                                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                                  ),
                                  icon: const Icon(Icons.login, size: 22),
                                  label: const Text('INICIAR SESIÓN', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
                                ),
                              const SizedBox(height: 12),
                              TextButton.icon(
                                style: TextButton.styleFrom(foregroundColor: const Color(0xFFBFD8F8)),
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
                                icon: const Icon(Icons.cloud_off, size: 19),
                                label: const Text('Trabajar sin señal (Modo Obra Offline)'),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
