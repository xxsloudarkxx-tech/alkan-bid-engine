import 'package:flutter/material.dart';

import 'models/bid_models.dart';
import 'screens/login_screen.dart';
import 'screens/mis_estimados_screen.dart';
import 'services/bidkit_api_client.dart';
import 'services/offline_store.dart';
import 'theme/alkan_theme.dart';
import 'widgets/alkan_loading_logo.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AlkanBidEngineApp());
}

class AlkanBidEngineApp extends StatefulWidget {
  const AlkanBidEngineApp({super.key});

  @override
  State<AlkanBidEngineApp> createState() => _AlkanBidEngineAppState();
}

class _AlkanBidEngineAppState extends State<AlkanBidEngineApp> {
  final _api = BidKitApiClient();
  final _store = OfflineStore();
  AuthSession? _session;
  bool _booting = true;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final saved = await _store.loadSession();
    if (saved != null && saved.isValid) {
      _api.setSession(saved);
    }
    if (mounted) {
      setState(() {
        _session = (saved != null && saved.isValid) ? saved : null;
        _booting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ALKAN Bid Engine',
      debugShowCheckedModeBanner: false,
      theme: buildAlkanTheme(),
      home: _booting
          ? const Scaffold(
              backgroundColor: Color(0xFF041428),
              body: Center(
                child: AlkanLoadingAnimation(
                  size: 160,
                  label: 'Iniciando ALKAN Bid Engine...',
                  textColor: Colors.white,
                ),
              ),
            )
          : _session == null
              ? LoginScreen(
                  api: _api,
                  store: _store,
                  onAuthenticated: (s) {
                    _api.setSession(s);
                    setState(() => _session = s);
                  },
                )
              : MisEstimadosScreen(
                  api: _api,
                  store: _store,
                  onLogout: () async {
                    await _store.clearSession();
                    _api.setSession(null);
                    setState(() => _session = null);
                  },
                ),
    );
  }
}
