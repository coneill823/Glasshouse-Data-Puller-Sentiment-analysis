/// The arithmetic behind the quiz: agreement, compass position, wording.
///
/// These are the same rules as the web app (app/index.html) and the Python
/// build (analysis/positions.py). test/scoring_test.dart holds them to the
/// same answers.
library;

import 'dart:math' as math;

import 'models.dart';

/// Fewer answers than this and no match is shown.
const int kMinAnswers = 5;

/// What a visitor said about one statement.
class Answer {
  Answer({this.value, this.skipped = false, this.important = false});

  factory Answer.fromJson(Map<String, dynamic> j) => Answer(
        value: j['v'] is num ? (j['v'] as num).toDouble() : null,
        skipped: j['skipped'] == true,
        important: j['imp'] == true,
      );

  /// +1 strongly agree … -1 strongly disagree; null if not answered.
  double? value;
  bool skipped;

  /// "This one matters a lot to me": counted twice.
  bool important;

  bool get answered => value != null;

  Map<String, dynamic> toJson() => {'v': value, 'skipped': skipped, 'imp': important};
}

/// The five answers, strongest agreement first.
const List<(String, double)> kAnswerScale = [
  ('Strongly agree', 1),
  ('Agree', 0.5),
  ('Neutral', 0),
  ('Disagree', -0.5),
  ('Strongly disagree', -1),
];

String answerLabel(double value) {
  for (final (label, v) in kAnswerScale) {
    if (v == value) return label.toLowerCase();
  }
  return '';
}

class MatchResult {
  const MatchResult(this.pct, this.overlap);

  /// 0–100, or null when there is nothing to compare.
  final double? pct;

  /// How many statements both the visitor and the member have a view on.
  final int overlap;
}

/// Agreement between a visitor's answers and one MP's votes.
///
/// On each statement both have a view on, agreement is 1 - |you - them| / 2,
/// so identical views score 1 and opposite ones 0. Statements marked as
/// mattering a lot count twice.
MatchResult matchFor(QuizData quiz, QuizMember member, Map<int, Answer> answers) {
  var sum = 0.0, weight = 0.0;
  var overlap = 0;
  for (var i = 0; i < quiz.statements.length; i++) {
    final answer = answers[quiz.statements[i].id];
    final you = answer?.value;
    if (you == null) continue;
    final them = i < member.pos.length ? member.pos[i] : null;
    if (them == null) continue;
    final w = answer!.important ? 2.0 : 1.0;
    sum += w * (1 - (you - them).abs() / 2);
    weight += w;
    overlap++;
  }
  return MatchResult(weight > 0 ? 100 * sum / weight : null, overlap);
}

/// A match is only shown when it rests on enough shared statements: at least
/// five (or everything answered, if fewer), and at least half of the answers.
bool enoughOverlap(MatchResult r, int answered) =>
    r.pct != null &&
    r.overlap >= math.min(answered, kMinAnswers) &&
    r.overlap * 2 >= answered;

class CompassPoint {
  const CompassPoint(this.econ, this.social, this.econWeight, this.socialWeight);

  /// -1 left … +1 right; null when no tagged statement has a value.
  final double? econ;

  /// -1 liberal … +1 authoritarian.
  final double? social;

  /// How many tagged statements each coordinate rests on.
  final double econWeight, socialWeight;

  bool get placed => econ != null && social != null;
}

/// Where a set of positions sits on the two axes. The SAME function places the
/// visitor (from their answers) and every MP (from their votes).
CompassPoint placeOnCompass(List<Statement> statements, double? Function(int index) valueAt) {
  var e = 0.0, en = 0.0, s = 0.0, sn = 0.0;
  for (var i = 0; i < statements.length; i++) {
    final v = valueAt(i);
    if (v == null) continue;
    final st = statements[i];
    if (st.econ != 0) {
      e += st.econ * v;
      en += st.econ.abs();
    }
    if (st.social != 0) {
      s += st.social * v;
      sn += st.social.abs();
    }
  }
  return CompassPoint(en > 0 ? e / en : null, sn > 0 ? s / sn : null, en, sn);
}

/// Votes actually cast in a string of vote codes (for, against, abstained).
int castCount(String codes) {
  var n = 0;
  for (final c in codes.codeUnits) {
    if (c == 0x66 || c == 0x61 || c == 0x62) n++; // f, a, b
  }
  return n;
}

/// Plain-English description of a position, in TheyWorkForYou's bands.
String band(double position, int votes) {
  if (votes == 1) {
    final what = position > 0 ? 'voted for' : position < 0 ? 'voted against' : 'abstained';
    return '$what (1 vote)';
  }
  final String words;
  if (position >= 0.9) {
    words = 'consistently voted for';
  } else if (position >= 0.7) {
    words = 'almost always voted for';
  } else if (position >= 0.2) {
    words = 'generally voted for';
  } else if (position > -0.2) {
    words = 'voted a mixture of for and against';
  } else if (position > -0.7) {
    words = 'generally voted against';
  } else if (position > -0.9) {
    words = 'almost always voted against';
  } else {
    words = 'consistently voted against';
  }
  return '$words ($votes votes)';
}

const Map<String, String> kVoteCodeLabels = {
  'f': 'For',
  'a': 'Against',
  'b': 'Abstained',
  'x': 'Absent',
  '.': 'Not an MP then',
};

/// The order statements are asked in.
///
/// Three lanes are taken in turn — statements that place you on the social
/// axis, on the economic axis, and the rest — so that nine answers are enough
/// for a compass position. Within a lane subjects rotate, best-evidenced
/// first, so that stopping early still leaves a spread.
List<int> askingOrder(List<Statement> statements) {
  final lanes = <List<int>>[[], [], []];
  for (var i = 0; i < statements.length; i++) {
    final s = statements[i];
    lanes[s.social != 0 ? 0 : s.econ != 0 ? 1 : 2].add(i);
  }
  final rotated = [for (final lane in lanes) _rotateSubjects(statements, lane)];
  final out = <int>[];
  var left = true;
  while (left) {
    left = false;
    for (final lane in rotated) {
      if (lane.isNotEmpty) {
        out.add(lane.removeAt(0));
        left = true;
      }
    }
  }
  return out;
}

List<int> _rotateSubjects(List<Statement> statements, List<int> indices) {
  final groups = <String, List<int>>{};
  final names = <String>[];
  for (final i in indices) {
    final g = statements[i].group;
    if (!groups.containsKey(g)) {
      groups[g] = [];
      names.add(g);
    }
    groups[g]!.add(i);
  }
  for (final g in names) {
    // ties fall back to the original order, so the result never depends on
    // how the sort happens to be implemented
    groups[g]!.sort((a, b) {
      final byTerm = statements[b].termVotes.compareTo(statements[a].termVotes);
      if (byTerm != 0) return byTerm;
      final byAll = statements[b].divisions.length.compareTo(statements[a].divisions.length);
      return byAll != 0 ? byAll : a.compareTo(b);
    });
  }
  names.sort((a, b) {
    final bySize = groups[b]!.length.compareTo(groups[a]!.length);
    return bySize != 0 ? bySize : a.compareTo(b);
  });
  final out = <int>[];
  var left = true;
  while (left) {
    left = false;
    for (final g in names) {
      final list = groups[g]!;
      if (list.isNotEmpty) {
        out.add(list.removeAt(0));
        left = true;
      }
    }
  }
  return out;
}

/// Labour/Co-operative MPs are Labour MPs.
String partyLabel(String party) =>
    party.toLowerCase().startsWith('labour') ? 'Labour' : party;

/// Sitting as an independent, or as Speaker, is the absence of a party.
bool isParty(String party) =>
    party.isNotEmpty && !RegExp(r'^(independent|speaker)', caseSensitive: false).hasMatch(party);

const Map<String, String> kShortParty = {
  'Scottish National Party': 'SNP',
  'Liberal Democrat': 'Lib Dem',
  'Social Democratic and Labour Party': 'SDLP',
  'Traditional Unionist Voice': 'TUV',
};
