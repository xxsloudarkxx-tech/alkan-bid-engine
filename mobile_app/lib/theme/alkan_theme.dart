import 'package:flutter/material.dart';

/// Paleta de alto contraste pensada para contratistas en obra o camioneta.
class AlkanColors {
  static const Color primary = Color(0xFF0F3D3E);
  static const Color primaryDark = Color(0xFF092829);
  static const Color accent = Color(0xFFD97706);
  static const Color background = Color(0xFFF3F5F4);
  static const Color surface = Colors.white;
  static const Color ink = Color(0xFF111827);
  static const Color muted = Color(0xFF4B5563);
  static const Color border = Color(0xFFD1D5DB);

  // Semáforo operativo ALKAN
  static const Color analyzing = Color(0xFFEAB308);
  static const Color draft = Color(0xFFEA580C);
  static const Color approved = Color(0xFF16A34A);
  static const Color noGo = Color(0xFFDC2626);
}

ThemeData buildAlkanTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: AlkanColors.primary,
    primary: AlkanColors.primary,
    secondary: AlkanColors.accent,
    surface: AlkanColors.surface,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AlkanColors.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: AlkanColors.primary,
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
        foregroundColor: AlkanColors.primary,
        side: const BorderSide(color: AlkanColors.primary, width: 1.8),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
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
        borderSide: const BorderSide(color: AlkanColors.primary, width: 2.2),
      ),
      labelStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AlkanColors.ink),
    ),
    cardColor: Colors.white,
  );
}
