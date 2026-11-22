/// Everything the screens share: the data, the chosen place, the quiz answers.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'models.dart';
import 'place.dart';
import 'scoring.dart';

/// Where answers are kept between launches. They are political opinions, so
/// the only implementations write to the device itself and nowhere else.
abstract class AnswerStore {
  Future<String?> read();
  Future<void> write(String value);
}

class MemoryStore implements AnswerStore {
  String? value;
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String v) async => value = v;
}

/// One MP ranked against the visitor's answers.
class Ranked {
  const Ranked(this.member, this.match);
  final QuizMember member;
  final MatchResult match;
}

/// Which MP the match screen is about, and why.
enum FocusReason { yours, chosen, closest }

class Focused {
  const Focused(this.member, this.reason);
  final QuizMember member;
  final FocusReason reason;
}

class AppState extends ChangeNotifier {
  AppState({required this.data, this.quiz, AnswerStore? store})
      : _store = store ?? MemoryStore() {
    final q = quiz;
    if (q != null) {
      order = askingOrder(q.statements);
      for (final m in q.members) {
        compass[m.id] = placeOnCompass(q.statements, (i) => m.pos[i]);
      }
    } else {
      order = const [];
    }
  }

  final AppData data;
  final QuizData? quiz;
  final AnswerStore _store;

  /// Statement indices in the order they are asked.
  late final List<int> order;

  /// Every MP's compass position, computed once.
  final Map<int, CompassPoint> compass = {};

  Place? place;
  final Map<int, Answer> answers = {};
  int at = 0;
  int? focusId;
  bool started = false;

  /// Which of the four screens is showing. Not saved.
  int tab = 0;

  // ---- navigation ----
  void go(int index) {
    if (tab == index) return;
    tab = index;
    notifyListeners();
  }

  // ---- place ----
  void setPlace(Place? p) {
    place = p;
    focusId = null;
    _changed();
  }

  /// The areas shown on the representatives screen, with an example when the
  /// visitor has not chosen anywhere yet.
  ({Place place, bool isExample}) get shownPlace {
    final p = place;
    if (p != null && p.areas(data).isNotEmpty) return (place: p, isExample: false);
    final example = data.areas.firstWhere(
      (a) => a.parliament == kUkParliament,
      orElse: () => data.areas.first,
    );
    return (place: Place.area(example), isExample: true);
  }

  // ---- quiz ----
  Statement get current => quiz!.statements[order[at]];
  Answer? answerFor(Statement s) => answers[s.id];
  int get answeredCount => answers.values.where((a) => a.answered).length;
  bool get canShowMatch => quiz != null && answeredCount >= kMinAnswers;

  void start() {
    started = true;
    _changed();
  }

  void answer(double value) {
    final a = answers.putIfAbsent(current.id, Answer.new);
    a.value = value;
    a.skipped = false;
    _changed();
  }

  void skip() {
    final a = answers.putIfAbsent(current.id, Answer.new);
    a.value = null;
    a.skipped = true;
    a.important = false;
    _changed();
  }

  void setImportant(bool important) {
    answers.putIfAbsent(current.id, Answer.new).important = important;
    _changed();
  }

  /// Moves through the statements. Returns false at either end.
  bool step(int delta) {
    final next = at + delta;
    if (next < 0 || next >= order.length) return false;
    at = next;
    _changed();
    return true;
  }

  bool get atLast => at >= order.length - 1;

  void clearAnswers() {
    answers.clear();
    at = 0;
    started = false;
    focusId = null;
    _changed();
  }

  // ---- match ----
  MatchResult matchOf(QuizMember m) => matchFor(quiz!, m, answers);

  bool isEnough(MatchResult r) => enoughOverlap(r, answeredCount);

  /// Every MP with enough overlap, closest first.
  List<Ranked> ranked() {
    final q = quiz;
    if (q == null) return const [];
    final out = [
      for (final m in q.members) Ranked(m, matchFor(q, m, answers)),
    ].where((r) => isEnough(r.match)).toList();
    out.sort((a, b) {
      final byPct = b.match.pct!.compareTo(a.match.pct!);
      return byPct != 0 ? byPct : b.match.overlap.compareTo(a.match.overlap);
    });
    return out;
  }

  /// The visitor's own MP, if they have chosen a place with a Commons seat.
  QuizMember? get ownMp {
    final p = place;
    final q = quiz;
    if (p == null || q == null) return null;
    for (final a in p.areas(data)) {
      if (a.parliament == kUkParliament && a.members.isNotEmpty) {
        return q.byId[a.members.first.id];
      }
    }
    return null;
  }

  Focused? focus(List<Ranked> ranked) {
    final mine = ownMp;
    final chosen = focusId == null ? null : quiz?.byId[focusId];
    if (chosen != null) {
      return Focused(chosen, mine?.id == chosen.id ? FocusReason.yours : FocusReason.chosen);
    }
    if (mine != null) return Focused(mine, FocusReason.yours);
    return ranked.isEmpty ? null : Focused(ranked.first.member, FocusReason.closest);
  }

  void focusOn(int? memberId) {
    focusId = memberId;
    _changed();
  }

  CompassPoint get ownCompass {
    final q = quiz!;
    return placeOnCompass(q.statements, (i) => answers[q.statements[i].id]?.value);
  }

  // ---- saving ----
  void _changed() {
    notifyListeners();
    _store.write(jsonEncode({
      'answers': {for (final e in answers.entries) '${e.key}': e.value.toJson()},
      'at': at,
      'place': place?.toJson(),
      'mp': focusId,
      'started': started,
    }));
  }

  /// Loads whatever was saved, dropping anything the data no longer contains.
  Future<void> restore() async {
    final String? raw;
    try {
      raw = await _store.read();
    } on Object {
      return;
    }
    if (raw == null || raw.isEmpty) return;
    try {
      final j = jsonDecode(raw);
      if (j is! Map) return;
      final known = {for (final s in quiz?.statements ?? const <Statement>[]) s.id};
      final saved = j['answers'];
      if (saved is Map) {
        for (final e in saved.entries) {
          final id = int.tryParse(e.key.toString());
          if (id != null && known.contains(id) && e.value is Map) {
            answers[id] = Answer.fromJson((e.value as Map).cast<String, dynamic>());
          }
        }
      }
      final savedAt = j['at'];
      at = savedAt is int && savedAt >= 0 && savedAt < order.length ? savedAt : 0;
      started = j['started'] == true;
      final mp = j['mp'];
      focusId = mp is int && (quiz?.byId.containsKey(mp) ?? false) ? mp : null;
      final p = j['place'];
      if (p is Map) {
        final restored = Place.fromJson(p.cast<String, dynamic>());
        final keys = restored.keys.where(data.areaByKey.containsKey).toList();
        place = keys.isEmpty
            ? null
            : Place(label: restored.label, keys: keys, notes: restored.notes);
      }
    } on Object {
      // A corrupt save is not worth failing to start over.
      answers.clear();
      at = 0;
      started = false;
      focusId = null;
      place = null;
    }
    notifyListeners();
  }
}
