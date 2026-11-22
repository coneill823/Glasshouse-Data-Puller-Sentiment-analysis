// The quiz arithmetic, held to the same answers as the website.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/scoring.dart';

Statement statement(int id, {double econ = 0, double social = 0, String group = 'g',
    int termVotes = 1, int divisions = 1}) =>
    Statement(
      id: id, name: 'S$id', text: 'statement $id', detail: '', link: '', group: group,
      freeVote: false, econ: econ, social: social, termVotes: termVotes,
      divisions: [for (var i = 0; i < divisions; i++) Division('k$id-$i', '2025-01-01', i, 't', 'agree')],
    );

QuizData quizOf(List<Statement> statements, List<QuizMember> members) =>
    QuizData.fromJson({
      'termStart': '2024-07-05',
      'votesAsOf': '2026-01-01',
      'statements': [
        for (final s in statements)
          {'id': s.id, 'name': s.name, 'text': s.text, 'group': s.group, 'econ': s.econ,
           'social': s.social, 'termVotes': s.termVotes, 'divisions': []},
      ],
      'members': [
        for (final m in members)
          {'id': m.id, 'name': m.name, 'party': m.party, 'area': m.area, 'pos': m.pos, 'votes': m.votes},
      ],
    });

QuizMember member(List<double?> pos) => QuizMember(
    id: 1, name: 'A Member', party: 'Party', area: 'Area', pos: pos,
    votes: [for (final _ in pos) 'f']);

void main() {
  group('agreement', () {
    final statements = [for (var i = 1; i <= 4; i++) statement(i)];
    final m = member([1, -1, null, 1 / 3]);
    final quiz = quizOf(statements, [m]);

    test('identical views score 1, opposite 0, and it is averaged', () {
      final answers = {1: Answer(value: 1), 2: Answer(value: 0.5), 3: Answer(value: 1), 4: Answer(value: 0)};
      final r = matchFor(quiz, quiz.members.first, answers);
      // s1: 1 - 0/2 = 1 | s2: 1 - 1.5/2 = 0.25 | s3: they never voted | s4: 1 - (1/3)/2
      expect(r.overlap, 3);
      expect(r.pct, closeTo(100 * (1 + 0.25 + (1 - 1 / 6)) / 3, 1e-9));
    });

    test('a statement that matters a lot counts twice', () {
      final answers = {1: Answer(value: 1), 2: Answer(value: 0.5, important: true), 4: Answer(value: 0)};
      final r = matchFor(quiz, quiz.members.first, answers);
      expect(r.pct, closeTo(100 * (1 + 2 * 0.25 + (1 - 1 / 6)) / 4, 1e-9));
    });

    test('skipped and unanswered statements are not evidence', () {
      final answers = {1: Answer(value: 1), 2: Answer(skipped: true), 3: Answer(important: true)};
      final r = matchFor(quiz, quiz.members.first, answers);
      expect((r.pct, r.overlap), (100.0, 1));
    });

    test('no shared statements means no match, not zero', () {
      final r = matchFor(quiz, quiz.members.first, {3: Answer(value: 1)});
      expect((r.pct, r.overlap), (null, 0));
    });

    test('a match needs enough shared statements to be shown', () {
      expect(enoughOverlap(const MatchResult(80, 5), 6), isTrue);
      expect(enoughOverlap(const MatchResult(80, 4), 6), isFalse);   // fewer than five
      expect(enoughOverlap(const MatchResult(80, 5), 12), isFalse);  // under half the answers
      expect(enoughOverlap(const MatchResult(80, 3), 3), isTrue);    // everything answered
      expect(enoughOverlap(const MatchResult(null, 0), 0), isFalse);
    });
  });

  group('compass', () {
    final statements = [
      statement(1, econ: -1), statement(2, econ: 1), statement(3, social: 1), statement(4),
    ];

    test('the same function places a visitor and an MP', () {
      final p = placeOnCompass(statements, (i) => [1.0, 1.0, -1.0, 1.0][i]);
      expect(p.econ, 0);            // for a left measure and for a right one
      expect(p.social, -1);         // against the one authoritarian measure
      expect((p.econWeight, p.socialWeight), (2.0, 1.0));
    });

    test('untagged statements never move anyone', () {
      final p = placeOnCompass(statements, (i) => i == 3 ? 1.0 : null);
      expect(p.placed, isFalse);
      expect((p.econWeight, p.socialWeight), (0.0, 0.0));
    });
  });

  group('wording', () {
    test('bands follow TheyWorkForYou', () {
      expect(band(1, 4), 'consistently voted for (4 votes)');
      expect(band(0.75, 8), 'almost always voted for (8 votes)');
      expect(band(0.5, 4), 'generally voted for (4 votes)');
      expect(band(0, 2), 'voted a mixture of for and against (2 votes)');
      expect(band(-0.5, 4), 'generally voted against (4 votes)');
      expect(band(-0.75, 8), 'almost always voted against (8 votes)');
      expect(band(-1, 3), 'consistently voted against (3 votes)');
    });

    test('one vote is described as one vote', () {
      expect(band(1, 1), 'voted for (1 vote)');
      expect(band(-1, 1), 'voted against (1 vote)');
      expect(band(0, 1), 'abstained (1 vote)');
    });

    test('only votes cast are counted', () {
      expect(castCount('ffa'), 3);
      expect(castCount('fb.x'), 2);
      expect(castCount('..xx'), 0);
    });

    test('parties', () {
      expect(partyLabel('Labour/Co-operative'), 'Labour');
      expect(isParty('Independent'), isFalse);
      expect(isParty('Speaker'), isFalse);
      expect(isParty('Plaid Cymru'), isTrue);
    });
  });

  group('asking order', () {
    test('lanes alternate so both axes are reached early', () {
      final statements = [
        statement(1, econ: -1, group: 'Tax'), statement(2, econ: -1, group: 'Tax'),
        statement(3, econ: 1, group: 'Welfare'), statement(4, social: 1, group: 'Home'),
        statement(5, social: -1, group: 'Justice'), statement(6, group: 'Reform'),
        statement(7, group: 'Environment'),
      ];
      final ids = [for (final i in askingOrder(statements)) statements[i].id];
      // social, economic, untagged, and round again; Tax has two so it leads its lane
      expect(ids, [4, 1, 7, 5, 3, 6, 2]);
    });

    test('within a subject the best-evidenced statement comes first', () {
      final statements = [
        statement(1, econ: 1, group: 'Tax', termVotes: 1),
        statement(2, econ: 1, group: 'Tax', termVotes: 5),
        statement(3, econ: 1, group: 'Tax', termVotes: 5, divisions: 9),
      ];
      expect(askingOrder(statements), [2, 1, 0]);
    });
  });

  group('parity with the Python build on real data', () {
    final fixture = jsonDecode(File('test/fixtures/quiz_slice.json').readAsStringSync())
        as Map<String, dynamic>;
    final quiz = QuizData.fromJson(fixture['quiz'] as Map<String, dynamic>);
    final answers = {
      for (final e in (fixture['answers'] as Map<String, dynamic>).entries)
        int.parse(e.key): Answer.fromJson(e.value as Map<String, dynamic>),
    };
    final expected = fixture['expected'] as Map<String, dynamic>;

    test('every MP in the slice gets the same match', () {
      final members = expected['members'] as Map<String, dynamic>;
      expect(members, hasLength(quiz.members.length));
      for (final m in quiz.members) {
        final want = members['${m.id}'] as Map<String, dynamic>;
        final got = matchFor(quiz, m, answers);
        expect(got.overlap, want['overlap'], reason: m.name);
        if (want['pct'] == null) {
          expect(got.pct, isNull, reason: m.name);
        } else {
          expect(got.pct, closeTo((want['pct'] as num).toDouble(), 1e-9), reason: m.name);
        }
      }
    });

    test('every MP in the slice gets the same compass position', () {
      final members = expected['members'] as Map<String, dynamic>;
      for (final m in quiz.members) {
        final want = (members['${m.id}'] as Map<String, dynamic>)['compass'] as List;
        final got = placeOnCompass(quiz.statements, (i) => m.pos[i]);
        _expectPoint(got, want, m.name);
      }
    });

    test('the visitor gets the same compass position', () {
      final got = placeOnCompass(quiz.statements, (i) => answers[quiz.statements[i].id]?.value);
      _expectPoint(got, expected['you'] as List, 'you');
      expect(answers.values.where((a) => a.answered).length, expected['answered']);
    });

    test('statements are asked in the same order', () {
      expect(askingOrder(quiz.statements), expected['order']);
    });
  });
}

void _expectPoint(CompassPoint got, List<dynamic> want, String who) {
  void same(double? a, Object? b) => b == null
      ? expect(a, isNull, reason: who)
      : expect(a, closeTo((b as num).toDouble(), 1e-9), reason: who);
  same(got.econ, want[0]);
  same(got.social, want[1]);
  expect(got.econWeight, (want[2] as num).toDouble(), reason: who);
  expect(got.socialWeight, (want[3] as num).toDouble(), reason: who);
}
