/// Hands the app's state, and the postcode service, to every screen.
library;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/postcode.dart';

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({
    super.key,
    required AppState state,
    required this.postcodes,
    required super.child,
  }) : super(notifier: state);

  final PostcodeLookup postcodes;

  /// The state, rebuilding the caller whenever it changes.
  static AppState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// The state, without subscribing: for use in callbacks.
  static AppState read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;

  static PostcodeLookup postcodesOf(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppScope>()!.postcodes;
}
