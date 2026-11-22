// Quiz state: answering, moving, saving and restoring.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/app_state.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/place.dart';
import 'package:glasshouse/core/scoring.dart';

final AppData data = AppData.fromJson(
    jsonDecode(File('assets/data/data.json').readAsStringSync()) as Map<String, dynamic>);
final QuizData quiz = QuizData.fromJson(
    jsonDecode(File('assets/data/quiz.json').readAsStringSync()) as Map<String, dynamic>);

AppState fresh([MemoryStore? store]) => AppState(data: data, quiz: quiz, store: store);

const String kAssembly = 'NI Assembly';
final QuizSet assembly = quiz.chambers[kAssembly]!;

/// Somewhere with an MP and several MLAs.
Place belfastSouth() => Place(label: 'Belfast South', keys: [
      data.areas.firstWhere((a) => a.parliament == kUkParliament && a.area.startsWith('Belfast South')).key,
      data.areaByKey['$kAssembly||Belfast South']!.key,
    ]);

/// Answers the next [n] questions of whichever part is open.
void answerSome(AppState s, int n, {double value = 1}) {
  for (var i = 0; i < n; i++) {
    s.answer(value);
    s.step(1);
  }
}

void main() {
  test('nine answers are enough for a compass position', () {
    final s = fresh();
    answerSome(s, 9);
    final own = s.ownCompass;
    expect(own.placed, isTrue);
    expect(own.econWeight, greaterThanOrEqualTo(3));
    expect(own.socialWeight, greaterThanOrEqualTo(3));
  });

  test('a match appears only once enough has been answered', () {
    final s = fresh();
    answerSome(s, kMinAnswers - 1);
    expect(s.canShowMatch, isFalse);
    s.answer(-1);
    expect(s.canShowMatch, isTrue);
    expect(s.ranked(), isNotEmpty);
  });

  test('skipping removes an answer and its importance', () {
    final s = fresh();
    s.answer(1);
    s.setImportant(true);
    expect(s.answeredCount, 1);
    s.skip();
    expect(s.answeredCount, 0);
    expect(s.answerFor(s.current)!.important, isFalse);
    expect(s.answerFor(s.current)!.skipped, isTrue);
  });

  test('stepping stops at both ends', () {
    final s = fresh();
    expect(s.step(-1), isFalse);
    expect(s.at, 0);
    while (s.step(1)) {}
    expect(s.atLast, isTrue);
    expect(s.at, quiz.commons.coreCount - 1); // the end of this part, not of everything
  });

  test('ranking is closest first and everyone ranked has enough overlap', () {
    final s = fresh();
    answerSome(s, 12, value: -1);
    final ranked = s.ranked();
    for (var i = 1; i < ranked.length; i++) {
      expect(ranked[i - 1].match.pct! >= ranked[i].match.pct!, isTrue);
    }
    expect(ranked.every((r) => s.isEnough(r.match)), isTrue);
  });

  test('your own MP is the focus once you have chosen a place', () {
    final s = fresh();
    answerSome(s, 8);
    final ranked = s.ranked();
    expect(s.focus(ranked)!.reason, FocusReason.closest);

    final seat = data.areas.firstWhere((a) => a.parliament == kUkParliament);
    s.setPlace(Place.area(seat));
    final mine = s.focus(ranked)!;
    expect((mine.reason, mine.member.id), (FocusReason.yours, seat.members.first.id));

    final other = ranked.firstWhere((r) => r.member.id != mine.member.id).member;
    s.focusOn(other.id);
    expect(s.focus(ranked)!.reason, FocusReason.chosen);
    s.focusOn(mine.member.id);     // arriving from your own MP's card
    expect(s.focus(ranked)!.reason, FocusReason.yours);
  });

  test('with no place chosen an example is shown and labelled as one', () {
    final shown = fresh().shownPlace;
    expect(shown.isExample, isTrue);
    expect(shown.place.areas(data).single.parliament, kUkParliament);
  });

  test('answers, position and place survive a restart', () async {
    final store = MemoryStore();
    final first = fresh(store);
    answerSome(first, 6, value: 0.5);
    first.setImportant(true);
    final seat = data.areas.firstWhere((a) => a.parliament == kUkParliament);
    first.setPlace(Place(label: 'AB1 2CD', keys: [seat.key], notes: const ['a note']));
    first.start();

    final second = fresh(store);
    await second.restore();
    expect(second.answeredCount, 6);
    expect(second.at, first.at);
    expect(second.started, isTrue);
    expect(second.place!.label, 'AB1 2CD');
    expect(second.place!.notes, ['a note']);
    expect(second.answerFor(second.current)!.important, isTrue);
    expect(second.matchOf(quiz.members.first).pct,
        closeTo(first.matchOf(quiz.members.first).pct!, 1e-12));
  });

  test('anything saved that the data no longer contains is dropped', () async {
    final store = MemoryStore()
      ..value = jsonEncode({
        'answers': {
          '-1': {'v': 1},                                   // a statement that has gone
          '${quiz.statements.first.id}': {'v': -1, 'imp': true},
        },
        'at': 9999,
        'mp': 123456789,
        'place': {'label': 'Gone', 'keys': ['Nowhere||At all']},
        'started': true,
      });
    final s = fresh(store);
    await s.restore();
    expect(s.answers.keys, [quiz.statements.first.id]);
    expect(s.at, 0);
    expect(s.focusId, isNull);
    expect(s.place, isNull);
  });

  test('a corrupt save does not stop the app starting', () async {
    final s = fresh(MemoryStore()..value = '{not json');
    await s.restore();
    expect(s.answers, isEmpty);
    expect(s.started, isFalse);
  });

  test('clearing answers starts the quiz again', () {
    final s = fresh();
    answerSome(s, 7);
    s.start();
    s.clearAnswers();
    expect((s.answeredCount, s.at, s.started), (0, 0, false));
  });

  group('parts of the quiz', () {
    test('each parliament has its own part, and earlier parliaments another', () {
      final s = fresh();
      expect(s.sections.first.id, kCommonsSection);
      expect(s.sections.map((p) => p.id), containsAll([kAssembly, 'Scottish Parliament', kEarlierSection]));
      final commons = s.sections.first, earlier = s.sections.firstWhere((p) => p.id == kEarlierSection);
      // Between them the two Commons parts ask every statement exactly once.
      expect([...commons.order, ...earlier.order]..sort(),
          [for (var i = 0; i < quiz.commons.statements.length; i++) i]);
      expect(commons.order.every((i) => i < quiz.commons.coreCount), isTrue);
      for (final part in s.sections.where((p) => p.isDevolved)) {
        expect(part.order.toSet(), hasLength(part.set.statements.length));
        expect(part.lead, 'I would have voted for…');
      }
    });

    test('the parliaments you are represented in are offered first', () {
      final s = fresh();
      expect(s.offered.map((p) => p.id).take(2), [kCommonsSection, kEarlierSection]);
      s.setPlace(belfastSouth());
      expect(s.offered.map((p) => p.id).take(3), [kCommonsSection, kAssembly, kEarlierSection]);
      expect(s.offered, hasLength(s.sections.length));
    });

    test('each part remembers where you were', () {
      final s = fresh();
      s.start();
      answerSome(s, 3);
      s.openSection(kAssembly);
      expect(s.at, 0);
      expect(s.current.id, assembly.statements[s.section.order.first].id);
      answerSome(s, 2);
      s.leaveSection();
      expect(s.started, isFalse);
      s.openSection(kCommonsSection);
      expect(s.at, 3);
      s.openSection(kAssembly);
      expect(s.at, 2);
      expect(s.answeredIn(s.section), 2);
      expect((s.answeredInSet(quiz.commons), s.answeredInSet(assembly), s.answeredCount), (3, 2, 5));
    });

    test('earlier parliaments count towards the same Commons match', () {
      final s = fresh();
      s.openSection(kEarlierSection);
      answerSome(s, kMinAnswers);
      expect(s.canShowMatch, isTrue);
      expect(s.answeredIn(s.sections.first), 0);
      // Sitting MPs who were there then are matched; those elected since are
      // not, and that is not held against them as a gap.
      final ranked = s.ranked();
      expect(ranked, isNotEmpty);
      expect(ranked.length, lessThan(quiz.members.length));
    });
  });

  group('a parliament of your own', () {
    test('answers about Westminster say nothing about your MLAs, and the reverse', () {
      final s = fresh()..setPlace(belfastSouth());
      expect(s.repsIn(quiz.commons), hasLength(1));
      expect(s.repsIn(assembly).length, greaterThan(3));
      s.start();
      answerSome(s, 8);
      expect(s.canShowMatchFor(quiz.commons), isTrue);
      expect(s.canShowMatchFor(assembly), isFalse);
      expect(s.hasAnyMatch, isTrue);
      for (final mla in s.repsIn(assembly)) {
        expect(s.matchOf(mla, assembly).pct, isNull, reason: mla.name);
      }
    });

    test('answering the Assembly\'s votes gives every MLA who voted a match', () {
      final s = fresh()..setPlace(belfastSouth());
      s.openSection(kAssembly);
      answerSome(s, assembly.statements.length);
      expect(s.canShowMatchFor(assembly), isTrue);
      expect(s.canShowMatch, isFalse); // nothing answered about the Commons
      final mine = s.repsIn(assembly);
      final matched = [for (final m in mine) if (s.isEnough(s.matchOf(m, assembly), assembly)) m];
      // More than one person to compare: the point of the whole exercise.
      expect(matched.length, greaterThan(2));
      for (final m in mine) {
        final r = s.matchOf(m, assembly);
        final voted = m.pos.where((p) => p != null).length;
        expect(r.overlap, voted, reason: m.name);
        expect(r.eligible, assembly.statements.length, reason: m.name);
      }
      final ranked = s.ranked(assembly);
      expect(ranked.every((r) => s.isEnough(r.match, assembly)), isTrue);
      for (var i = 1; i < ranked.length; i++) {
        expect(ranked[i - 1].match.pct! >= ranked[i].match.pct!, isTrue);
      }
    });

    test('its results are about your own closest member unless you pick another', () {
      final s = fresh()..setPlace(belfastSouth());
      s.openSection(kAssembly);
      answerSome(s, 12, value: -1);
      final ranked = s.ranked(assembly);
      final mine = {for (final m in s.repsIn(assembly)) m.id};
      final focus = s.focusIn(assembly, ranked)!;
      expect(mine, contains(focus.id));
      expect(focus.id, ranked.firstWhere((r) => mine.contains(r.member.id)).member.id);

      final someoneElse = ranked.firstWhere((r) => !mine.contains(r.member.id)).member;
      s.focusOnIn(assembly, someoneElse.id);
      expect(s.focusIn(assembly, ranked)!.id, someoneElse.id);
      s.setPlace(belfastSouth()); // choosing a place again starts over
      expect(mine, contains(s.focusIn(assembly, ranked)!.id));
    });

    test('with no place chosen its results are about whoever is closest', () {
      final s = fresh();
      s.openSection(kAssembly);
      answerSome(s, 10);
      final ranked = s.ranked(assembly);
      expect(s.focusIn(assembly, ranked)!.id, ranked.first.member.id);
    });

    test('going to one member\'s match opens the match screen at their parliament', () {
      final s = fresh()..setPlace(belfastSouth());
      final mla = s.repsIn(assembly).first;
      s.showMatchFor(assembly, mla.id);
      expect((s.tab, s.reveal), (2, kAssembly));
      expect(s.focusIn(assembly, const [])!.id, mla.id);
      final mp = s.repsIn(quiz.commons).single;
      s.showMatchFor(quiz.commons, mp.id);
      expect((s.focusId, s.reveal), (mp.id, kUkParliament));
    });
  });

  group('a member who skipped most of it', () {
    // There are a handful in the Commons: the Speaker and deputies, who do
    // not vote, and some MPs who take part in few votes.
    QuizMember partialMp() => quiz.members.firstWhere((m) {
          final core = m.pos.take(quiz.commons.coreCount);
          final voted = core.where((p) => p != null).length;
          return voted >= kMinAnswers + 2 && voted * 3 < quiz.commons.coreCount;
        });

    test('their own constituents still see a figure, and what it rests on', () {
      final mp = partialMp();
      final s = fresh()..setPlace(Place.area(data.areaByKey[data.memberById[mp.id]!.areaKey]!));
      s.start();
      answerSome(s, quiz.commons.coreCount);
      final r = s.matchOf(mp);
      expect(r.pct, isNotNull);
      expect(r.overlap, mp.pos.take(quiz.commons.coreCount).where((p) => p != null).length);
      expect(r.eligible, quiz.commons.coreCount); // they were an MP for all of it
      expect(s.isShown(r), isTrue);
      expect(s.isEnough(r), isFalse);
      expect(s.focus(s.ranked())!.member.id, mp.id);
    });

    test('but they are not ranked among the closest, however well they score', () {
      final mp = partialMp();
      final s = fresh();
      // Agree with every vote they cast: a perfect score on a thin record.
      for (final i in s.sections.first.order) {
        final theirs = mp.pos[i];
        s.answer(theirs == null ? 1 : (theirs >= 0 ? 1 : -1));
        s.step(1);
      }
      expect(s.matchOf(mp).pct, greaterThan(80));
      final ranked = s.ranked();
      expect(ranked.any((r) => r.member.id == mp.id), isFalse);
      expect(ranked.every((r) => r.match.overlap * 2 >= r.match.eligible), isTrue);
    });
  });

  group('people who have left', () {
    test('a former MP is matched on what they voted on, and placed on the compass', () {
      final s = fresh();
      final former = quiz.commons.former.reduce(
          (a, b) => a.pos.where((p) => p != null).length >= b.pos.where((p) => p != null).length ? a : b);
      expect(quiz.byId[former.id], same(former));
      expect(s.compass.containsKey(former.id), isFalse); // only sitting MPs are worked out up front
      expect(s.compassOf(former).placed, isTrue);
      s.openSection(kEarlierSection);
      answerSome(s, 30);
      final r = s.matchOf(former);
      expect(r.overlap, greaterThan(kMinAnswers));
      expect(s.isEnough(r), isTrue);
      expect(s.ranked().any((x) => x.member.id == former.id), isFalse); // the list is of sitting MPs
      s.focusOn(former.id);
      expect(s.focus(s.ranked())!.reason, FocusReason.chosen);
    });
  });

  group('saving', () {
    test('where you were in every part survives a restart', () async {
      final store = MemoryStore();
      final first = fresh(store)..setPlace(belfastSouth());
      first.start();
      answerSome(first, 4);
      first.openSection(kAssembly);
      answerSome(first, 6, value: -0.5);

      final second = fresh(store);
      await second.restore();
      expect((second.sectionId, second.at, second.started), (kAssembly, 6, true));
      expect(second.answeredInSet(assembly), 6);
      second.openSection(kCommonsSection);
      expect(second.at, 4);
      expect(second.place!.areas(data), hasLength(2));
    });

    test('a save from before there were parts still opens where it was', () async {
      final ids = [for (final i in fresh().sections.first.order.take(3)) quiz.commons.statements[i].id];
      final store = MemoryStore()
        ..value = jsonEncode({
          'answers': {for (final id in ids) '$id': {'v': 1}},
          'at': 3,
          'started': true,
        });
      final s = fresh(store);
      await s.restore();
      expect((s.sectionId, s.at, s.started, s.answeredCount), (kCommonsSection, 3, true, 3));
    });

    test('a part that no longer exists is forgotten', () async {
      final store = MemoryStore()
        ..value = jsonEncode({
          'answers': <String, dynamic>{},
          'ats': {'A parliament that has gone': 4, kAssembly: 9999, kCommonsSection: 2},
          'section': 'A parliament that has gone',
          'started': true,
        });
      final s = fresh(store);
      await s.restore();
      expect((s.sectionId, s.at), (kCommonsSection, 2));
      s.openSection(kAssembly);
      expect(s.at, 0);
    });
  });
}
