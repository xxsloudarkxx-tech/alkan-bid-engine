import 'package:flutter/material.dart';

import '../models/bid_models.dart';
import '../theme/alkan_theme.dart';
import 'alkan_loading_logo.dart';

/// Botón primario empresarial ALKAN Blue (mínimo 52 dp de área táctil).
class AlkanPrimaryButton extends StatelessWidget {
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final bool loading;
  final Color? backgroundColor;

  const AlkanPrimaryButton({
    super.key,
    required this.label,
    this.icon,
    this.onPressed,
    this.loading = false,
    this.backgroundColor,
  });

  @override
  Widget build(BuildContext context) {
    return ElevatedButton(
      onPressed: loading ? null : onPressed,
      style: ElevatedButton.styleFrom(
        minimumSize: const Size(double.infinity, 54),
        backgroundColor: backgroundColor ?? AlkanColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      child: loading
          ? const SizedBox(
              height: 22,
              width: 22,
              child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
            )
          : Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (icon != null) ...[Icon(icon, size: 22), const SizedBox(width: 10)],
                Flexible(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                  ),
                ),
              ],
            ),
    );
  }
}

/// Botón secundario limpio ALKAN Blue.
class AlkanSecondaryButton extends StatelessWidget {
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final Color? borderColor;
  final Color? foregroundColor;

  const AlkanSecondaryButton({
    super.key,
    required this.label,
    this.icon,
    this.onPressed,
    this.borderColor,
    this.foregroundColor,
  });

  @override
  Widget build(BuildContext context) {
    final fg = foregroundColor ?? AlkanColors.primary;
    return OutlinedButton(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(double.infinity, 50),
        foregroundColor: fg,
        backgroundColor: AlkanColors.surface,
        side: BorderSide(color: borderColor ?? AlkanColors.border, width: 1.5),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon, size: 20, color: fg), const SizedBox(width: 8)],
          Flexible(
            child: Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: fg),
            ),
          ),
        ],
      ),
    );
  }
}

/// Campo de texto estandarizado ALKAN Blue.
class AlkanTextField extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final String? hint;
  final bool obscureText;
  final int maxLines;
  final TextInputType? keyboardType;
  final ValueChanged<String>? onChanged;
  final Widget? suffixIcon;
  final bool readOnly;

  const AlkanTextField({
    super.key,
    required this.controller,
    required this.label,
    this.hint,
    this.obscureText = false,
    this.maxLines = 1,
    this.keyboardType,
    this.onChanged,
    this.suffixIcon,
    this.readOnly = false,
  });

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      obscureText: obscureText,
      maxLines: maxLines,
      keyboardType: keyboardType,
      onChanged: onChanged,
      readOnly: readOnly,
      style: const TextStyle(color: AlkanColors.textPrimary, fontWeight: FontWeight.w600),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        suffixIcon: suffixIcon,
      ),
    );
  }
}

/// Logotipo oficial ALKAN + descriptor BIDENGINE (sin redibujar el asset).
class AlkanLogo extends StatelessWidget {
  final double badgeSize;
  final bool showDescriptor;
  final Color titleColor;

  const AlkanLogo({
    super.key,
    this.badgeSize = 44,
    this.showDescriptor = true,
    this.titleColor = Colors.white,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        AlkanLogoBadge(size: badgeSize, withBorder: badgeSize >= 48),
        const SizedBox(width: 10),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'ALKAN',
              style: TextStyle(
                color: titleColor,
                fontSize: badgeSize >= 56 ? 24 : 18,
                fontWeight: FontWeight.w900,
                letterSpacing: 1.4,
              ),
            ),
            if (showDescriptor)
              const Text(
                'BIDENGINE',
                style: TextStyle(
                  color: AlkanColors.azulLuminoso,
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 2.2,
                ),
              ),
          ],
        ),
      ],
    );
  }
}

/// Encabezado corporativo azul profundo con subtítulo de contexto y acciones.
class AlkanHeader extends StatelessWidget {
  final String greeting;
  final String subtitle;
  final Widget? trailing;
  final Widget? bottom;

  const AlkanHeader({
    super.key,
    required this.greeting,
    required this.subtitle,
    this.trailing,
    this.bottom,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      decoration: BoxDecoration(
        color: AlkanColors.azulProfundo,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      greeting,
                      style: const TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w900),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: const TextStyle(color: Color(0xFFBFD8F8), fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
              if (trailing != null) trailing!,
            ],
          ),
          if (bottom != null) ...[
            const SizedBox(height: 14),
            bottom!,
          ],
        ],
      ),
    );
  }
}

/// Insignia de estado con ícono + texto (accesible más allá del color).
class AlkanStatusBadge extends StatelessWidget {
  final String status; // analyzing | draft_ready | approved | no_go | error
  final String label;

  const AlkanStatusBadge({
    super.key,
    required this.status,
    required this.label,
  });

  @override
  Widget build(BuildContext context) {
    Color color;
    IconData icon;
    switch (status) {
      case 'analyzing':
        color = AlkanColors.analyzing;
        icon = Icons.autorenew;
        break;
      case 'approved':
        color = AlkanColors.approved;
        icon = Icons.verified;
        break;
      case 'no_go':
      case 'error':
        color = AlkanColors.noGo;
        icon = Icons.error_outline;
        break;
      default:
        color = AlkanColors.draft;
        icon = Icons.edit_note;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.55)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

/// Indicador de progreso y calibración real en ALKAN Blue.
class AlkanProgressIndicator extends StatelessWidget {
  final int percent;
  final String label;
  final String? helper;

  const AlkanProgressIndicator({
    super.key,
    required this.percent,
    required this.label,
    this.helper,
  });

  @override
  Widget build(BuildContext context) {
    final p = (percent.clamp(0, 100)) / 100.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: AlkanColors.textPrimary),
              ),
            ),
            Text(
              '$percent%',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w900,
                color: percent >= 80 ? AlkanColors.approved : AlkanColors.primary,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: p,
            minHeight: 9,
            backgroundColor: AlkanColors.azulSuave,
            valueColor: AlwaysStoppedAnimation<Color>(
              percent >= 80 ? AlkanColors.approved : AlkanColors.azulPrincipal,
            ),
          ),
        ),
        if (helper != null && helper!.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(
            helper!,
            style: const TextStyle(fontSize: 12.5, color: AlkanColors.textSecondary, fontWeight: FontWeight.w600),
          ),
        ],
      ],
    );
  }
}

/// Tarjeta limpia de estimado / proyecto para Home y Pipeline.
class AlkanProjectCard extends StatelessWidget {
  final EstimateRunCard run;
  final VoidCallback onTap;
  final VoidCallback? onOptions;

  const AlkanProjectCard({
    super.key,
    required this.run,
    required this.onTap,
    this.onOptions,
  });

  @override
  Widget build(BuildContext context) {
    final needsAttention = run.budgetCount > 0 || run.badgeStatus == 'draft_ready' || run.badgeStatus == 'no_go';
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      run.key,
                      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: AlkanColors.textPrimary),
                    ),
                  ),
                  AlkanStatusBadge(status: run.badgeStatus, label: run.badgeLabel),
                  if (onOptions != null) ...[
                    const SizedBox(width: 4),
                    IconButton(
                      icon: const Icon(Icons.more_vert, size: 20, color: AlkanColors.textSecondary),
                      onPressed: onOptions,
                      padding: EdgeInsets.zero,
                      constraints: const BoxConstraints(),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 6),
              Text(
                run.contractor.isNotEmpty ? run.contractor : run.profile,
                style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: AlkanColors.textPrimary),
              ),
              const SizedBox(height: 3),
              Text(
                '${run.specialty.isNotEmpty ? "${run.specialty.toUpperCase()} · " : ""}${run.county} · ${run.stage}',
                style: const TextStyle(fontSize: 13, color: AlkanColors.textSecondary),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  if (run.price != null && run.price!.isNotEmpty)
                    Text(
                      '\$${run.price}',
                      style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w900, color: AlkanColors.primary),
                    )
                  else
                    Text(
                      'Avance ${run.progressPct}%',
                      style: const TextStyle(fontWeight: FontWeight.w800, color: AlkanColors.analyzing),
                    ),
                  const Spacer(),
                  if (run.budgetCount > 0)
                    Container(
                      margin: const EdgeInsets.only(right: 8),
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: AlkanColors.noGo.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        '${run.budgetCount} BUDGET',
                        style: const TextStyle(color: AlkanColors.noGo, fontWeight: FontWeight.w800, fontSize: 11.5),
                      ),
                    ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: needsAttention ? AlkanColors.azulSuave : AlkanColors.background,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      run.clientShareUnlocked ? 'Enviar →' : 'Revisar →',
                      style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: AlkanColors.primary),
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

/// Tarjeta para los 3 PDFs reales del motor respetando candado interno/externo.
class AlkanDocumentCard extends StatelessWidget {
  final DeliverableDocItem doc;
  final bool busy;
  final VoidCallback onView;
  final VoidCallback? onShare;

  const AlkanDocumentCard({
    super.key,
    required this.doc,
    required this.busy,
    required this.onView,
    this.onShare,
  });

  @override
  Widget build(BuildContext context) {
    final statusLabel = !doc.exists
        ? 'Pendiente'
        : doc.internalOnly
            ? 'Solo uso interno'
            : (doc.isDraft ? 'BORRADOR (DRAFT)' : 'Autorizado');
    final statusColor = !doc.exists
        ? AlkanColors.textSecondary
        : doc.internalOnly
            ? AlkanColors.azulInstitucional
            : (doc.isDraft ? AlkanColors.draft : AlkanColors.approved);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: AlkanColors.azulSuave,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                doc.internalOnly ? Icons.analytics_outlined : Icons.description_outlined,
                color: AlkanColors.primary,
                size: 26,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(doc.title, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15.5)),
                  const SizedBox(height: 2),
                  Text(doc.subtitle, style: const TextStyle(fontSize: 12.5, color: AlkanColors.textSecondary)),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: statusColor.withOpacity(0.12),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          statusLabel,
                          style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: statusColor),
                        ),
                      ),
                      if (doc.bytes > 0) ...[
                        const SizedBox(width: 8),
                        Text(
                          '${(doc.bytes / 1024).toStringAsFixed(0)} KB',
                          style: const TextStyle(fontSize: 11.5, color: AlkanColors.textSecondary),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              children: [
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size(74, 42),
                    backgroundColor: AlkanColors.primary,
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                  ),
                  onPressed: busy || !doc.exists ? null : onView,
                  child: const Text('Ver', style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800)),
                ),
                if (doc.shareToClientAllowed && onShare != null) ...[
                  const SizedBox(height: 6),
                  TextButton(
                    onPressed: busy ? null : onShare,
                    child: const Text('Enviar', style: TextStyle(fontSize: 12.5)),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Tarjeta de Contratista para selección rápida o calibración.
class AlkanContractorCard extends StatelessWidget {
  final ContractorProfileItem profile;
  final bool selected;
  final int? calibrationPercent;
  final String? logoUrl;
  final Map<String, String>? authHeaders;
  final VoidCallback onTap;
  final VoidCallback? onEdit;

  const AlkanContractorCard({
    super.key,
    required this.profile,
    required this.selected,
    this.calibrationPercent,
    this.logoUrl,
    this.authHeaders,
    required this.onTap,
    this.onEdit,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(
          color: selected ? AlkanColors.primary : AlkanColors.border,
          width: selected ? 2.0 : 1.2,
        ),
      ),
      color: selected ? AlkanColors.azulSuave.withOpacity(0.55) : AlkanColors.surface,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  color: AlkanColors.surface,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AlkanColors.border),
                ),
                child: (logoUrl != null && profile.hasLogo)
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(10),
                        child: Image.network(
                          logoUrl!,
                          headers: authHeaders,
                          fit: BoxFit.contain,
                          errorBuilder: (_, __, ___) => const Icon(Icons.apartment, color: AlkanColors.primary),
                        ),
                      )
                    : const Icon(Icons.apartment, color: AlkanColors.primary, size: 28),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      profile.contractor,
                      style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w900, color: AlkanColors.textPrimary),
                    ),
                    if (profile.trade.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        profile.trade,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 12.5, color: AlkanColors.textSecondary),
                      ),
                    ],
                    if (calibrationPercent != null) ...[
                      const SizedBox(height: 6),
                      Text(
                        'Calibración: $calibrationPercent%',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                          color: calibrationPercent! >= 80 ? AlkanColors.approved : AlkanColors.primary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (onEdit != null)
                IconButton(
                  tooltip: 'Configurar',
                  onPressed: onEdit,
                  icon: const Icon(Icons.tune, color: AlkanColors.primary),
                ),
              Icon(
                selected ? Icons.check_circle : Icons.radio_button_unchecked,
                color: selected ? AlkanColors.primary : AlkanColors.border,
                size: 26,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Estado vacío claro con acción sugerida.
class AlkanEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  const AlkanEmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(28),
      decoration: BoxDecoration(
        color: AlkanColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AlkanColors.border),
      ),
      child: Column(
        children: [
          Container(
            width: 58,
            height: 58,
            decoration: const BoxDecoration(color: AlkanColors.azulSuave, shape: BoxShape.circle),
            child: Icon(icon, size: 30, color: AlkanColors.primary),
          ),
          const SizedBox(height: 14),
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w900, color: AlkanColors.textPrimary),
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 13.5, color: AlkanColors.textSecondary, height: 1.4),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(height: 16),
            AlkanPrimaryButton(
              label: actionLabel!,
              icon: Icons.mic,
              onPressed: onAction,
            ),
          ],
        ],
      ),
    );
  }
}
