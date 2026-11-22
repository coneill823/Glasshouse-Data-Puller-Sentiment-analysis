// What the tests share: the bundled data, and a few made-up local records.
//
// Elections come and go, so nothing here depends on which ones happen to be
// in the register on the day the data was built. The ballots and the council
// below are invented, with codes no real place has, and are added to the real
// data rather than replacing it.
import 'dart:convert';
import 'dart:io';

import 'package:glasshouse/core/models.dart';

Map<String, dynamic> readJson(String path) =>
    jsonDecode(File(path).readAsStringSync()) as Map<String, dynamic>;

const String kTestWard = 'E05TEST01';
const String kTestCounty = 'E10TEST01';
const String kTestDistrict = 'E07TEST01';
const String kQuietDistrict = 'E07TEST02';

/// The bundled data, with the invented ballots and council added.
Map<String, dynamic> dataJsonWithLocal() {
  final j = readJson('assets/data/data.json');
  final others = (j['others'] as List).cast<Map<String, dynamic>>();
  final former = others.firstWhere((m) => m['status'] == 'former');

  final elections = ((j['elections'] as Map?) ?? <String, dynamic>{}).cast<String, dynamic>();
  elections['asOf'] ??= '2026-11-22';
  elections['ballots'] = [
    ...((elections['ballots'] as List?) ?? const []),
    {
      'id': 'local.testshire.ward-one.by.2099-05-07',
      'date': '2099-05-07',
      'kind': 'Council',
      'title': 'Testshire local election Ward One by-election',
      'body': 'Testshire',
      'area': 'Ward One',
      'gss': kTestWard,
      'seats': 1,
      'byElection': true,
      'cancelled': false,
      'url': 'https://whocanivotefor.co.uk/elections/local.testshire.ward-one.by.2099-05-07/',
      'candidates': [
        {'name': 'Pat Example', 'party': 'Independent', 'record': null},
        // someone who has held a seat before, standing again
        {'name': former['name'], 'party': former['party'], 'record': former['id']},
      ],
    },
    {
      'id': 'local.testshire.2099-05-07',
      'date': '2099-05-07',
      'kind': 'Council',
      'title': 'Testshire County Council election',
      'body': 'Testshire County',
      'area': 'North Division',
      'gss': kTestCounty,
      'seats': 2,
      'byElection': false,
      'cancelled': true,
      'url': '',
      'candidates': <Map<String, dynamic>>[],
    },
  ];
  j['elections'] = elections;

  final councils = ((j['councils'] as Map?) ?? <String, dynamic>{}).cast<String, dynamic>();
  councils['period'] ??= ['2025-11-22', '2026-11-22'];
  councils['bodies'] = [
    ...((councils['bodies'] as List?) ?? const []),
    {
      'name': 'Testshire Council',
      'gss': kTestDistrict,
      'url': 'https://example.org',
      'attendance': true,
      'wards': [
        {
          'name': 'Riverside',
          'covers': ['Ward One', 'Ward Two'],
          'councillors': [
            {'name': 'Sam Sample', 'party': 'Independent', 'expected': 20, 'present': 15,
             'url': 'https://example.org/sam'},
            {'name': 'Alex Absent', 'party': 'Green', 'url': 'https://example.org/alex'},
          ],
        },
      ],
    },
  ];
  j['councils'] = councils;
  return j;
}

/// The bundled data exactly as the app ships it.
final AppData bundledData = AppData.fromJson(readJson('assets/data/data.json'));

/// The same, with the invented local records.
final AppData localData = AppData.fromJson(dataJsonWithLocal());

final QuizData bundledQuiz = QuizData.fromJson(readJson('assets/data/quiz.json'));
