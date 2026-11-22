// The bundled data files parse, and names can be found however they are typed.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/place.dart';
import 'package:glasshouse/core/scoring.dart';
import 'package:glasshouse/core/text.dart';

import 'support.dart';

void main() {
  test('part of a postcode is told apart from a whole one and from a name', () {
    for (final whole in ['G12 8QQ', 'g128qq', 'SW1A 0AA', 'M1 1AE', 'BT7 1NN']) {
      expect(looksLikePostcode(whole), isTrue, reason: whole);
      expect(looksLikePartPostcode(whole), isFalse, reason: whole);
    }
    for (final part in ['G1', 'G12', 'G12 8', 'g12 8q', 'SW1A', 'SW1A 0', 'BT7']) {
      expect(looksLikePartPostcode(part), isTrue, reason: part);
      expect(looksLikePostcode(part), isFalse, reason: part);
    }
    for (final name in ['G', 'Glasgow', 'Bath', 'Ely', 'M', 'St Ives', '12']) {
      expect(looksLikePartPostcode(name), isFalse, reason: name);
    }
  });

  group('text', () {
    test('accents, case and punctuation do not matter', () {
      expect(norm('Ynys Môn'), 'ynys mon');
      expect(norm('Sinéad McLaughlin'), 'sinead mclaughlin');
      expect(norm('Llŷr Gruffydd'), 'llyr gruffydd');
      expect(norm('Carál Ní Chuilín'), 'caral ni chuilin');
      expect(norm("O'Toole, Matthew"), 'o toole matthew');
      expect(norm('Health & social care'), 'health and social care');
      expect(norm('Môn'), 'mon'); // a letter followed by a combining mark
      expect(norm(null), '');
    });

    test('postcodes', () {
      for (final ok in ['BT7 1NN', 'bt71nn', 'G12 8QQ', 'SW1A 0AA', 'M1 1AE', ' EH99 1SP ']) {
        expect(looksLikePostcode(ok), isTrue, reason: ok);
      }
      for (final no in ['Glasgow North', 'BT7', 'Ynys Môn', '12345', '']) {
        expect(looksLikePostcode(no), isFalse, reason: no);
      }
    });

    test('numbers', () {
      expect(thousands(1234567), '1,234,567');
      expect(thousands(646), '646');
      expect(thousands(null), '—');
    });
  });

  group('bundled data', () {
    final data = AppData.fromJson(
        jsonDecode(File('assets/data/data.json').readAsStringSync()) as Map<String, dynamic>);
    final quiz = QuizData.fromJson(
        jsonDecode(File('assets/data/quiz.json').readAsStringSync()) as Map<String, dynamic>);

    test('every legislature is present with its members', () {
      expect(data.chambers.keys, containsAll([kUkParliament, 'Scottish Parliament',
          'Welsh Parliament (Senedd)', 'NI Assembly']));
      expect(data.members.where((m) => m.parliament == kUkParliament), hasLength(650));
      expect(data.roleOf('NI Assembly'), 'MLA');
      expect(data.sources.votesAsOf, isNotEmpty);
    });

    test('each Commons seat has exactly one MP and an official code', () {
      final uk = data.areas.where((a) => a.parliament == kUkParliament).toList();
      expect(uk, hasLength(650));
      expect(uk.every((a) => a.members.length == 1), isTrue);
      expect(data.areaByGss, hasLength(650));
    });

    test('Scottish regional lists are told apart from constituencies', () {
      final regions = data.areas.where((a) => a.isRegion).toList();
      expect(regions, hasLength(8));
      expect(regions.every((a) => a.members.length > 1), isTrue);
    });

    test('the quiz lines up with the data', () {
      expect(quiz.statements.length, greaterThan(10));
      expect(quiz.members, hasLength(650));
      for (final m in quiz.members) {
        expect(m.pos, hasLength(quiz.statements.length), reason: m.name);
        expect(m.votes, hasLength(quiz.statements.length), reason: m.name);
        expect(data.memberById.containsKey(m.id), isTrue, reason: m.name);
      }
      for (final s in quiz.statements) {
        expect(s.text, isNotEmpty);
        expect(s.divisions, isNotEmpty, reason: s.name);
      }
    });

    test('a position is always backed by votes cast', () {
      for (final m in quiz.members) {
        for (var i = 0; i < m.pos.length; i++) {
          final cast = RegExp('[fab]').allMatches(m.votes[i]).length;
          expect(m.pos[i] == null, cast == 0, reason: '${m.name} / ${quiz.statements[i].name}');
          // one mark per division, or nothing at all if they sat for none of them
          expect(m.votes[i].length, anyOf(0, quiz.statements[i].divisions.length));
          if (m.votes[i].isEmpty) expect(m.pos[i], isNull);
        }
      }
    });

    test('search finds areas and people, with or without accents', () {
      expect(data.search('ynys mon').map((a) => a.area), contains('Ynys Môn'));
      expect(data.search('Glasgow North').first.area, 'Glasgow North');
      expect(data.search('x'), isEmpty); // too short to mean anything
      final abbott = data.search('diane abbott');
      expect(abbott, hasLength(1));
      expect(abbott.first.members.first.name, 'Diane Abbott');
    });

    test('a place lists the Commons seat before devolved ones and regions', () {
      final region = data.areas.firstWhere((a) => a.isRegion);
      final uk = data.areas.firstWhere((a) => a.parliament == kUkParliament);
      final seat = data.areas.firstWhere(
          (a) => a.parliament == 'Scottish Parliament' && !a.isRegion);
      final place = Place(label: 'X', keys: [region.key, 'gone||nowhere', seat.key, uk.key]);
      expect(place.areas(data), [uk, seat, region]);
    });

    test('receipts link to the division', () {
      final withReceipt = data.members.firstWhere(
          (m) => m.parliament == kUkParliament && m.receipts.isNotEmpty);
      expect(withReceipt.receipts.first.url,
          startsWith('https://votes.theyworkforyou.com/decisions/division/commons/'));
      expect(divisionUrlFromKey(null), isNull);
      expect(divisionUrlFromKey('not-a-key'), isNull);
    });
  });

  group('a quiz for each parliament', () {
    final data = bundledData;
    final quiz = bundledQuiz;

    test('the three devolved legislatures each have questions and members', () {
      expect(quiz.chambers.keys,
          containsAll(['Scottish Parliament', 'Welsh Parliament (Senedd)', 'NI Assembly']));
      expect(quiz.sets.first, same(quiz.commons));
      expect(quiz.setFor(kUkParliament), same(quiz.commons));
      expect(quiz.setFor('NI Assembly'), same(quiz.chambers['NI Assembly']));
      expect(quiz.setFor('House of Lords'), isNull);
    });

    test('no two questions anywhere share an id', () {
      // Answers are kept by statement id, across every parliament at once.
      final ids = [for (final set in quiz.sets) for (final s in set.statements) s.id];
      expect(ids.toSet(), hasLength(ids.length));
    });

    test('a devolved question is one vote, with its result and a link to the record', () {
      for (final set in quiz.chambers.values) {
        expect(set.statements.length, inInclusiveRange(kMinAnswers, 30), reason: set.parliament);
        for (final s in set.statements) {
          final why = '${set.parliament}: ${s.name}';
          expect(s.divisions, hasLength(1), reason: why);
          expect(s.divisions.single.ayeSupports, isTrue, reason: why);
          expect(s.divisions.single.url, startsWith('https://'), reason: why);
          expect(s.result, hasLength(2), reason: why);
          // the house really divided: at least one in ten on the losing side
          final ayes = s.result[0], noes = s.result[1];
          expect(10 * (ayes < noes ? ayes : noes) >= ayes + noes, isTrue, reason: why);
          expect(s.text, isNotEmpty, reason: why);
          expect(['Bill', 'Motion'], contains(s.group), reason: why);
          expect((s.econ, s.social), (0.0, 0.0), reason: why); // the compass is Commons only
        }
      }
    });

    test('every member of a devolved quiz is someone sitting there, one mark per vote', () {
      for (final set in quiz.chambers.values) {
        expect(set.members, isNotEmpty, reason: set.parliament);
        for (final m in set.members) {
          final why = '${set.parliament}: ${m.name}';
          expect(data.memberById[m.id]?.parliament, set.parliament, reason: why);
          expect(m.pos, hasLength(set.statements.length), reason: why);
          expect(m.votes, hasLength(set.statements.length), reason: why);
          for (var i = 0; i < m.pos.length; i++) {
            expect(m.pos[i] == null, castCount(m.votes[i]) == 0, reason: why);
            if (m.pos[i] != null) expect([-1.0, 0.0, 1.0], contains(m.pos[i]), reason: why);
          }
        }
      }
    });

    test('in each, most members have enough votes to be matched', () {
      // New parliaments start thin: members first elected in 2026 did not
      // vote on questions from the term before. Northern Ireland has had a
      // whole term.
      final ni = quiz.chambers['NI Assembly']!;
      final matched = ni.members.where((m) => m.pos.where((p) => p != null).length >= kMinAnswers);
      expect(matched.length / ni.members.length, greaterThan(0.9));
      for (final set in quiz.chambers.values) {
        expect(set.members.any((m) => m.pos.where((p) => p != null).length >= kMinAnswers), isTrue,
            reason: set.parliament);
      }
    });

    test('the Commons asks about this parliament first and earlier ones after', () {
      final commons = quiz.commons;
      expect(commons.coreCount, inExclusiveRange(10, commons.statements.length));
      for (final (i, s) in commons.statements.indexed) {
        expect(s.termVotes > 0, i < commons.coreCount, reason: s.name);
      }
    });

    test('former MPs carry the years they sat and a position on something', () {
      final former = quiz.commons.former;
      expect(former.length, greaterThan(500));
      for (final m in former) {
        expect(m.former, isTrue);
        expect(m.pos, hasLength(quiz.commons.statements.length), reason: m.name);
        expect(m.votes, hasLength(quiz.commons.statements.length), reason: m.name);
        expect(m.pos.any((p) => p != null), isTrue, reason: m.name);
        expect(m.from, isNotEmpty, reason: m.name);
        expect(data.memberById[m.id]?.parliament, isNot(kUkParliament), reason: m.name);
      }
      // sitting and former never collide
      expect({for (final m in former) m.id}.intersection({for (final m in quiz.members) m.id}), isEmpty);
    });
  });

  group('people who hold no seat now', () {
    final data = bundledData;

    test('former members and peers are found by name', () {
      final peers = data.others.where((m) => m.isPeer).toList();
      final former = data.others.where((m) => m.isFormer).toList();
      expect(peers.length, greaterThan(600));
      expect(former.length, greaterThan(1000));
      expect(data.others.every((m) => !m.isSitting), isTrue);
      final someone = former.first;
      expect(data.searchOthers(someone.name).map((m) => m.id), contains(someone.id));
      expect(data.searchOthers(someone.name.toUpperCase()).first.id, someone.id);
      expect(data.searchOthers('ab'), isEmpty); // two letters would match hundreds
      expect(data.searchOthers('zzzzzz'), isEmpty);
      expect(data.searchOthers('lord', limit: 5), hasLength(5));
    });

    test('a name is matched at the start of a word before the middle of one', () {
      final hits = data.searchOthers('cam', limit: 50);
      final firstInside = hits.indexWhere((m) => !RegExp(r'(^| )cam').hasMatch(norm(m.name)));
      final lastAtStart = hits.lastIndexWhere((m) => RegExp(r'(^| )cam').hasMatch(norm(m.name)));
      expect(lastAtStart, greaterThanOrEqualTo(0));
      if (firstInside >= 0) expect(firstInside, greaterThan(lastAtStart));
    });

    test('nobody with a seat is listed as having left it', () {
      for (final m in data.others.where((m) => m.isFormer)) {
        expect(data.memberById[m.id]?.parliament, isNot(m.parliament), reason: m.name);
        expect(m.until, isNotEmpty, reason: m.name);
      }
    });

    test('a peer is known by their title, never by a first name alone', () {
      for (final m in data.others.where((m) => m.isPeer)) {
        expect(m.name.trim().split(' ').length, greaterThan(1), reason: '${m.id} "${m.name}"');
        expect(m.name, m.name.trim(), reason: '${m.id} "${m.name}"');
        expect(m.termKnown, isTrue, reason: m.name);
      }
    });

    test('one person can have a record in more than one place', () {
      final moved = data.others.firstWhere((m) => m.isFormer && data.memberById.containsKey(m.id));
      final records = data.recordsOf(moved.id);
      expect(records.length, greaterThan(1));
      expect(records.first.isSitting, isTrue); // where they sit now comes first
      expect(data.recordIn(moved.id, moved.parliament), same(moved));
      expect(data.recordIn(moved.id, records.first.parliament), same(records.first));
      expect(data.recordIn(moved.id, 'Nowhere'), isNull);
      expect(data.recordsOf(-1), isEmpty);
      expect(data.chamber('House of Lords')?.twfySegment, 'peer');
    });
  });

  group('elections and councillors', () {
    final data = localData;

    test('ballots are found by any of a place\'s official codes', () {
      expect(data.ballotsFor(const []), isEmpty);
      expect(data.ballotsFor(const ['', 'E99999999']), isEmpty);
      final here = data.ballotsFor(const ['X00000000', kTestWard, kTestCounty]);
      expect(here.map((b) => b.area), ['Ward One', 'North Division']);
      expect(here.first.byElection, isTrue);
      expect(here.first.candidates.map((c) => c.name), contains('Pat Example'));
      expect(here.last.cancelled, isTrue);
      expect(here.last.seats, 2);
    });

    test('a candidate who has held office links to that record, and nobody else does', () {
      final ballot = data.ballotsFor(const [kTestWard]).single;
      final fresh = ballot.candidates.firstWhere((c) => c.name == 'Pat Example');
      final returning = ballot.candidates.firstWhere((c) => c.record != null);
      expect(fresh.record, isNull);
      expect(data.recordsOf(returning.record!), isNotEmpty);
      for (final b in bundledData.ballots) {
        for (final c in b.candidates) {
          if (c.record != null) expect(bundledData.recordsOf(c.record!), isNotEmpty, reason: c.name);
        }
      }
    });

    test('candidates are found by name, from three letters', () {
      expect(data.searchCandidates('pat exa').single.ballot.area, 'Ward One');
      expect(data.searchCandidates('EXAMPLE').single.candidate.name, 'Pat Example');
      expect(data.searchCandidates('pa'), isEmpty);
      expect(data.searchCandidates('xample'), isEmpty); // not the middle of a word
    });

    test('councillors are found by the postcode\'s ward, or the area that covers it', () {
      final byWard = data.councilFor(kTestDistrict, 'Ward Two')!;
      expect((byWard.body.name, byWard.ward.name), ('Testshire Council', 'Riverside'));
      expect(data.councilFor(kTestDistrict, 'riverside')!.ward.name, 'Riverside');
      expect(data.councilFor(kTestDistrict, 'Somewhere Else'), isNull);
      expect(data.councilFor(kQuietDistrict, 'Ward Two'), isNull); // right ward, wrong council
      expect(data.councilFor(kTestDistrict, ''), isNull);
      final people = byWard.ward.councillors;
      expect(people.first.attendance, 75);
      expect(people.last.attendance, isNull); // not published is not zero
    });

    test('the councils that were read are in the bundled data, with what was found', () {
      for (final body in bundledData.councils) {
        expect(body.gss, matches(RegExp(r'^[ENSW]\d{8}$')), reason: body.name);
        expect(body.wards, isNotEmpty, reason: body.name);
        for (final w in body.wards) {
          expect(w.covers, isNotEmpty, reason: '${body.name}: ${w.name}');
          expect(w.councillors, isNotEmpty, reason: '${body.name}: ${w.name}');
          for (final c in w.councillors) {
            if (c.attendance != null) {
              expect(c.attendance, inInclusiveRange(0, 100), reason: c.name);
            }
            expect(body.hasAttendance || c.expected == null, isTrue, reason: c.name);
          }
        }
      }
    });

    test('an older data file without any of this still loads', () {
      final old = readJson('assets/data/data.json')
        ..remove('others')
        ..remove('elections')
        ..remove('councils');
      final loaded = AppData.fromJson(old);
      expect(loaded.members, hasLength(bundledData.members.length));
      expect(loaded.others, isEmpty);
      expect(loaded.ballots, isEmpty);
      expect(loaded.councils, isEmpty);
      expect(loaded.councilFor(kTestDistrict, 'Ward One'), isNull);
    });
  });
}
