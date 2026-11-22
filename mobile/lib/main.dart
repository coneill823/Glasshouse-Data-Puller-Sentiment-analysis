/// Glasshouse: who represents you, what they did, and how their votes compare
/// with your views.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:material_ui/material_ui.dart';

import 'core/app_state.dart';
import 'core/postcode.dart';
import 'core/repository.dart';
import 'theme.dart';
import 'ui/scope.dart';
import 'ui/shell.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  _registerFontLicences();
  runApp(const GlasshouseApp());
}

/// The three typefaces are used under the SIL Open Font Licence, which asks
/// that its text travels with them. This puts it on the licences screen.
void _registerFontLicences() {
  LicenseRegistry.addLicense(() async* {
    const fonts = [
      ('Fraunces', 'OFL-Fraunces.txt'),
      ('Public Sans', 'OFL-PublicSans.txt'),
      ('IBM Plex Mono', 'OFL-IBMPlexMono.txt'),
    ];
    for (final (family, file) in fonts) {
      yield LicenseEntryWithLineBreaks([family], await rootBundle.loadString('assets/fonts/$file'));
    }
  });
}

/// Reads the data and whatever was saved on this device.
Future<AppState> loadFromDevice() async {
  final loaded = await loadData();
  final state = AppState(data: loaded.data, quiz: loaded.quiz, store: PrefsStore());
  await state.restore();
  return state;
}

class GlasshouseApp extends StatefulWidget {
  const GlasshouseApp({super.key, this.load, this.postcodes});

  /// How to get the app's state. Tests supply their own.
  final Future<AppState> Function()? load;

  /// The postcode service. Tests supply their own.
  final PostcodeLookup Function(AppState state)? postcodes;

  @override
  State<GlasshouseApp> createState() => _GlasshouseAppState();
}

class _GlasshouseAppState extends State<GlasshouseApp> {
  AppState? _state;
  PostcodeLookup? _postcodes;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _state?.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    try {
      final state = await (widget.load ?? loadFromDevice)();
      if (!mounted) {
        state.dispose();
        return;
      }
      setState(() {
        _state = state;
        _postcodes = widget.postcodes?.call(state) ?? PostcodeLookup(state.data);
      });
      // Newer votes are fetched for the next launch, never swapped in mid-quiz.
      if (widget.load == null) unawaited(refreshInBackground());
    } on Object {
      if (mounted) setState(() => _failed = true);
    }
  }

  void _retry() {
    setState(() => _failed = false);
    _start();
  }

  @override
  Widget build(BuildContext context) {
    final state = _state;
    return MaterialApp(
      title: 'Glasshouse',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      builder: (context, child) => state == null
          ? child!
          : AppScope(state: state, postcodes: _postcodes!, child: child!),
      home: state != null
          ? const Shell()
          : _failed
              ? _Failed(onRetry: _retry)
              : const _Opening(),
    );
  }
}

class _Opening extends StatelessWidget {
  const _Opening();

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Glasshouse', style: GlassText.display(30, color: c.ink)),
            const SizedBox(height: 18),
            SizedBox(
              width: 120,
              child: LinearProgressIndicator(
                minHeight: 2,
                color: c.data,
                backgroundColor: c.track,
                semanticsLabel: 'Opening',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Failed extends StatelessWidget {
  const _Failed({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('Glasshouse could not open its data',
                    textAlign: TextAlign.center, style: GlassText.display(22, color: c.ink)),
                const SizedBox(height: 10),
                Text('Try again. If it keeps happening, reinstalling the app will fix it.',
                    textAlign: TextAlign.center, style: GlassText.body(15, color: c.ink2)),
                const SizedBox(height: 18),
                FilledButton(onPressed: onRetry, child: const Text('Try again')),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
