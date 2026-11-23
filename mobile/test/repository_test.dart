// Which downloaded data the app will trust. Every installed copy fetches
// newer files by itself, so this rule decides what all of them show.
import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/repository.dart';

import 'support.dart';

void main() {
  Map<String, dynamic> data() => readJson('assets/data/data.json');
  Map<String, dynamic> quiz() => readJson('assets/data/quiz.json');

  test('the pair the app ships with is one it would accept', () {
    expect(usablePair(data(), quiz()), isTrue);
  });

  test('a pair from before the quiz had parts is refused, not half-used', () {
    // It would load, but with no devolved questions, no earlier statements
    // and nobody but sitting members: the app keeps what it shipped with.
    expect(usablePair(data()..remove('schema'), quiz()), isFalse);
    expect(usablePair(data(), quiz()..remove('schema')), isFalse);
    expect(usablePair(data()..['schema'] = 1, quiz()), isFalse);
    expect(usablePair(data(), quiz()..['schema'] = 1), isFalse);
    expect(usablePair(data()..['schema'] = '2', quiz()), isFalse); // a number, not text
  });

  test('a later shape that keeps what this one reads is accepted', () {
    expect(usablePair(data()..['schema'] = 3, quiz()..['schema'] = 3), isTrue);
  });

  test('two files built at different times are not mixed', () {
    final other = quiz()..['votesAsOf'] = '1999-01-01';
    expect(usablePair(data(), other), isFalse);
    expect(usablePair(data()..remove('sources'), quiz()), isFalse);
  });

  test('a file cut short in transit is refused', () {
    expect(usablePair(data()..['members'] = (data()['members'] as List).take(40).toList(), quiz()),
        isFalse);
    expect(usablePair(data(), quiz()..['statements'] = <dynamic>[]), isFalse);
    expect(usablePair(data(), quiz()..['members'] = (quiz()['members'] as List).take(40).toList()),
        isFalse);
    expect(usablePair(<String, dynamic>{}, <String, dynamic>{}), isFalse);
  });
}
