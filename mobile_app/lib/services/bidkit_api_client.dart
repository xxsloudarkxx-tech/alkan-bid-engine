import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../models/bid_models.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;

  ApiException(this.statusCode, this.message);

  @override
  String toString() => message;
}

/// Cliente REST para ALKAN Bid Engine Mobile API (HTTPS + Bearer Token + chunks reanudables).
class BidKitApiClient {
  static const MethodChannel _shareChannel = MethodChannel('com.alkan.bidengine/share_intent');

  AuthSession? _session;
  final http.Client _http = http.Client();

  AuthSession? get session => _session;

  void setSession(AuthSession? session) {
    _session = session;
  }

  /// Lee archivos compartidos desde WhatsApp o Archivos al abrir la app.
  Future<List<String>> consumeSharedFiles() async {
    try {
      final list = await _shareChannel.invokeMethod<List<dynamic>>('consumeSharedFiles');
      return (list ?? const []).map((e) => e.toString()).toList();
    } catch (_) {
      return const [];
    }
  }

  String _cleanBase(String url) => url.trim().replaceAll(RegExp(r'/+$'), '');

  Map<String, String> _headers({bool authenticated = true, String? overrideToken}) {
    final hdrs = <String, String>{'Content-Type': 'application/json'};
    final tok = overrideToken ?? _session?.token ?? '';
    if (authenticated && tok.isNotEmpty) {
      hdrs['Authorization'] = 'Bearer $tok';
    }
    return hdrs;
  }

  dynamic _decodeJson(http.Response res) {
    final text = utf8.decode(res.bodyBytes);
    final data = text.isNotEmpty ? jsonDecode(text) : <String, dynamic>{};
    if (res.statusCode >= 400) {
      final msg = data is Map && data['error'] != null
          ? data['error'].toString()
          : 'Error del servidor (${res.statusCode})';
      throw ApiException(res.statusCode, msg);
    }
    return data;
  }

  Future<Map<String, dynamic>> fetchHealth(String baseUrl) async {
    final uri = Uri.parse('${_cleanBase(baseUrl)}/api/mobile/health');
    final res = await _http.get(uri).timeout(const Duration(seconds: 8));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  Future<AuthSession> bootstrapAuth({
    required String baseUrl,
    required String username,
    required String password,
  }) async {
    final clean = _cleanBase(baseUrl);
    final uri = Uri.parse('$clean/api/mobile/auth/bootstrap');
    final res = await _http
        .post(
          uri,
          headers: _headers(authenticated: false),
          body: jsonEncode({'username': username, 'password': password}),
        )
        .timeout(const Duration(seconds: 12));
    final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
    final session = AuthSession(
      baseUrl: clean,
      token: (data['token'] ?? '').toString(),
      actor: (data['actor'] ?? username).toString(),
      role: (data['role'] ?? 'estimator').toString(),
      orgId: (data['org_id'] ?? 'default').toString(),
      mustChangePassword: data['must_change_password'] == true,
    );
    _session = session;
    return session;
  }

  Future<AuthSession> login({
    required String baseUrl,
    required String username,
    required String password,
  }) async {
    final clean = _cleanBase(baseUrl);
    final uri = Uri.parse('$clean/api/v4/auth/login');
    final res = await _http
        .post(
          uri,
          headers: _headers(authenticated: false),
          body: jsonEncode({'username': username, 'password': password}),
        )
        .timeout(const Duration(seconds: 12));
    final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
    final session = AuthSession(
      baseUrl: clean,
      token: (data['token'] ?? '').toString(),
      actor: (data['actor'] ?? username).toString(),
      role: (data['role'] ?? 'estimator').toString(),
      orgId: (data['org_id'] ?? 'default').toString(),
      mustChangePassword: data['must_change_password'] == true,
    );
    _session = session;
    return session;
  }

  Future<AuthSession> changePassword({
    required String baseUrl,
    required String username,
    required String currentPassword,
    required String newPassword,
  }) async {
    final clean = _cleanBase(baseUrl);
    final uri = Uri.parse('$clean/api/mobile/auth/change-password');
    final res = await _http
        .post(
          uri,
          headers: _headers(authenticated: false),
          body: jsonEncode({
            'username': username,
            'current_password': currentPassword,
            'new_password': newPassword,
          }),
        )
        .timeout(const Duration(seconds: 12));
    final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
    final session = AuthSession(
      baseUrl: clean,
      token: (data['token'] ?? '').toString(),
      actor: (data['actor'] ?? username).toString(),
      role: (data['role'] ?? 'estimator').toString(),
      orgId: (data['org_id'] ?? 'default').toString(),
      mustChangePassword: false,
    );
    _session = session;
    return session;
  }

  Future<List<Map<String, dynamic>>> fetchUsers() async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/auth/users');
    final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
    final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
    return (data['users'] as List<dynamic>? ?? const [])
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  Future<Map<String, dynamic>> createUser({
    required String username,
    required String password,
    required String userRole,
    bool mustChangePassword = true,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/auth/users');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({
            'username': username,
            'password': password,
            'user_role': userRole,
            'must_change_password': mustChangePassword,
          }),
        )
        .timeout(const Duration(seconds: 12));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  Future<List<ContractorProfileItem>> fetchProfiles() async {
    final s = _requireSession();
    try {
      final uri = Uri.parse('${s.baseUrl}/api/mobile/profiles');
      final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
      final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
      return (data['profiles'] as List<dynamic>? ?? const [])
          .map((e) => ContractorProfileItem.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (_) {
      final uri = Uri.parse('${s.baseUrl}/api/app/profiles');
      final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
      final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
      return (data['profiles'] as List<dynamic>? ?? const [])
          .map((e) => ContractorProfileItem.fromJson(e as Map<String, dynamic>))
          .toList();
    }
  }

  Future<ProfileCalibration> fetchCalibration(String profileName) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/calibration?profile=${Uri.encodeQueryComponent(profileName)}');
    final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
    return ProfileCalibration.fromJson(Map<String, dynamic>.from(_decodeJson(res) as Map));
  }

  Future<Map<String, dynamic>> fetchProfileDetail(String name) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/app/profile?name=${Uri.encodeQueryComponent(name)}');
    final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  Future<Map<String, dynamic>> saveProfile({
    required String name,
    required Map<String, dynamic> profile,
    List<int>? logoBytes,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/app/profile/save');
    final body = <String, dynamic>{'name': name, 'profile': profile};
    if (logoBytes != null && logoBytes.isNotEmpty) {
      body['logo'] = {'content': base64Encode(logoBytes)};
    }
    final res = await _http
        .post(uri, headers: _headers(), body: jsonEncode(body))
        .timeout(const Duration(seconds: 20));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  Future<Map<String, dynamic>> registerQuickProfile({
    required String contractorName,
    String contact = '',
    String phone = '',
    String address = '',
    String license = '',
    String specialty = '',
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/profiles/register');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({
            'contractor_name': contractorName,
            if (contact.isNotEmpty) 'contact': contact,
            if (phone.isNotEmpty) 'phone': phone,
            if (address.isNotEmpty) 'address': address,
            if (license.isNotEmpty) 'license': license,
            if (specialty.isNotEmpty) 'specialty': specialty,
          }),
        )
        .timeout(const Duration(seconds: 20));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  String profileLogoUrl(String profileName) {
    final s = _requireSession();
    return '${s.baseUrl}/api/mobile/profiles/${Uri.encodeComponent(profileName)}/logo';
  }

  Map<String, String> authHeaders() => _headers();

  Future<List<EstimateRunCard>> fetchRuns() async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/runs');
    final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
    final data = Map<String, dynamic>.from(_decodeJson(res) as Map);
    return (data['runs'] as List<dynamic>? ?? const [])
        .map((e) => EstimateRunCard.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Genera un upload_id hexadecimal válido para el backend (32 hex chars).
  String newUploadId() {
    final rnd = Random.secure();
    return List.generate(16, (_) => rnd.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }

  /// Sube un archivo grande en bloques de 768 KB con reanudación automática.
  Future<void> uploadChunkedFile({
    required String uploadId,
    required File file,
    void Function(double fraction)? onProgress,
  }) async {
    final s = _requireSession();
    final filename = file.uri.pathSegments.isNotEmpty ? file.uri.pathSegments.last : 'plano.pdf';
    const chunkSize = 768 * 1024;
    final totalBytes = await file.length();
    final totalChunks = max(1, (totalBytes / chunkSize).ceil());

    // Consultar qué bloques ya recibió el servidor para reanudar sin repetir trabajo.
    int startIndex = 0;
    try {
      final stUri = Uri.parse('${s.baseUrl}/api/mobile/upload/status?upload_id=$uploadId');
      final stRes = await _http.get(stUri, headers: _headers()).timeout(const Duration(seconds: 8));
      final stData = Map<String, dynamic>.from(_decodeJson(stRes) as Map);
      for (final f in (stData['files'] as List<dynamic>? ?? const [])) {
        final m = f as Map<String, dynamic>;
        if ((m['name'] ?? '') == filename) {
          startIndex = (m['next_index'] as num? ?? 0).toInt();
        }
      }
    } catch (_) {
      startIndex = 0;
    }

    final raf = await file.open();
    try {
      for (int idx = startIndex; idx < totalChunks; idx++) {
        await raf.setPosition(idx * chunkSize);
        final bytes = await raf.read(chunkSize);
        final isLast = idx == totalChunks - 1;
        final uri = Uri.parse('${s.baseUrl}/api/mobile/upload/chunk');
        final res = await _http
            .post(
              uri,
              headers: _headers(),
              body: jsonEncode({
                'upload_id': uploadId,
                'name': filename,
                'index': idx,
                'content': base64Encode(bytes),
                'is_last': isLast,
              }),
            )
            .timeout(const Duration(seconds: 45));
        _decodeJson(res);
        onProgress?.call((idx + 1) / totalChunks);
      }
    } finally {
      await raf.close();
    }
  }

  Future<Map<String, dynamic>> startAgentRun({
    required String key,
    required String profile,
    required String tradeScope,
    required String uploadId,
    required String notes,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/app/run/start');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({
            'spec': {
              'key': key,
              'profile': profile,
              'trade_scope': tradeScope,
              'upload_id': uploadId,
              'notes': notes,
            }
          }),
        )
        .timeout(const Duration(seconds: 20));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  Future<DraftPreview> previewDraft({
    required String key,
    required String projectTitle,
    required String profile,
    required List<String> specialties,
    required String county,
    required String voiceNotes,
    String? uploadId,
    String? clientName,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/runs/preview-draft');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({
            'key': key,
            'project_title': projectTitle,
            'profile': profile,
            'specialty': specialties.isNotEmpty ? specialties.first : 'metal',
            'specialties': specialties,
            'county': county,
            'voice_notes': voiceNotes,
            if (uploadId != null && uploadId.isNotEmpty) 'upload_id': uploadId,
            if (clientName != null && clientName.isNotEmpty) 'client_name': clientName,
          }),
        )
        .timeout(const Duration(seconds: 25));
    return DraftPreview.fromJson(Map<String, dynamic>.from(_decodeJson(res) as Map));
  }

  Future<RunExecutiveSummary> startQuickPackage({
    required String key,
    required String projectTitle,
    required String profile,
    required String specialty,
    List<String> specialties = const [],
    required String county,
    required String voiceNotes,
    String? uploadId,
    String? clientName,
    List<Map<String, dynamic>> materialsOverrides = const [],
    List<Map<String, dynamic>> laborOverrides = const [],
    Map<String, dynamic> markups = const {},
    int? validityDays,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/runs/quick-package');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({
            'key': key,
            'project_title': projectTitle,
            'profile': profile,
            'specialty': specialty,
            if (specialties.isNotEmpty) 'specialties': specialties,
            'county': county,
            'voice_notes': voiceNotes,
            if (uploadId != null && uploadId.isNotEmpty) 'upload_id': uploadId,
            if (clientName != null && clientName.isNotEmpty) 'client_name': clientName,
            if (materialsOverrides.isNotEmpty) 'materials_overrides': materialsOverrides,
            if (laborOverrides.isNotEmpty) 'labor_overrides': laborOverrides,
            if (markups.isNotEmpty) 'markups': markups,
            if (validityDays != null) 'validity_days': validityDays,
          }),
        )
        .timeout(const Duration(seconds: 45));
    return RunExecutiveSummary.fromJson(Map<String, dynamic>.from(_decodeJson(res) as Map));
  }

  Future<RunExecutiveSummary> fetchRunSummary(String runId) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/runs/${Uri.encodeComponent(runId)}/summary');
    final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));
    return RunExecutiveSummary.fromJson(Map<String, dynamic>.from(_decodeJson(res) as Map));
  }

  Future<List<int>> downloadRunFile(String runId, String filename) async {
    final s = _requireSession();
    final uri = Uri.parse(
      '${s.baseUrl}/api/app/run/file?id=${Uri.encodeQueryComponent(runId)}&name=${Uri.encodeQueryComponent(filename)}',
    );
    final res = await _http.get(uri, headers: _headers()).timeout(const Duration(seconds: 45));
    if (res.statusCode >= 400) {
      throw ApiException(res.statusCode, 'No se pudo descargar $filename (${res.statusCode})');
    }
    return res.bodyBytes;
  }

  Future<void> recordVoiceNote({
    required String runId,
    required String transcript,
    String kind = 'adjustment_request',
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/runs/${Uri.encodeComponent(runId)}/voice-note');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({'transcript': transcript, 'kind': kind}),
        )
        .timeout(const Duration(seconds: 12));
    _decodeJson(res);
  }

  /// Aprobación humana independiente. Si el usuario actual creó el estimado, puede enviar credenciales de revisor.
  Future<void> approveRun({
    required String runId,
    String note = '',
    String? reviewerToken,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/v4/bids/approve');
    final res = await _http
        .post(
          uri,
          headers: _headers(overrideToken: reviewerToken),
          body: jsonEncode({'run_id': runId, 'note': note, 'org_id': s.orgId}),
        )
        .timeout(const Duration(seconds: 25));
    _decodeJson(res);
  }

  Future<void> rejectRun({
    required String runId,
    required String reason,
    String? reviewerToken,
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/v4/bids/reject');
    final res = await _http
        .post(
          uri,
          headers: _headers(overrideToken: reviewerToken),
          body: jsonEncode({'run_id': runId, 'reason': reason, 'org_id': s.orgId}),
        )
        .timeout(const Duration(seconds: 15));
    _decodeJson(res);
  }

  Future<Map<String, dynamic>> importSupplierQuote({
    required String fileName,
    required List<int> bytes,
    required String supplier,
    String city = '',
  }) async {
    final s = _requireSession();
    final uri = Uri.parse('${s.baseUrl}/api/mobile/pricebook/import-file');
    final res = await _http
        .post(
          uri,
          headers: _headers(),
          body: jsonEncode({
            'file_name': fileName,
            'content_b64': base64Encode(bytes),
            'supplier': supplier,
            'city': city,
            'state': 'WA',
          }),
        )
        .timeout(const Duration(seconds: 30));
    return Map<String, dynamic>.from(_decodeJson(res) as Map);
  }

  AuthSession _requireSession() {
    final s = _session;
    if (s == null || !s.isValid) {
      throw ApiException(401, 'Sesión no iniciada');
    }
    return s;
  }
}
