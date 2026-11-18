import 'package:flutter/material.dart';

/// Paleta oficial ALKAN Assistant (#041428 azul marino + azul eléctrico) de alto contraste para campo.
class AlkanColors {
  static const Color primary = Color(0xFF1D8CF8);
  static const Color primaryDark = Color(0xFF041428);
  static const Color accent = Color(0xFF0EA5E9);
  static const Color background = Color(0xFF041428);
  static const Color surface = Color(0xFF0A213F);
  static const Color surfaceAlt = Color(0xFF071932);
  static const Color ink = Color(0xFFF8FAFC);
  static const Color muted = Color(0xFF94A3B8);
  static const Color border = Color(0xFF1E3A5F);

  // Semáforo operativo ALKAN
  static const Color analyzing = Color(0xFFFACC15);
  static const Color draft = Color(0xFFFB923C);
  static const Color approved = Color(0xFF22C55E);
  static const Color noGo = Color(0xFFF87171);
}

ThemeData buildAlkanTheme() {
  final scheme = ColorScheme.fromSeed(
    brightness: Brightness.dark,
    seedColor: AlkanColors.primary,
    primary: AlkanColors.primary,
    secondary: AlkanColors.accent,
    surface: AlkanColors.surface,
  );
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: AlkanColors.background,
    canvasColor: AlkanColors.surface,
    cardColor: AlkanColors.surface,
    dialogBackgroundColor: AlkanColors.surface,
    dividerColor: AlkanColors.border,
    cardTheme: CardTheme(
      color: AlkanColors.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: AlkanColors.border, width: 1.2),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: AlkanColors.surface,
      selectedColor: AlkanColors.primary,
      side: const BorderSide(color: AlkanColors.border),
      labelStyle: const TextStyle(color: AlkanColors.ink, fontWeight: FontWeight.w700),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AlkanColors.primaryDark,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: Colors.white,
        fontSize: 20,
        fontWeight: FontWeight.w800,
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        minimumSize: const Size(double.infinity, 58),
        backgroundColor: AlkanColors.primary,
        foregroundColor: Colors.white,
        textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(double.infinity, 54),
        foregroundColor: const Color(0xFF7DD3FC),
        side: const BorderSide(color: AlkanColors.accent, width: 1.6),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: const Color(0xFF7DD3FC),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AlkanColors.surfaceAlt,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AlkanColors.border, width: 1.5),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AlkanColors.border, width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AlkanColors.accent, width: 2.2),
      ),
      labelStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Color(0xFFCBD5E1)),
      hintStyle: const TextStyle(color: AlkanColors.muted),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AlkanColors.surface,
      contentTextStyle: TextStyle(color: AlkanColors.ink, fontWeight: FontWeight.w700),
    ),
  );
}
