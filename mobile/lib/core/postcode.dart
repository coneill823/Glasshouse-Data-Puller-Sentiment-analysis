/// Postcode -> the constituencies that cover it, using the open postcodes.io
/// service. The postcode is sent to that service and nowhere else, and is not
/// kept by the app beyond remembering the place the visitor chose.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';
import 'place.dart';
import 'text.dart';

enum PostcodeFailure {
  /// postcodes.io does not know the postcode.
  notFound,

  /// No connection, a timeout, or an unexpected reply.
  unavailable,

  /// A real postcode, but none of its constituencies is in our data.
  noMatch,
}

class PostcodeException implements Exception {
  const PostcodeException(this.kind, [this.postcode = '']);
  final PostcodeFailure kind;
  final String postcode;

  String get message => switch (kind) {
        PostcodeFailure.notFound =>
          'That postcode was not recognised. Check it, or search by constituency name.',
        PostcodeFailure.unavailable =>
          'Postcode lookup is not available right now. Check your connection, or search by constituency or representative name.',
        PostcodeFailure.noMatch =>
          'We could not match $postcode to a constituency. Search by name instead.',
      };
}

class PostcodeLookup {
  PostcodeLookup(this.data, {http.Client? client}) : _client = client ?? http.Client();

  final AppData data;
  final http.Client _client;

  static const String _base = 'https://api.postcodes.io';
  static const Duration _timeout = Duration(seconds: 12);

  static const String welshNote =
      'We cannot yet match a postcode to a Senedd constituency. Search for yours by name to see your Members of the Senedd.';
  static const String scottishNote =
      'We found your MP but could not look up your MSPs. Search for your Scottish Parliament constituency by name.';
  static const String northernIrishNote =
      'Assembly seats still use the pre-2024 boundaries, so near a boundary your MLAs may be those of the neighbouring constituency.';

  Future<Map<String, dynamic>> _get(String path) async {
    final http.Response r;
    try {
      r = await _client.get(Uri.parse('$_base/$path')).timeout(_timeout);
    } on Object {
      throw const PostcodeException(PostcodeFailure.unavailable);
    }
    if (r.statusCode == 404) throw const PostcodeException(PostcodeFailure.notFound);
    if (r.statusCode != 200) throw const PostcodeException(PostcodeFailure.unavailable);
    try {
      final body = jsonDecode(utf8.decode(r.bodyBytes));
      final result = body is Map ? body['result'] : null;
      return result is Map ? result.cast<String, dynamic>() : <String, dynamic>{};
    } on FormatException {
      throw const PostcodeException(PostcodeFailure.unavailable);
    }
  }

  Future<Place> find(String raw) async {
    final pc = raw.replaceAll(RegExp(r'\s+'), '').toUpperCase();
    final encoded = Uri.encodeComponent(pc);
    final res = await _get('postcodes/$encoded');
    final keys = <String>[];
    final notes = <String>[];

    // The Commons seat is matched on its official code, never on its name.
    final codes = res['codes'];
    final gss = codes is Map ? codes['parliamentary_constituency_2024'] : null;
    final uk = data.areaByGss[gss];
    if (uk != null) keys.add(uk.key);

    final country = res['country'];
    if (country == 'Scotland') {
      try {
        final s = await _get('scotland/postcodes/$encoded');
        for (final name in [
          s['scottish_parliamentary_constituency'],
          s['scottish_parliamentary_region'],
        ]) {
          final a = data.areaByName['Scottish Parliament||${norm(name?.toString())}'];
          if (a != null) keys.add(a.key);
        }
      } on PostcodeException {
        notes.add(scottishNote);
      }
    } else if (country == 'Wales') {
      notes.add(welshNote);
    } else if (country == 'Northern Ireland') {
      // Assembly seats share the Westminster names, bar one that was renamed.
      final name = (res['parliamentary_constituency_2024'] ?? '')
          .toString()
          .replaceFirst(RegExp(r' and Mid Down$'), '');
      final n = norm(name);
      final ni = data.areaByName['NI Assembly||$n'] ??
          data.areaByName['NI Assembly||${n.split(' ').reversed.join(' ')}'];
      if (ni != null) {
        keys.add(ni.key);
        notes.add(northernIrishNote);
      }
    }

    final label = (res['postcode'] ?? pc).toString();
    if (keys.isEmpty) throw PostcodeException(PostcodeFailure.noMatch, label);
    return Place(label: label, keys: keys, notes: notes);
  }
}
