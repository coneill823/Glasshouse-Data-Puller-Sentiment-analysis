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

/// One member ranked against the visitor's answers.
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

const String kCommonsSection = 'commons';
const String kEarlierSection = 'earlier';

/// One part of the quiz a visitor can work through: this parliament's
/// statements, a devolved legislature's votes, or earlier parliaments.
class QuizSection {
  const QuizSection({
    required this.id,
    required this.set,
    required this.order,
    required this.title,
    required this.blurb,
    required this.lead,
  });

  final String id;

  /// The quiz these statements belong to, and whose members they match.
  final QuizSet set;

  /// Indices into the set's statements, in the order they are asked.
  final List<int> order;
  final String title, blurb;

  /// What comes before each statement: "I support…".
  final String lead;

  bool get isDevolved => !set.isCommons;
  Statement statementAt(int position) => set.statements[order[position]];
}

class AppState extends ChangeNotifier {
  AppState({required this.data, this.quiz, AnswerStore? store})
      : _store = store ?? MemoryStore() {
    final q = quiz;
    if (q == null) return;
    final commons = q.commons;
    final since = commons.termStart.length >= 4 ? commons.termStart.substring(0, 4) : '';
    final order = fullOrder(commons.statements, commons.coreCount);
    sections.add(QuizSection(
      id: kCommonsSection,
      set: commons,
      order: order.sublist(0, commons.coreCount),
      title: 'House of Commons',
      blurb: '${commons.coreCount} statements MPs have voted on'
          '${since.isEmpty ? ' this parliament' : ' since $since'}.',
      lead: 'I support…',
    ));
    for (final set in q.chambers.values) {
      final house = data.chamber(set.parliament)?.house ?? set.parliament;
      sections.add(QuizSection(
        id: set.parliament,
        set: set,
        order: askingOrder(set.statements),
        title: house,
        blurb: '${set.statements.length} votes it actually held. Say how you would have voted.',
        lead: 'I would have voted for…',
      ));
    }
    final more = commons.statements.length - commons.coreCount;
    if (more > 0) {
      sections.add(QuizSection(
        id: kEarlierSection,
        set: commons,
        order: order.sublist(commons.coreCount),
        title: 'Earlier parliaments',
        blurb: '$more more statements, voted on before'
            '${since.isEmpty ? ' this parliament' : ' $since'}: tuition fees, Iraq, identity '
            'cards. They sharpen your place on the compass and reach MPs\' longer records.',
        lead: 'I support…',
      ));
    }
    for (final m in commons.members) {
      compass[m.id] = placeOnCompass(commons.statements, (i) => m.pos[i]);
    }
  }

  final AppData data;
  final QuizData? quiz;
  final AnswerStore _store;

  /// The parts of the quiz, in the order they are offered.
  final List<QuizSection> sections = [];

  /// Every sitting MP's compass position, computed once.
  final Map<int, CompassPoint> compass = {};

  Place? place;
  final Map<int, Answer> answers = {};

  /// Which part of the quiz is open, and how far through each one is.
  String sectionId = kCommonsSection;
  final Map<String, int> _at = {};

  /// Whether a part of the quiz is open, rather than the list of parts.
  bool started = false;

  /// The MP the match screen is about, if the visitor chose one.
  int? focusId;

  /// The member each devolved match is about. Not saved.
  final Map<String, int> _focusIn = {};

  /// Which of the four screens is showing. Not saved.
  int tab = 0;

  /// The parliament whose results the match screen should open at, set when
  /// the visitor arrives there from one member's own page. Not saved.
  String? reveal;

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
    _focusIn.clear();
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

  /// Whether the chosen place has representatives in this legislature.
  bool hasRepsIn(QuizSet set) =>
      place?.areas(data).any((a) => a.parliament == set.parliament) ?? false;

  /// The visitor's own representatives in a legislature.
  List<QuizMember> repsIn(QuizSet set) => [
        for (final a in place?.areas(data) ?? const <Area>[])
          if (a.parliament == set.parliament)
            for (final m in a.members)
              if (set.byId[m.id] != null) set.byId[m.id]!,
      ];

  // ---- quiz ----
  QuizSection get section =>
      sections.firstWhere((s) => s.id == sectionId, orElse: () => sections.first);
  QuizSection? sectionFor(QuizSet set) {
    for (final s in sections) {
      if (identical(s.set, set) && s.id != kEarlierSection) return s;
    }
    return null;
  }

  /// The parts of the quiz, those for the visitor's own parliaments first.
  List<QuizSection> get offered {
    final mine = [for (final s in sections) if (s.isDevolved && hasRepsIn(s.set)) s];
    final theirs = [for (final s in sections) if (s.isDevolved && !hasRepsIn(s.set)) s];
    return [
      for (final s in sections) if (s.id == kCommonsSection) s,
      ...mine,
      for (final s in sections) if (s.id == kEarlierSection) s,
      ...theirs,
    ];
  }

  int get at => positionIn(section);
  int positionIn(QuizSection s) => (_at[s.id] ?? 0).clamp(0, s.order.isEmpty ? 0 : s.order.length - 1);
  Statement get current => section.statementAt(at);
  Answer? answerFor(Statement s) => answers[s.id];

  /// Answers given so far, anywhere.
  int get answeredCount => answers.values.where((a) => a.answered).length;

  /// Answers given to one part of the quiz.
  int answeredIn(QuizSection s) {
    var n = 0;
    for (final i in s.order) {
      if (answers[s.set.statements[i].id]?.answered ?? false) n++;
    }
    return n;
  }

  /// Answers given to a whole quiz: for the Commons, both of its parts.
  int answeredInSet(QuizSet set) {
    var n = 0;
    for (final s in set.statements) {
      if (answers[s.id]?.answered ?? false) n++;
    }
    return n;
  }

  bool canShowMatchFor(QuizSet set) => answeredInSet(set) >= kMinAnswers;
  bool get canShowMatch => quiz != null && canShowMatchFor(quiz!.commons);

  /// Whether there is any match to show at all.
  bool get hasAnyMatch => quiz != null && quiz!.sets.any(canShowMatchFor);

  /// Opens a part of the quiz where the visitor left it.
  void openSection(String id) {
    if (sections.any((s) => s.id == id)) sectionId = id;
    started = true;
    _changed();
  }

  void start() => openSection(sectionId);

  /// Back to the list of parts.
  void leaveSection() {
    started = false;
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

  /// Moves through the open part's statements. Returns false at either end.
  bool step(int delta) {
    final next = at + delta;
    if (next < 0 || next >= section.order.length) return false;
    _at[section.id] = next;
    _changed();
    return true;
  }

  bool get atLast => at >= section.order.length - 1;

  void clearAnswers() {
    answers.clear();
    _at.clear();
    sectionId = kCommonsSection;
    started = false;
    focusId = null;
    _focusIn.clear();
    _changed();
  }

  // ---- match ----
  MatchResult matchOf(QuizMember m, [QuizSet? set]) =>
      matchFor(set ?? quiz!.commons, m, answers);

  /// Whether there is a figure to show for this member at all.
  bool isShown(MatchResult r, [QuizSet? set]) =>
      showable(r, answeredInSet(set ?? quiz!.commons));

  /// Whether it also rests on enough of their record to be ranked.
  bool isEnough(MatchResult r, [QuizSet? set]) =>
      enoughOverlap(r, answeredInSet(set ?? quiz!.commons));

  /// Every sitting member whose record covers enough of what was answered
  /// to be compared with the rest, closest first.
  List<Ranked> ranked([QuizSet? of]) {
    final q = quiz;
    if (q == null) return const [];
    final set = of ?? q.commons;
    final answered = answeredInSet(set);
    final out = [
      for (final m in set.members) Ranked(m, matchFor(set, m, answers)),
    ].where((r) => enoughOverlap(r.match, answered)).toList();
    out.sort((a, b) {
      final byPct = b.match.pct!.compareTo(a.match.pct!);
      return byPct != 0 ? byPct : b.match.overlap.compareTo(a.match.overlap);
    });
    return out;
  }

  /// The visitor's own MP, if they have chosen a place with a Commons seat.
  QuizMember? get ownMp {
    final q = quiz;
    if (q == null) return null;
    final mine = repsIn(q.commons);
    return mine.isEmpty ? null : mine.first;
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

  /// The member a devolved legislature's results are about: the one the
  /// visitor picked, else whichever of their own representatives voted most
  /// like them, else the closest of anyone.
  QuizMember? focusIn(QuizSet set, List<Ranked> ranked) {
    final chosen = set.byId[_focusIn[set.parliament]];
    if (chosen != null) return chosen;
    final mine = repsIn(set);
    QuizMember? best;
    var bestPct = -1.0;
    for (final m in mine) {
      final r = matchOf(m, set);
      if (isShown(r, set) && r.pct! > bestPct) {
        best = m;
        bestPct = r.pct!;
      }
    }
    if (best != null) return best;
    if (mine.isNotEmpty) return mine.first;
    return ranked.isEmpty ? null : ranked.first.member;
  }

  void focusOnIn(QuizSet set, int memberId) {
    _focusIn[set.parliament] = memberId;
    notifyListeners();
  }

  /// Whether the visitor picked the member a legislature's results are about.
  bool pickedIn(QuizSet set) => set.byId[_focusIn[set.parliament]] != null;

  /// Goes to the match screen, at one member's results.
  void showMatchFor(QuizSet set, int memberId) {
    if (set.isCommons) {
      focusId = memberId;
    } else {
      _focusIn[set.parliament] = memberId;
    }
    reveal = set.parliament;
    tab = 2;
    _changed();
  }

  /// Where an MP's votes sit. Sitting MPs are worked out once, at the start;
  /// a former one only when someone asks about them.
  CompassPoint compassOf(QuizMember m) {
    final known = compass[m.id];
    if (known != null) return known;
    final statements = quiz!.commons.statements;
    return placeOnCompass(statements, (i) => i < m.pos.length ? m.pos[i] : null);
  }

  CompassPoint get ownCompass {
    final statements = quiz!.commons.statements;
    return placeOnCompass(statements, (i) => answers[statements[i].id]?.value);
  }

  // ---- saving ----
  void _changed() {
    notifyListeners();
    _store.write(jsonEncode({
      'answers': {for (final e in answers.entries) '${e.key}': e.value.toJson()},
      'at': _at[kCommonsSection] ?? 0,
      'ats': _at,
      'section': sectionId,
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
      final known = {
        for (final set in quiz?.sets ?? const <QuizSet>[])
          for (final s in set.statements) s.id,
      };
      final saved = j['answers'];
      if (saved is Map) {
        for (final e in saved.entries) {
          final id = int.tryParse(e.key.toString());
          if (id != null && known.contains(id) && e.value is Map) {
            answers[id] = Answer.fromJson((e.value as Map).cast<String, dynamic>());
          }
        }
      }
      // How far through each part. Before there were parts there was one
      // number, for the Commons.
      final ats = j['ats'];
      if (ats is Map) {
        for (final e in ats.entries) {
          if (e.value is int) _at[e.key.toString()] = e.value as int;
        }
      } else if (j['at'] is int) {
        _at[kCommonsSection] = j['at'] as int;
      }
      for (final s in sections) {
        final saved = _at[s.id];
        if (saved != null && (saved < 0 || saved >= s.order.length)) _at.remove(s.id);
      }
      _at.removeWhere((id, _) => !sections.any((s) => s.id == id));
      final section = j['section'];
      sectionId = section is String && sections.any((s) => s.id == section)
          ? section
          : kCommonsSection;
      started = j['started'] == true && sections.isNotEmpty;
      final mp = j['mp'];
      focusId = mp is int && (quiz?.byId.containsKey(mp) ?? false) ? mp : null;
      final p = j['place'];
      if (p is Map) {
        final restored = Place.fromJson(p.cast<String, dynamic>());
        final keys = restored.keys.where(data.areaByKey.containsKey).toList();
        place = keys.isEmpty
            ? null
            : Place(
                label: restored.label,
                keys: keys,
                notes: restored.notes,
                codes: restored.codes,
                ward: restored.ward,
                district: restored.district,
              );
      }
    } on Object {
      // A corrupt save is not worth failing to start over.
      answers.clear();
      _at.clear();
      sectionId = kCommonsSection;
      started = false;
      focusId = null;
      place = null;
    }
    notifyListeners();
  }
}
