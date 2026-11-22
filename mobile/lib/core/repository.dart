/// Loading the data: the copy the app shipped with, or a newer one it has
/// since downloaded.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show AssetBundle, rootBundle;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'app_state.dart';
import 'cache_stub.dart' if (dart.library.io) 'cache_io.dart' as cache;
import 'models.dart';

/// Where newer data is fetched from: the two JSON files in the repository's
/// default branch. Votes change daily and a store release takes days, so
/// without this the app would always be showing an old record. Set to an empty
/// string to switch refreshing off; the app then only ever uses bundled data.
const String kRemoteBase =
    'https://raw.githubusercontent.com/coneill823/Glasshouse-Data-Puller-Sentiment-analysis/HEAD/app';

/// Checked at most this often.
const Duration kRefreshEvery = Duration(hours: 12);

const String _lastRefreshKey = 'glasshouse.lastRefresh';
const String _answersKey = 'glasshouse.quiz.v1';

class Loaded {
  const Loaded(this.data, this.quiz, {required this.fromDownload});
  final AppData data;
  final QuizData? quiz;

  /// True when a downloaded copy replaced the bundled one.
  final bool fromDownload;
}

Map<String, dynamic> _decode(String source) {
  final decoded = jsonDecode(source);
  return decoded is Map ? decoded.cast<String, dynamic>() : <String, dynamic>{};
}

/// A downloaded pair is only trusted if both files look whole and were built
/// together — the quiz refers to members by the ids in the data file.
@visibleForTesting
bool usablePair(Map<String, dynamic> data, Map<String, dynamic> quiz) {
  final members = data['members'];
  final statements = quiz['statements'];
  final quizMembers = quiz['members'];
  if (members is! List || members.length < 500) return false;
  if (statements is! List || statements.isEmpty) return false;
  if (quizMembers is! List || quizMembers.length < 500) return false;
  final sources = data['sources'];
  final votes = sources is Map ? sources['votes'] : null;
  final asOf = votes is Map ? votes['asOf'] : null;
  return asOf != null && asOf == quiz['votesAsOf'];
}

Future<Loaded> loadData({AssetBundle? bundle}) async {
  final assets = bundle ?? rootBundle;
  var data = await compute(_decode, await assets.loadString('assets/data/data.json'));
  var quiz = await compute(_decode, await assets.loadString('assets/data/quiz.json'));
  var fromDownload = false;
  try {
    final cachedData = await cache.read('data.json');
    final cachedQuiz = await cache.read('quiz.json');
    if (cachedData != null && cachedQuiz != null) {
      final d = await compute(_decode, cachedData);
      final q = await compute(_decode, cachedQuiz);
      final newer = '${d['generated']}'.compareTo('${data['generated']}') > 0;
      if (newer && usablePair(d, q)) {
        data = d;
        quiz = q;
        fromDownload = true;
      }
    }
  } on Object {
    // Anything wrong with the downloaded copy: the bundled one is still good.
  }
  return Loaded(AppData.fromJson(data), QuizData.fromJson(quiz), fromDownload: fromDownload);
}

/// Fetches newer data for the NEXT launch. Never changes what is on screen, so
/// a quiz in progress cannot have its statements swapped underneath it.
Future<void> refreshInBackground({http.Client? client}) async {
  if (kIsWeb || kRemoteBase.isEmpty) return;
  final http.Client c = client ?? http.Client();
  try {
    final prefs = await SharedPreferences.getInstance();
    final now = DateTime.now().millisecondsSinceEpoch;
    if (now - (prefs.getInt(_lastRefreshKey) ?? 0) < kRefreshEvery.inMilliseconds) return;
    const timeout = Duration(seconds: 25);
    final dataResponse = await c.get(Uri.parse('$kRemoteBase/data.json')).timeout(timeout);
    final quizResponse = await c.get(Uri.parse('$kRemoteBase/quiz.json')).timeout(timeout);
    if (dataResponse.statusCode != 200 || quizResponse.statusCode != 200) return;
    final dataText = utf8.decode(dataResponse.bodyBytes);
    final quizText = utf8.decode(quizResponse.bodyBytes);
    if (!usablePair(await compute(_decode, dataText), await compute(_decode, quizText))) return;
    await cache.write('data.json', dataText);
    await cache.write('quiz.json', quizText);
    await prefs.setInt(_lastRefreshKey, now);
  } on Object {
    // Offline, blocked, or the files changed mid-download: try again later.
  } finally {
    if (client == null) c.close();
  }
}

/// Quiz answers, kept on this device only.
class PrefsStore implements AnswerStore {
  @override
  Future<String?> read() async {
    try {
      return (await SharedPreferences.getInstance()).getString(_answersKey);
    } on Object {
      return null;
    }
  }

  @override
  Future<void> write(String value) async {
    try {
      await (await SharedPreferences.getInstance()).setString(_answersKey, value);
    } on Object {
      // Storage full or unavailable: the quiz still works for this session.
    }
  }
}
