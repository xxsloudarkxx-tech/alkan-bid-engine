import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/bid_models.dart';

/// Persistencia local para sesión, cola offline de estimados y PDFs descargados.
class OfflineStore {
  static const _kSession = 'alkan_auth_session';
  static const _kRunsCache = 'alkan_runs_cache';
  static const _kPendingDrafts = 'alkan_pending_drafts';
  static const _kServerUrl = 'alkan_server_url';
  static const _kProfilesCache = 'alkan_profiles_cache';
  static const _kProfileDetailPrefix = 'alkan_profile_detail_';
  static const _kCoachDismissedPrefix = 'alkan_coach_done_';
  static const _kWizardDraft = 'alkan_wizard_draft_v1';

  Future<bool> isCoachDismissed(int step) async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool('$_kCoachDismissedPrefix$step') ?? false;
  }

  Future<void> dismissCoach(int step) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('$_kCoachDismissedPrefix$step', true);
  }

  Future<void> saveCachedProfiles(List<ContractorProfileItem> profiles) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = profiles
        .map((p) => {
              'name': p.name,
              'label': p.label,
              'contractor': p.contractor,
              'generic': p.generic,
              'has_logo': p.hasLogo,
              'trade': p.trade,
              'markups': p.markups,
            })
        .toList();
    await prefs.setString(_kProfilesCache, jsonEncode(raw));
  }

  Future<List<ContractorProfileItem>> loadCachedProfiles() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kProfilesCache);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list.map((e) => ContractorProfileItem.fromJson(Map<String, dynamic>.from(e as Map))).toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> saveCachedProfileDetail(String name, Map<String, dynamic> detail) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('$_kProfileDetailPrefix$name', jsonEncode(detail));
  }

  Future<Map<String, dynamic>?> loadCachedProfileDetail(String name) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('$_kProfileDetailPrefix$name');
    if (raw == null || raw.isEmpty) return null;
    try {
      return Map<String, dynamic>.from(jsonDecode(raw) as Map);
    } catch (_) {
      return null;
    }
  }

  Future<void> saveWizardDraft(Map<String, dynamic> draft) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kWizardDraft, jsonEncode(draft));
  }

  Future<Map<String, dynamic>?> loadWizardDraft() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kWizardDraft);
    if (raw == null || raw.isEmpty) return null;
    try {
      return Map<String, dynamic>.from(jsonDecode(raw) as Map);
    } catch (_) {
      return null;
    }
  }

  Future<void> clearWizardDraft() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kWizardDraft);
  }

  Future<String> loadServerUrl({String fallback = 'http://10.0.2.2:8000'}) async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kServerUrl) ?? fallback;
  }

  Future<void> saveServerUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kServerUrl, url.trim());
  }

  Future<AuthSession?> loadSession() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kSession);
    if (raw == null || raw.isEmpty) return null;
    try {
      return AuthSession.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<void> saveSession(AuthSession session) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kSession, jsonEncode(session.toJson()));
    await prefs.setString(_kServerUrl, session.baseUrl);
  }

  Future<void> clearSession() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kSession);
  }

  Future<List<EstimateRunCard>> loadCachedRuns() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kRunsCache);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list.map((e) => EstimateRunCard.fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> saveCachedRuns(List<EstimateRunCard> runs) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kRunsCache, jsonEncode(runs.map((r) => r.toJson()).toList()));
  }

  Future<List<PendingOfflineEstimate>> loadPendingDrafts() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kPendingDrafts);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list.map((e) => PendingOfflineEstimate.fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> addPendingDraft(PendingOfflineEstimate draft) async {
    final current = await loadPendingDrafts();
    current.add(draft);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kPendingDrafts, jsonEncode(current.map((e) => e.toJson()).toList()));
  }

  Future<void> removePendingDraft(String localId) async {
    final current = await loadPendingDrafts();
    current.removeWhere((d) => d.localId == localId);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kPendingDrafts, jsonEncode(current.map((e) => e.toJson()).toList()));
  }

  /// Guarda una copia local de los PDFs generados para abrirlos sin conexión en obra.
  Future<File> saveLocalPdf(String runId, String filename, List<int> bytes) async {
    final base = await getApplicationDocumentsDirectory();
    final dir = Directory('${base.path}/alkan_pdfs/$runId');
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    final file = File('${dir.path}/$filename');
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }

  Future<File?> getCachedPdf(String runId, String filename) async {
    final base = await getApplicationDocumentsDirectory();
    final file = File('${base.path}/alkan_pdfs/$runId/$filename');
    return await file.exists() ? file : null;
  }
}
