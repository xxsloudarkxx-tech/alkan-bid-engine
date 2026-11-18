import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/alkan_theme.dart';

/// Insignia del logo oficial ALKAN Assistant con respaldo limpio si falta el asset.
class AlkanLogoBadge extends StatelessWidget {
  final double size;
  final bool withBorder;

  const AlkanLogoBadge({
    super.key,
    this.size = 64,
    this.withBorder = true,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: const Color(0xFF041428),
        border: withBorder ? Border.all(color: const Color(0xFF38BDF8), width: math.max(1.5, size * 0.03)) : null,
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF0284C7).withOpacity(0.28),
            blurRadius: size * 0.22,
            spreadRadius: 1,
          ),
        ],
      ),
      child: ClipOval(
        child: Image.asset(
          'assets/images/alkan_logo.png',
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => Center(
            child: Text(
              'ALKAN',
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w900,
                fontSize: math.max(10, size * 0.22),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Animación de carga con el logo ALKAN (pulso suave + halo giratorio azul eléctrico).
class AlkanLoadingAnimation extends StatefulWidget {
  final double size;
  final String? label;
  final Color textColor;

  const AlkanLoadingAnimation({
    super.key,
    this.size = 96,
    this.label,
    this.textColor = AlkanColors.ink,
  });

  @override
  State<AlkanLoadingAnimation> createState() => _AlkanLoadingAnimationState();
}

class _AlkanLoadingAnimationState extends State<AlkanLoadingAnimation> with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _pulse;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1600),
    )..repeat();
    _pulse = Tween<double>(begin: 0.93, end: 1.03).animate(
      CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final outer = widget.size + 18;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: outer,
          height: outer,
          child: Stack(
            alignment: Alignment.center,
            children: [
              RotationTransition(
                turns: _ctrl,
                child: SizedBox(
                  width: outer,
                  height: outer,
                  child: const CircularProgressIndicator(
                    strokeWidth: 4,
                    valueColor: AlwaysStoppedAnimation<Color>(Color(0xFF0EA5E9)),
                    backgroundColor: Color(0x330EA5E9),
                  ),
                ),
              ),
              ScaleTransition(
                scale: _pulse,
                child: AlkanLogoBadge(size: widget.size),
              ),
            ],
          ),
        ),
        if (widget.label != null && widget.label!.isNotEmpty) ...[
          const SizedBox(height: 14),
          Text(
            widget.label!,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: widget.textColor,
              fontSize: 15,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ],
    );
  }
}
