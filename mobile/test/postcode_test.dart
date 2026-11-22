// Postcode lookup against canned postcodes.io replies. No network is used.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/postcode.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

final AppData data = AppData.fromJson(
    jsonDecode(File('assets/data/data.json').readAsStringSync()) as Map<String, dynamic>);

String gssOf(String area) =>
    data.areas.firstWhere((a) => a.parliament == kUkParliament && a.area == area).members.first.gss!;

http.Response ok(Map<String, dynamic> result) =>
    http.Response(jsonEncode({'status': 200, 'result': result}), 200,
        headers: {'content-type': 'application/json; charset=utf-8'});

/// A fake postcodes.io: `main` answers /postcodes/…, `scotland` /scotland/postcodes/….
PostcodeLookup lookup({required http.Response Function() main, http.Response Function()? scotland}) {
  final requested = <String>[];
  final client = MockClient((request) async {
    requested.add(request.url.path);
    if (request.url.path.startsWith('/scotland/')) {
      return (scotland ?? () => http.Response('{}', 500))();
    }
    return main();
  });
  return PostcodeLookup(data, client: client);
}

void main() {
  test('an English postcode resolves to its MP by official code', () async {
    final place = await lookup(main: () => ok({
          'postcode': 'SW1A 0AA', 'country': 'England',
          'parliamentary_constituency_2024': 'A name we deliberately ignore',
          'codes': {'parliamentary_constituency_2024': gssOf('Cities of London and Westminster')},
        })).find('sw1a0aa');
    expect(place.label, 'SW1A 0AA');
    expect(place.areas(data).map((a) => a.area), ['Cities of London and Westminster']);
    expect(place.notes, isEmpty);
  });

  test('a Scottish postcode adds the constituency MSP and the regional list', () async {
    final place = await lookup(
      main: () => ok({
        'postcode': 'G12 8QQ', 'country': 'Scotland',
        'codes': {'parliamentary_constituency_2024': gssOf('Glasgow North')},
      }),
      scotland: () => ok({
        'scottish_parliamentary_constituency': 'Glasgow Kelvin and Maryhill',
        'scottish_parliamentary_region': 'Glasgow',
      }),
    ).find('G12 8QQ');
    final areas = place.areas(data);
    expect(areas.map((a) => a.area), ['Glasgow North', 'Glasgow Kelvin and Maryhill', 'Glasgow']);
    expect(areas.last.isRegion, isTrue);
    expect(areas.fold<int>(0, (n, a) => n + a.members.length), greaterThan(5));
  });

  test('if the Scottish lookup fails the MP is still returned, with a note', () async {
    final place = await lookup(
      main: () => ok({
        'postcode': 'G12 8QQ', 'country': 'Scotland',
        'codes': {'parliamentary_constituency_2024': gssOf('Glasgow North')},
      }),
    ).find('G12 8QQ');
    expect(place.areas(data).map((a) => a.area), ['Glasgow North']);
    expect(place.notes, [PostcodeLookup.scottishNote]);
  });

  test('a Welsh postcode says the Senedd seat cannot be resolved yet', () async {
    final place = await lookup(main: () => ok({
          'postcode': 'LL57 4BN', 'country': 'Wales',
          'codes': {'parliamentary_constituency_2024': gssOf('Bangor Aberconwy')},
        })).find('LL57 4BN');
    expect(place.areas(data).map((a) => a.parliament), [kUkParliament]);
    expect(place.notes, [PostcodeLookup.welshNote]);
  });

  test('Northern Ireland maps the renamed Westminster seat to its Assembly seat', () async {
    final place = await lookup(main: () => ok({
          'postcode': 'BT7 1NN', 'country': 'Northern Ireland',
          'parliamentary_constituency_2024': 'Belfast South and Mid Down',
          'codes': {'parliamentary_constituency_2024': gssOf('Belfast South and Mid Down')},
        })).find('BT7 1NN');
    final areas = place.areas(data);
    expect(areas.map((a) => '${a.parliament}: ${a.area}'),
        ['UK Parliament: Belfast South and Mid Down', 'NI Assembly: Belfast South']);
    expect(areas.last.members.length, greaterThan(1));
    expect(place.notes, [PostcodeLookup.northernIrishNote]);
  });

  test('an unknown postcode is reported as such', () async {
    final l = lookup(main: () => http.Response('{"status":404,"error":"Invalid postcode"}', 404));
    await expectLater(l.find('ZZ99 9ZZ'),
        throwsA(isA<PostcodeException>().having((e) => e.kind, 'kind', PostcodeFailure.notFound)));
  });

  test('no connection is not mistaken for a bad postcode', () async {
    final offline = PostcodeLookup(data,
        client: MockClient((_) async => throw const SocketException('offline')));
    await expectLater(offline.find('SW1A 0AA'),
        throwsA(isA<PostcodeException>().having((e) => e.kind, 'kind', PostcodeFailure.unavailable)));
    final broken = lookup(main: () => http.Response('<html>gateway timeout</html>', 200));
    await expectLater(broken.find('SW1A 0AA'),
        throwsA(isA<PostcodeException>().having((e) => e.kind, 'kind', PostcodeFailure.unavailable)));
  });

  test('a real postcode outside our data says so', () async {
    final l = lookup(main: () => ok({
          'postcode': 'IM1 1AA', 'country': 'Isle of Man', 'codes': <String, dynamic>{},
        }));
    await expectLater(
        l.find('IM1 1AA'),
        throwsA(isA<PostcodeException>()
            .having((e) => e.kind, 'kind', PostcodeFailure.noMatch)
            .having((e) => e.message, 'message', contains('IM1 1AA'))));
  });
}
