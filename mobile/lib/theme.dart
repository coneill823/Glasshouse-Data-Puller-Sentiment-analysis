/// Colours, type and component styling for the whole app.
///
/// The palette is a set of cool neutrals leaning toward one blue. That blue is
/// the only colour data is drawn in: nothing here is coloured "good" or "bad",
/// and no party is given its own colour.
library;

import 'package:material_ui/material_ui.dart';

@immutable
class GlassColors extends ThemeExtension<GlassColors> {
  const GlassColors({
    required this.paper,
    required this.surface,
    required this.surface2,
    required this.ink,
    required this.ink2,
    required this.muted,
    required this.line,
    required this.edge,
    required this.accent,
    required this.onAccent,
    required this.wash,
    required this.data,
    required this.track,
    required this.dot,
  });

  /// The page behind everything.
  final Color paper;

  /// Cards and inputs.
  final Color surface;

  /// Quiet fills inside a card.
  final Color surface2;

  /// Text, in three strengths.
  final Color ink, ink2, muted;

  /// Hairlines that separate, and edges that mark something you can press.
  final Color line, edge;

  /// Things you can press, and the tint behind a selected one.
  final Color accent, onAccent, wash;

  /// Every mark that shows a number.
  final Color data;

  /// The empty part of a bar.
  final Color track;

  /// One MP among many on the compass.
  final Color dot;

  static const GlassColors light = GlassColors(
    paper: Color(0xFFF2F4F7),
    surface: Color(0xFFFFFFFF),
    surface2: Color(0xFFE9ECF1),
    ink: Color(0xFF11151C),
    ink2: Color(0xFF39414F),
    muted: Color(0xFF67707F),
    line: Color(0xFFD8DDE5),
    edge: Color(0xFF7F899B),
    accent: Color(0xFF2F5FA8),
    onAccent: Color(0xFFFFFFFF),
    wash: Color(0xFFDFE8F6),
    data: Color(0xFF2F5FA8),
    track: Color(0xFFDDE2E9),
    dot: Color(0xFF9AA4B4),
  );

  static const GlassColors dark = GlassColors(
    paper: Color(0xFF11151C),
    surface: Color(0xFF171C26),
    surface2: Color(0xFF1F2632),
    ink: Color(0xFFEEF1F6),
    ink2: Color(0xFFC2C9D6),
    muted: Color(0xFF8F98A8),
    line: Color(0xFF2A3240),
    edge: Color(0xFF667287),
    accent: Color(0xFF8FA8D8),
    onAccent: Color(0xFF0E1B33),
    wash: Color(0xFF23314A),
    data: Color(0xFF5A8AE0),
    track: Color(0xFF2A3240),
    dot: Color(0xFF5B6678),
  );

  @override
  GlassColors copyWith() => this;

  @override
  GlassColors lerp(GlassColors? other, double t) {
    if (other == null) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t)!;
    return GlassColors(
      paper: mix(paper, other.paper),
      surface: mix(surface, other.surface),
      surface2: mix(surface2, other.surface2),
      ink: mix(ink, other.ink),
      ink2: mix(ink2, other.ink2),
      muted: mix(muted, other.muted),
      line: mix(line, other.line),
      edge: mix(edge, other.edge),
      accent: mix(accent, other.accent),
      onAccent: mix(onAccent, other.onAccent),
      wash: mix(wash, other.wash),
      data: mix(data, other.data),
      track: mix(track, other.track),
      dot: mix(dot, other.dot),
    );
  }
}

extension GlassContext on BuildContext {
  GlassColors get glass => Theme.of(this).extension<GlassColors>()!;
}

FontWeight _weight(int w) => switch (w) {
      <= 350 => FontWeight.w300,
      <= 450 => FontWeight.w400,
      <= 550 => FontWeight.w500,
      <= 650 => FontWeight.w600,
      _ => FontWeight.w700,
    };

/// The three typefaces. Fraunces and Public Sans ship as variable fonts, so
/// the weight is set on the font's own axis as well as on the style.
abstract final class GlassText {
  /// Fraunces: names, headings, the statement being asked, large figures.
  static TextStyle display(double size, {int weight = 600, double height = 1.16, Color? color}) =>
      TextStyle(
        fontFamily: 'Fraunces',
        fontSize: size,
        height: height,
        color: color,
        fontWeight: _weight(weight),
        letterSpacing: size >= 24 ? -0.2 : 0,
        fontVariations: [
          FontVariation('wght', weight.toDouble()),
          FontVariation('opsz', size.clamp(9, 144).toDouble()),
        ],
        fontFeatures: const [FontFeature.liningFigures()],
      );

  /// Public Sans: everything that is read as running text.
  static TextStyle body(double size, {int weight = 400, double height = 1.45, Color? color}) =>
      TextStyle(
        fontFamily: 'PublicSans',
        fontSize: size,
        height: height,
        color: color,
        fontWeight: _weight(weight),
        fontVariations: [FontVariation('wght', weight.toDouble())],
      );

  /// IBM Plex Mono: labels, dates and figures that line up in columns.
  static TextStyle mono(double size, {int weight = 400, double height = 1.35, Color? color}) =>
      TextStyle(
        fontFamily: 'IBMPlexMono',
        fontSize: size,
        height: height,
        color: color,
        fontWeight: weight >= 500 ? FontWeight.w500 : FontWeight.w400,
      );

  static TextStyle eyebrow(Color color) =>
      mono(11, weight: 500, color: color).copyWith(letterSpacing: 0.9);
}

ThemeData buildTheme(Brightness brightness) {
  final c = brightness == Brightness.dark ? GlassColors.dark : GlassColors.light;
  final scheme = ColorScheme.fromSeed(seedColor: GlassColors.light.accent, brightness: brightness)
      .copyWith(
    primary: c.accent,
    onPrimary: c.onAccent,
    primaryContainer: c.wash,
    onPrimaryContainer: c.ink,
    secondary: c.accent,
    onSecondary: c.onAccent,
    secondaryContainer: c.wash,
    onSecondaryContainer: c.ink,
    surface: c.surface,
    onSurface: c.ink,
    onSurfaceVariant: c.ink2,
    surfaceContainerLowest: c.surface,
    surfaceContainerLow: c.surface,
    surfaceContainer: c.surface,
    surfaceContainerHigh: c.surface2,
    surfaceContainerHighest: c.surface2,
    outline: c.edge,
    outlineVariant: c.line,
    surfaceTint: const Color(0x00000000),
  );
  final rounded = RoundedRectangleBorder(borderRadius: BorderRadius.circular(10));
  final button = GlassText.body(15, weight: 600, height: 1.25);

  return ThemeData(
    colorScheme: scheme,
    scaffoldBackgroundColor: c.paper,
    canvasColor: c.paper,
    dividerColor: c.line,
    fontFamily: 'PublicSans',
    extensions: [c],
    textTheme: TextTheme(
      displaySmall: GlassText.display(40, color: c.ink),
      headlineMedium: GlassText.display(26, color: c.ink),
      headlineSmall: GlassText.display(22, color: c.ink),
      titleLarge: GlassText.display(20, color: c.ink),
      titleMedium: GlassText.body(16, weight: 600, color: c.ink),
      titleSmall: GlassText.body(14, weight: 600, color: c.ink),
      bodyLarge: GlassText.body(16, color: c.ink),
      bodyMedium: GlassText.body(15, color: c.ink),
      bodySmall: GlassText.body(13, color: c.ink2),
      labelLarge: button.copyWith(color: c.ink),
      labelMedium: GlassText.body(12, weight: 600, color: c.ink2),
      labelSmall: GlassText.mono(11, weight: 500, color: c.muted),
    ),
    appBarTheme: AppBarThemeData(
      backgroundColor: c.paper,
      foregroundColor: c.ink,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      toolbarHeight: 52,
      titleSpacing: 16,
      titleTextStyle: GlassText.display(21, color: c.ink),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 66,
      elevation: 0,
      backgroundColor: c.surface,
      indicatorColor: c.wash,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final on = states.contains(WidgetState.selected);
        return GlassText.body(12, weight: on ? 700 : 500, height: 1.2, color: on ? c.ink : c.ink2);
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) => IconThemeData(
            size: 22,
            color: states.contains(WidgetState.selected) ? c.ink : c.ink2,
          )),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 48),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        shape: rounded,
        textStyle: button,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        shape: rounded,
        side: BorderSide(color: c.edge),
        foregroundColor: c.ink,
        backgroundColor: c.surface,
        textStyle: button,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(48, 44),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        shape: rounded,
        foregroundColor: c.accent,
        textStyle: button,
      ),
    ),
    inputDecorationTheme: InputDecorationThemeData(
      filled: true,
      fillColor: c.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      hintStyle: GlassText.body(15, color: c.muted),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: c.edge),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: c.edge),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: c.accent, width: 2),
      ),
    ),
    checkboxTheme: CheckboxThemeData(
      side: BorderSide(color: c.edge, width: 1.5),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: c.data, linearTrackColor: c.track),
    dividerTheme: DividerThemeData(color: c.line, thickness: 1, space: 1),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: c.ink,
      contentTextStyle: GlassText.body(14, color: c.paper),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      titleTextStyle: GlassText.display(20, color: c.ink),
      contentTextStyle: GlassText.body(15, color: c.ink2),
    ),
  );
}
