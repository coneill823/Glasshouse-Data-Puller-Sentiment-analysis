// The bundled data files parse, and names can be found however they are typed.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/place.dart';
import 'package:glasshouse/core/text.dart';

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
          expect(m.votes[i], hasLength(quiz.statements[i].divisions.length));
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
}
