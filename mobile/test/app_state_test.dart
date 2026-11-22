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
    expect(s.at, quiz.statements.length - 1);
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
}
