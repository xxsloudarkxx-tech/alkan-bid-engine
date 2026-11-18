import 'package:flutter/material.dart';

/// Sistema de diseño "ALKAN Blue" — Minimalismo empresarial para contratistas en obra.
class AlkanColors {
  // Paleta principal ALKAN Blue
  static const Color azulProfundo = Color(0xFF061A35);
  static const Color azulInstitucional = Color(0xFF0757B8);
  static const Color azulPrincipal = Color(0xFF0869CC);
  static const Color azulElectrico = Color(0xFF087CEB);
  static const Color azulLuminoso = Color(0xFF20B9FF);
  static const Color azulSuave = Color(0xFFEAF4FF);
  static const Color blanco = Color(0xFFFFFFFF);
  static const Color grisLectura = Color(0xFF65758B);
  static const Color grisSuperficie = Color(0xFFF4F7FB);

  // Roles semánticos
  static const Color primary = azulPrincipal;
  static const Color primaryDark = azulInstitucional;
  static const Color info = azulLuminoso;
  static const Color accent = azulElectrico;
  static const Color background = grisSuperficie;
  static const Color surface = blanco;
  static const Color surfaceElevated = blanco;
  static const Color surfaceAlt = azulSuave;
  static const Color textPrimary = Color(0xFF0B1B33);
  static const Color textSecondary = grisLectura;
  static const Color ink = textPrimary;
  static const Color muted = textSecondary;
  static const Color border = Color(0xFFE2E9F2);

  // Semáforo operativo ALKAN (diferenciado del azul)
  static const Color approved = Color(0xFF16A34A);
  static const Color analyzing = Color(0xFFD97706);
  static const Color draft = Color(0xFFEA580C);
  static const Color noGo = Color(0xFFDC2626);
}

ThemeData buildAlkanTheme() {
  final scheme = ColorScheme.fromSeed(
    brightness: Brightness.light,
    seedColor: AlkanColors.primary,
    primary: AlkanColors.primary,
    secondary: AlkanColors.info,
    surface: AlkanColors.surface,
  );
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    colorScheme: scheme,
    scaffoldBackgroundColor: AlkanColors.background,
    canvasColor: AlkanColors.surface,
    cardColor: AlkanColors.surface,
    dialogBackgroundColor: AlkanColors.surface,
    dividerColor: AlkanColors.border,
    cardTheme: CardTheme(
      color: AlkanColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: AlkanColors.border, width: 1.2),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: AlkanColors.surface,
      selectedColor: AlkanColors.primary,
      side: const BorderSide(color: AlkanColors.border),
      labelStyle: const TextStyle(color: AlkanColors.textPrimary, fontWeight: FontWeight.w700),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AlkanColors.azulProfundo,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: Colors.white,
        fontSize: 19,
        fontWeight: FontWeight.w800,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AlkanColors.surface,
      indicatorColor: AlkanColors.azulSuave,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final sel = states.contains(WidgetState.selected);
        return TextStyle(
          fontSize: 12,
          fontWeight: sel ? FontWeight.w800 : FontWeight.w600,
          color: sel ? AlkanColors.primary : AlkanColors.textSecondary,
        );
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final sel = states.contains(WidgetState.selected);
        return IconThemeData(
          color: sel ? AlkanColors.primary : AlkanColors.textSecondary,
        );
      }),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        minimumSize: const Size(double.infinity, 54),
        backgroundColor: AlkanColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(double.infinity, 50),
        foregroundColor: AlkanColors.primary,
        backgroundColor: AlkanColors.surface,
        side: const BorderSide(color: AlkanColors.border, width: 1.5),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AlkanColors.primary,
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AlkanColors.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AlkanColors.border, width: 1.4),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AlkanColors.border, width: 1.4),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AlkanColors.primary, width: 2.0),
      ),
      labelStyle: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: AlkanColors.textSecondary),
      hintStyle: const TextStyle(color: AlkanColors.textSecondary),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AlkanColors.azulProfundo,
      contentTextStyle: TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
    ),
  );
}
