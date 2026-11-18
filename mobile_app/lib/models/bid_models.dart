/// Modelos de datos para la app móvil ALKAN Bid Engine.

class AuthSession {
  final String baseUrl;
  final String token;
  final String actor;
  final String role;
  final String orgId;
  final bool mustChangePassword;

  const AuthSession({
    required this.baseUrl,
    required this.token,
    required this.actor,
    required this.role,
    required this.orgId,
    this.mustChangePassword = false,
  });

  bool get isValid => token.isNotEmpty && baseUrl.isNotEmpty;

  Map<String, dynamic> toJson() => {
        'baseUrl': baseUrl,
        'token': token,
        'actor': actor,
        'role': role,
        'orgId': orgId,
        'mustChangePassword': mustChangePassword,
      };

  factory AuthSession.fromJson(Map<String, dynamic> json) => AuthSession(
        baseUrl: (json['baseUrl'] ?? '').toString(),
        token: (json['token'] ?? '').toString(),
        actor: (json['actor'] ?? '').toString(),
        role: (json['role'] ?? 'estimator').toString(),
        orgId: (json['orgId'] ?? 'default').toString(),
        mustChangePassword: json['mustChangePassword'] == true || json['must_change_password'] == true,
      );
}

class SpecialtyOption {
  final String id;
  final String label;
  final String tradeScope;
  final String defaultProfile;
  final List<String> suppliers;

  const SpecialtyOption({
    required this.id,
    required this.label,
    required this.tradeScope,
    required this.defaultProfile,
    required this.suppliers,
  });

  factory SpecialtyOption.fromJson(Map<String, dynamic> json) => SpecialtyOption(
        id: (json['id'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        tradeScope: (json['trade_scope'] ?? '').toString(),
        defaultProfile: (json['default_profile'] ?? '').toString(),
        suppliers: (json['suppliers'] as List<dynamic>? ?? const [])
            .map((e) => e.toString())
            .toList(),
      );
}

class ContractorProfileItem {
  final String name;
  final String label;
  final String contractor;
  final bool generic;
  final bool hasLogo;
  final String trade;
  final Map<String, dynamic> markups;
  final int? calibrationPct;
  final List<String> missingData;
  final String? nextPendingModule;

  const ContractorProfileItem({
    required this.name,
    required this.label,
    required this.contractor,
    required this.generic,
    required this.hasLogo,
    required this.trade,
    required this.markups,
    this.calibrationPct,
    this.missingData = const [],
    this.nextPendingModule,
  });

  factory ContractorProfileItem.fromJson(Map<String, dynamic> json) => ContractorProfileItem(
        name: (json['name'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        contractor: (json['contractor'] ?? '').toString(),
        generic: json['generic'] == true,
        hasLogo: json['has_logo'] == true,
        trade: (json['trade'] ?? '').toString(),
        markups: (json['markups'] as Map<String, dynamic>? ?? const {}),
        calibrationPct: (json['calibration_pct'] as num?)?.toInt(),
        missingData: (json['missing_data'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        nextPendingModule: json['next_pending_module']?.toString(),
      );
}

class CalibrationModule {
  final String id;
  final String key;
  final String label;
  final int weight;
  final bool complete;
  final String detail;

  const CalibrationModule({
    required this.id,
    required this.key,
    required this.label,
    required this.weight,
    required this.complete,
    required this.detail,
  });

  factory CalibrationModule.fromJson(Map<String, dynamic> json) => CalibrationModule(
        id: (json['id'] ?? '').toString(),
        key: (json['key'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        weight: (json['weight'] as num? ?? 20).toInt(),
        complete: json['complete'] == true,
        detail: (json['detail'] ?? '').toString(),
      );
}

class ProfileCalibration {
  final String profile;
  final String contractor;
  final int percent;
  final List<String> missingData;
  final bool hasLogo;
  final int quoteCount;
  final String? nextPendingModule;
  final List<CalibrationModule> modules;

  const ProfileCalibration({
    required this.profile,
    required this.contractor,
    required this.percent,
    required this.missingData,
    required this.hasLogo,
    required this.quoteCount,
    this.nextPendingModule,
    this.modules = const [],
  });

  factory ProfileCalibration.fromJson(Map<String, dynamic> json) => ProfileCalibration(
        profile: (json['profile'] ?? '').toString(),
        contractor: (json['contractor'] ?? '').toString(),
        percent: (json['percent'] as num? ?? 0).toInt(),
        missingData: (json['missing_data'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        hasLogo: json['has_logo'] == true,
        quoteCount: (json['quote_count'] as num? ?? 0).toInt(),
        nextPendingModule: json['next_pending_module']?.toString(),
        modules: (json['modules'] as List<dynamic>? ?? const [])
            .map((e) => CalibrationModule.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList(),
      );
}

const List<ContractorProfileItem> defaultAlkanProfiles = [
  ContractorProfileItem(
    name: 'ss_custom_iron_works',
    label: 'S & S Custom Iron Works LLC',
    contractor: 'S & S CUSTOM IRON WORKS LLC',
    generic: false,
    hasLogo: true,
    trade: 'Metal fabrication, structural steel, railings, fences & gates',
    markups: {'contingency_pct': '5', 'overhead_pct': '10', 'profit_pct': '10'},
  ),
  ContractorProfileItem(
    name: 'pj_roofing',
    label: 'P J Roofing LLC',
    contractor: 'P J ROOFING LLC',
    generic: false,
    hasLogo: false,
    trade: 'Roofing, TPO, shingles & architectural flashing',
    markups: {'contingency_pct': '5', 'overhead_pct': '10', 'profit_pct': '10'},
  ),
  ContractorProfileItem(
    name: 'diaz_finish_carpenter',
    label: 'Díaz Finish Carpenter',
    contractor: 'DÍAZ FINISH CARPENTER',
    generic: false,
    hasLogo: false,
    trade: 'Finish carpentry, drywall, painting & casework',
    markups: {'contingency_pct': '5', 'overhead_pct': '10', 'profit_pct': '10'},
  ),
  ContractorProfileItem(
    name: 'jc_granite_design',
    label: 'JC Granite Design LLC',
    contractor: 'JC GRANITE DESIGN LLC',
    generic: false,
    hasLogo: false,
    trade: 'Stone, quartz & solid surface countertops',
    markups: {'contingency_pct': '5', 'overhead_pct': '10', 'profit_pct': '10'},
  ),
  ContractorProfileItem(
    name: 'duran_gc',
    label: 'Duran General Contractor LLC',
    contractor: 'DURAN GENERAL CONTRACTOR LLC',
    generic: false,
    hasLogo: false,
    trade: 'General contracting & multi-trade commercial/residential',
    markups: {'contingency_pct': '5', 'overhead_pct': '10', 'profit_pct': '10'},
  ),
  ContractorProfileItem(
    name: 'generico_sin_marca',
    label: 'Genérico sin marca',
    contractor: '[CONTRACTOR NAME]',
    generic: true,
    hasLogo: false,
    trade: 'Perfil neutro configurable para cualquier contratista WA',
    markups: {'contingency_pct': '5', 'overhead_pct': '10', 'profit_pct': '10'},
  ),
];

class EstimateRunCard {
  final String id;
  final String key;
  final String contractor;
  final String profile;
  final String specialty;
  final String county;
  final String status;
  final String canonicalState;
  final String badgeStatus; // analyzing | draft_ready | approved | no_go | error
  final String badgeLabel;
  final String stage;
  final String? price;
  final String? direct;
  final String? decision;
  final String? qa;
  final String actor;
  final String? authorizedBy;
  final String startedAt;
  final int budgetCount;
  final int quoteCount;
  final int voiceNotesCount;
  final bool clientShareUnlocked;
  final int progressPct;

  const EstimateRunCard({
    required this.id,
    required this.key,
    required this.contractor,
    required this.profile,
    required this.specialty,
    required this.county,
    required this.status,
    required this.canonicalState,
    required this.badgeStatus,
    required this.badgeLabel,
    required this.stage,
    required this.price,
    required this.direct,
    required this.decision,
    required this.qa,
    required this.actor,
    required this.authorizedBy,
    required this.startedAt,
    required this.budgetCount,
    required this.quoteCount,
    required this.voiceNotesCount,
    required this.clientShareUnlocked,
    required this.progressPct,
  });

  factory EstimateRunCard.fromJson(Map<String, dynamic> json) => EstimateRunCard(
        id: (json['id'] ?? '').toString(),
        key: (json['key'] ?? '').toString(),
        contractor: (json['contractor'] ?? '').toString(),
        profile: (json['profile'] ?? '').toString(),
        specialty: (json['specialty'] ?? '').toString(),
        county: (json['county'] ?? '').toString(),
        status: (json['status'] ?? '').toString(),
        canonicalState: (json['canonical_state'] ?? '').toString(),
        badgeStatus: (json['badge_status'] ?? 'analyzing').toString(),
        badgeLabel: (json['badge_label'] ?? '').toString(),
        stage: (json['stage'] ?? '').toString(),
        price: json['price']?.toString(),
        direct: json['direct']?.toString(),
        decision: json['decision']?.toString(),
        qa: json['qa']?.toString(),
        actor: (json['actor'] ?? '').toString(),
        authorizedBy: json['authorized_by']?.toString(),
        startedAt: (json['started_at'] ?? '').toString(),
        budgetCount: (json['budget_count'] as num? ?? 0).toInt(),
        quoteCount: (json['quote_count'] as num? ?? 0).toInt(),
        voiceNotesCount: (json['voice_notes_count'] as num? ?? 0).toInt(),
        clientShareUnlocked: json['client_share_unlocked'] == true,
        progressPct: (json['progress_pct'] as num? ?? 0).toInt(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'key': key,
        'contractor': contractor,
        'profile': profile,
        'specialty': specialty,
        'county': county,
        'status': status,
        'canonical_state': canonicalState,
        'badge_status': badgeStatus,
        'badge_label': badgeLabel,
        'stage': stage,
        'price': price,
        'direct': direct,
        'decision': decision,
        'qa': qa,
        'actor': actor,
        'authorized_by': authorizedBy,
        'started_at': startedAt,
        'budget_count': budgetCount,
        'quote_count': quoteCount,
        'voice_notes_count': voiceNotesCount,
        'client_share_unlocked': clientShareUnlocked,
        'progress_pct': progressPct,
      };
}

class ProgressStepItem {
  final String id;
  final String label;
  final int index;
  final String state; // pending | active | done | error

  const ProgressStepItem({
    required this.id,
    required this.label,
    required this.index,
    required this.state,
  });

  factory ProgressStepItem.fromJson(Map<String, dynamic> json) => ProgressStepItem(
        id: (json['id'] ?? '').toString(),
        label: (json['label'] ?? '').toString(),
        index: (json['index'] as num? ?? 0).toInt(),
        state: (json['state'] ?? 'pending').toString(),
      );
}

class DeliverableDocItem {
  final String docType;
  final String title;
  final String subtitle;
  final String filename;
  final bool internalOnly;
  final bool isDraft;
  final bool shareToClientAllowed;
  final bool exists;
  final int bytes;

  const DeliverableDocItem({
    required this.docType,
    required this.title,
    required this.subtitle,
    required this.filename,
    required this.internalOnly,
    required this.isDraft,
    required this.shareToClientAllowed,
    required this.exists,
    required this.bytes,
  });

  factory DeliverableDocItem.fromJson(Map<String, dynamic> json) => DeliverableDocItem(
        docType: (json['doc_type'] ?? '').toString(),
        title: (json['title'] ?? '').toString(),
        subtitle: (json['subtitle'] ?? '').toString(),
        filename: (json['filename'] ?? '').toString(),
        internalOnly: json['internal_only'] == true,
        isDraft: json['is_draft'] != false,
        shareToClientAllowed: json['share_to_client_allowed'] == true,
        exists: json['exists'] == true,
        bytes: (json['bytes'] as num? ?? 0).toInt(),
      );
}

class RunExecutiveSummary {
  final Map<String, dynamic> run;
  final List<ProgressStepItem> steps;
  final int percent;
  final bool isRunning;
  final String stage;
  final List<Map<String, dynamic>> events;
  final Map<String, dynamic> financials;
  final Map<String, dynamic> humanLock;
  final List<DeliverableDocItem> documents;
  final List<Map<String, dynamic>> voiceNotes;
  final String reportMd;

  const RunExecutiveSummary({
    required this.run,
    required this.steps,
    required this.percent,
    required this.isRunning,
    required this.stage,
    required this.events,
    required this.financials,
    required this.humanLock,
    required this.documents,
    required this.voiceNotes,
    required this.reportMd,
  });

  bool get isApproved => humanLock['is_approved'] == true;
  bool get clientShareUnlocked => humanLock['client_share_unlocked'] == true;
  bool get isRejectedOrNoGo => humanLock['is_rejected_or_nogo'] == true;

  factory RunExecutiveSummary.fromJson(Map<String, dynamic> json) {
    final prog = json['progress'] as Map<String, dynamic>? ?? const {};
    return RunExecutiveSummary(
      run: json['run'] as Map<String, dynamic>? ?? const {},
      steps: (prog['steps'] as List<dynamic>? ?? const [])
          .map((e) => ProgressStepItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      percent: (prog['percent'] as num? ?? 0).toInt(),
      isRunning: prog['is_running'] == true,
      stage: (prog['stage'] ?? '').toString(),
      events: (json['events'] as List<dynamic>? ?? const [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList(),
      financials: json['financials'] as Map<String, dynamic>? ?? const {},
      humanLock: json['human_lock'] as Map<String, dynamic>? ?? const {},
      documents: (json['documents'] as List<dynamic>? ?? const [])
          .map((e) => DeliverableDocItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      voiceNotes: (json['voice_notes'] as List<dynamic>? ?? const [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList(),
      reportMd: (json['report_md'] ?? '').toString(),
    );
  }
}

class EditableMaterialLine {
  final String id;
  final String section;
  final String item;
  String qty;
  final String unit;
  final String unitPrice;
  final String priceBasis;

  EditableMaterialLine({
    required this.id,
    required this.section,
    required this.item,
    required this.qty,
    required this.unit,
    required this.unitPrice,
    required this.priceBasis,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'section': section,
        'item': item,
        'qty': qty,
        'unit': unit,
        'unit_price': unitPrice,
        'price_basis': priceBasis,
      };

  factory EditableMaterialLine.fromJson(Map<String, dynamic> json) => EditableMaterialLine(
        id: (json['id'] ?? '').toString(),
        section: (json['section'] ?? '').toString(),
        item: (json['item'] ?? '').toString(),
        qty: (json['qty'] ?? '1').toString(),
        unit: (json['unit'] ?? 'EA').toString(),
        unitPrice: (json['unit_price'] ?? '0.00').toString(),
        priceBasis: (json['price_basis'] ?? 'BUDGET').toString(),
      );
}

class EditableLaborLine {
  final String id;
  final String task;
  final String rate;
  String hours;

  EditableLaborLine({
    required this.id,
    required this.task,
    required this.rate,
    required this.hours,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'task': task,
        'rate': rate,
        'hours': hours,
      };

  factory EditableLaborLine.fromJson(Map<String, dynamic> json) => EditableLaborLine(
        id: (json['id'] ?? '').toString(),
        task: (json['task'] ?? '').toString(),
        rate: (json['rate'] ?? '').toString(),
        hours: (json['hours'] ?? '1').toString(),
      );
}

class DraftPreview {
  final String key;
  final String contractor;
  final String county;
  final bool countyWageVerified;
  final String? countyWageWarning;
  final List<String> specialties;
  final String? detectedCounty;
  final List<String> detectedSpecialties;
  final List<String> exclusions;
  final List<EditableMaterialLine> materials;
  final List<EditableLaborLine> labor;
  final Map<String, dynamic> markups;
  final int validityDays;

  const DraftPreview({
    required this.key,
    required this.contractor,
    this.county = 'King',
    this.countyWageVerified = true,
    this.countyWageWarning,
    this.specialties = const [],
    this.detectedCounty,
    this.detectedSpecialties = const [],
    required this.exclusions,
    required this.materials,
    required this.labor,
    required this.markups,
    required this.validityDays,
  });

  factory DraftPreview.fromJson(Map<String, dynamic> json) {
    final det = Map<String, dynamic>.from(json['detected'] as Map? ?? const {});
    return DraftPreview(
      key: (json['key'] ?? '').toString(),
      contractor: (json['contractor'] ?? '').toString(),
      county: (json['county'] ?? 'King').toString(),
      countyWageVerified: json['county_wage_verified'] != false,
      countyWageWarning: json['county_wage_warning']?.toString(),
      specialties: (json['specialties'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
      detectedCounty: det['county']?.toString(),
      detectedSpecialties: (det['specialties'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
      exclusions: (json['exclusions'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
      materials: (json['materials'] as List<dynamic>? ?? const [])
          .map((e) => EditableMaterialLine.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList(),
      labor: (json['labor'] as List<dynamic>? ?? const [])
          .map((e) => EditableLaborLine.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList(),
      markups: Map<String, dynamic>.from(json['markups'] as Map? ?? const {}),
      validityDays: (json['validity_days'] as num? ?? 30).toInt(),
    );
  }
}

class PendingOfflineEstimate {
  final String localId;
  final String key;
  final String projectTitle;
  final String profile;
  final String specialty;
  final List<String> specialties;
  final String county;
  final String voiceNotes;
  final List<String> filePaths;
  final bool useQuickPackage;
  final List<Map<String, dynamic>> materialsOverrides;
  final List<Map<String, dynamic>> laborOverrides;
  final Map<String, dynamic> markups;
  final int validityDays;
  final String createdAt;

  const PendingOfflineEstimate({
    required this.localId,
    required this.key,
    required this.projectTitle,
    required this.profile,
    required this.specialty,
    this.specialties = const [],
    required this.county,
    required this.voiceNotes,
    required this.filePaths,
    required this.useQuickPackage,
    this.materialsOverrides = const [],
    this.laborOverrides = const [],
    this.markups = const {},
    this.validityDays = 30,
    required this.createdAt,
  });

  Map<String, dynamic> toJson() => {
        'localId': localId,
        'key': key,
        'projectTitle': projectTitle,
        'profile': profile,
        'specialty': specialty,
        'specialties': specialties,
        'county': county,
        'voiceNotes': voiceNotes,
        'filePaths': filePaths,
        'useQuickPackage': useQuickPackage,
        'materialsOverrides': materialsOverrides,
        'laborOverrides': laborOverrides,
        'markups': markups,
        'validityDays': validityDays,
        'createdAt': createdAt,
      };

  factory PendingOfflineEstimate.fromJson(Map<String, dynamic> json) => PendingOfflineEstimate(
        localId: (json['localId'] ?? '').toString(),
        key: (json['key'] ?? '').toString(),
        projectTitle: (json['projectTitle'] ?? '').toString(),
        profile: (json['profile'] ?? '').toString(),
        specialty: (json['specialty'] ?? 'metal').toString(),
        specialties: (json['specialties'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        county: (json['county'] ?? 'King').toString(),
        voiceNotes: (json['voiceNotes'] ?? '').toString(),
        filePaths: (json['filePaths'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
        useQuickPackage: json['useQuickPackage'] == true,
        materialsOverrides: (json['materialsOverrides'] as List<dynamic>? ?? const [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList(),
        laborOverrides: (json['laborOverrides'] as List<dynamic>? ?? const [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList(),
        markups: Map<String, dynamic>.from(json['markups'] as Map? ?? const {}),
        validityDays: (json['validityDays'] as num? ?? 30).toInt(),
        createdAt: (json['createdAt'] ?? '').toString(),
      );
}
