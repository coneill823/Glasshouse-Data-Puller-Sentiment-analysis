/// The two data files the app reads, as typed objects.
///
/// Both are produced by `python -m analysis.build` in the repository root and
/// are the same files the web app uses: `data.json` (every sitting
/// representative) and `quiz.json` (statements and each MP's position).
library;

import 'text.dart';

const String kUkParliament = 'UK Parliament';

double? _double(Object? v) => v is num ? v.toDouble() : null;
int _int(Object? v, [int fallback = 0]) => v is num ? v.toInt() : fallback;
int? _intOrNull(Object? v) => v is num ? v.toInt() : null;
String _string(Object? v) => v == null ? '' : v.toString();
Map<String, dynamic> _map(Object? v) =>
    v is Map ? v.cast<String, dynamic>() : const <String, dynamic>{};
List<dynamic> _list(Object? v) => v is List ? v : const <dynamic>[];

String? divisionUrlFromKey(String? key) {
  final m = RegExp(r'^pw-(\d{4}-\d{2}-\d{2})-(\d+)-([a-z]+)$').firstMatch(key ?? '');
  if (m == null) return null;
  return 'https://votes.theyworkforyou.com/decisions/division/${m[3]}/${m[1]}/${m[2]}';
}

/// One legislature: its name for a member, its term and its medians.
class Chamber {
  const Chamber({
    required this.parliament,
    required this.slug,
    required this.role,
    required this.house,
    required this.termStart,
    required this.votesSource,
    required this.members,
    required this.termDivisions,
    this.turnout,
    this.partyAgreement,
    this.chamberAgreement,
  });

  factory Chamber.fromJson(String parliament, Map<String, dynamic> j) => Chamber(
        parliament: parliament,
        slug: _string(j['slug']),
        role: _string(j['role']).isEmpty ? 'Member' : _string(j['role']),
        house: _string(j['house']).isEmpty ? parliament : _string(j['house']),
        termStart: _string(j['termStart']),
        votesSource: _string(j['votesSource']),
        members: _int(j['members']),
        termDivisions: _int(j['termDivisions']),
        turnout: _double(j['turnout']),
        partyAgreement: _double(j['partyAgreement']),
        chamberAgreement: _double(j['chamberAgreement']),
      );

  final String parliament, slug, role, house, termStart, votesSource;
  final int members, termDivisions;
  final double? turnout, partyAgreement, chamberAgreement;

  /// Path segment TheyWorkForYou uses for a member of this chamber.
  String? get twfySegment =>
      const {'commons': 'mp', 'scotland': 'msp', 'senedd': 'ms', 'ni': 'mla'}[slug];
}

class Topic {
  const Topic(this.name, this.count, this.share);
  final String name;
  final int count;
  final double share;
}

/// One occasion on which a member did something other than most of their party.
class Receipt {
  const Receipt(this.date, this.title, this.theirVote, this.partyVote, this.key);
  final String date, title, theirVote, partyVote;
  final String? key;
  String? get url => divisionUrlFromKey(key);
}

class Motions {
  const Motions(this.proposed, this.signed);
  final int proposed, signed;
}

class Member {
  const Member({
    required this.id,
    required this.name,
    required this.party,
    required this.area,
    required this.parliament,
    required this.since,
    required this.votesCast,
    required this.eligible,
    required this.partyLineDivisions,
    required this.rebellions,
    required this.topics,
    required this.receipts,
    this.mnis,
    this.gss,
    this.recordAsOf,
    this.termVotes,
    this.turnout,
    this.partyAgreement,
    this.chamberAgreement,
    this.questions,
    this.speeches,
    this.motions,
  });

  factory Member.fromJson(Map<String, dynamic> j) {
    final motions = j['motions'];
    return Member(
      id: _int(j['id']),
      name: _string(j['name']),
      party: _string(j['party']),
      area: _string(j['area']),
      parliament: _string(j['parliament']),
      since: _string(j['since']),
      mnis: j['mnis'] == null ? null : _string(j['mnis']),
      gss: j['gss'] == null ? null : _string(j['gss']),
      recordAsOf: j['recordAsOf'] == null ? null : _string(j['recordAsOf']),
      votesCast: _int(j['votesCast']),
      termVotes: _intOrNull(j['termVotes']),
      eligible: _int(j['eligible']),
      turnout: _double(j['turnout']),
      partyAgreement: _double(j['partyAgreement']),
      partyLineDivisions: _int(j['partyLineDivisions']),
      chamberAgreement: _double(j['chamberAgreement']),
      rebellions: _int(j['rebellions']),
      questions: _intOrNull(j['questions']),
      speeches: _intOrNull(j['speeches']),
      topics: [
        for (final t in _list(j['topics']))
          if (t is List && t.length >= 3 && _int(t[1]) > 0)
            Topic(_string(t[0]), _int(t[1]), _double(t[2]) ?? 0),
      ],
      receipts: [
        for (final r in _list(j['receipts']))
          if (r is List && r.length >= 4)
            Receipt(_string(r[0]), _string(r[1]), _string(r[2]), _string(r[3]),
                r.length > 4 && r[4] != null ? _string(r[4]) : null),
      ],
      motions: motions is Map
          ? Motions(_int(motions['proposed']), _int(motions['signed']))
          : null,
    );
  }

  final int id;
  final String name, party, area, parliament, since;
  final String? mnis, gss, recordAsOf;
  final int votesCast, eligible, partyLineDivisions, rebellions;
  final int? termVotes, questions, speeches;
  final double? turnout, partyAgreement, chamberAgreement;
  final List<Topic> topics;
  final List<Receipt> receipts;
  final Motions? motions;

  String get areaKey => '$parliament||$area';

  /// Turnout is only meaningful when we know how many divisions they could
  /// have voted in this term.
  bool get termKnown => termVotes != null && eligible > 0;
  bool get neverVoted => termKnown && termVotes == 0;
  int? get spoken => questions == null ? null : questions! + (speeches ?? 0);
}

/// A constituency or region in one legislature, with whoever sits for it.
class Area {
  Area(this.parliament, this.area);
  final String parliament, area;
  final List<Member> members = [];

  /// Scottish regional lists return several members for one area.
  bool isRegion = false;
  String get key => '$parliament||$area';
}

class Sources {
  const Sources({required this.votesAsOf, required this.speechAsOf});
  final String votesAsOf, speechAsOf;
}

class AppData {
  AppData._(this.generated, this.sources, this.chambers, this.members) {
    for (final m in members) {
      final area = areaByKey.putIfAbsent(m.areaKey, () {
        final a = Area(m.parliament, m.area);
        areas.add(a);
        return a;
      });
      area.members.add(m);
      memberById[m.id] = m;
      if (m.gss != null && m.parliament == kUkParliament) areaByGss[m.gss!] = area;
    }
    for (final a in areas) {
      areaByName['${a.parliament}||${norm(a.area)}'] = a;
      a.isRegion = a.parliament == 'Scottish Parliament' && a.members.length > 1;
      a.members.sort((x, y) => x.name.compareTo(y.name));
    }
    areas.sort((a, b) => norm(a.area).compareTo(norm(b.area)));
  }

  factory AppData.fromJson(Map<String, dynamic> j) {
    final sources = _map(j['sources']);
    return AppData._(
      _string(j['generated']),
      Sources(
        votesAsOf: _string(_map(sources['votes'])['asOf']),
        speechAsOf: _string(_map(sources['speech'])['asOf']),
      ),
      {
        for (final e in _map(j['chambers']).entries)
          e.key: Chamber.fromJson(e.key, _map(e.value)),
      },
      [for (final m in _list(j['members'])) Member.fromJson(_map(m))],
    );
  }

  final String generated;
  final Sources sources;
  final Map<String, Chamber> chambers;
  final List<Member> members;

  final List<Area> areas = [];
  final Map<String, Area> areaByKey = {};
  final Map<String, Area> areaByGss = {};
  final Map<String, Area> areaByName = {};
  final Map<int, Member> memberById = {};

  Chamber? chamber(String parliament) => chambers[parliament];
  String roleOf(String parliament) => chambers[parliament]?.role ?? 'Member';

  /// Areas whose name, or one of whose members' names, contains the query.
  List<Area> search(String query, {int limit = 36}) {
    final q = norm(query);
    if (q.length < 2) return const [];
    final seen = <String>{};
    final out = <Area>[];
    for (final a in areas) {
      if (norm(a.area).contains(q) && seen.add(a.key)) out.add(a);
    }
    for (final m in members) {
      if (norm(m.name).contains(q)) {
        final a = areaByKey[m.areaKey];
        if (a != null && seen.add(a.key)) out.add(a);
      }
    }
    return out.length > limit ? out.sublist(0, limit) : out;
  }
}

/// One division that counts towards a statement.
class Division {
  const Division(this.key, this.date, this.number, this.title, this.alignment);
  final String key, date, title, alignment;
  final int number;

  String get url =>
      'https://votes.theyworkforyou.com/decisions/division/commons/$date/$number';

  /// Whether voting aye supported the statement.
  bool get ayeSupports => alignment == 'agree';
}

class Statement {
  const Statement({
    required this.id,
    required this.name,
    required this.text,
    required this.detail,
    required this.link,
    required this.group,
    required this.freeVote,
    required this.econ,
    required this.social,
    required this.termVotes,
    required this.divisions,
  });

  factory Statement.fromJson(Map<String, dynamic> j) => Statement(
        id: _int(j['id']),
        name: _string(j['name']),
        text: _string(j['text']),
        detail: _string(j['detail']),
        link: _string(j['link']),
        group: _string(j['group']),
        freeVote: j['freeVote'] == true,
        econ: _double(j['econ']) ?? 0,
        social: _double(j['social']) ?? 0,
        termVotes: _int(j['termVotes']),
        divisions: [
          for (final d in _list(j['divisions']))
            Division(_string(_map(d)['key']), _string(_map(d)['date']),
                _int(_map(d)['number']), _string(_map(d)['title']),
                _string(_map(d)['alignment'])),
        ],
      );

  final int id, termVotes;
  final String name, text, detail, link, group;
  final bool freeVote;

  /// Which way supporting this statement moves you on each compass axis.
  /// Zero means it does not move that axis at all.
  final double econ, social;
  final List<Division> divisions;
}

/// An MP's position on each statement, and the votes behind it.
class QuizMember {
  const QuizMember({
    required this.id,
    required this.name,
    required this.party,
    required this.area,
    required this.pos,
    required this.votes,
  });

  factory QuizMember.fromJson(Map<String, dynamic> j) => QuizMember(
        id: _int(j['id']),
        name: _string(j['name']),
        party: _string(j['party']),
        area: _string(j['area']),
        pos: [for (final p in _list(j['pos'])) _double(p)],
        votes: [for (final v in _list(j['votes'])) _string(v)],
      );

  final int id;
  final String name, party, area;

  /// One entry per statement: +1 always voted for it, -1 always against,
  /// null if they never voted on it.
  final List<double?> pos;

  /// One string per statement, one character per division:
  /// f for, a against, b abstained, x absent, . not an MP at the time.
  final List<String> votes;
}

class QuizData {
  QuizData._(this.termStart, this.votesAsOf, this.statements, this.members) {
    for (final m in members) {
      byId[m.id] = m;
    }
  }

  factory QuizData.fromJson(Map<String, dynamic> j) => QuizData._(
        _string(j['termStart']),
        _string(j['votesAsOf']),
        [for (final s in _list(j['statements'])) Statement.fromJson(_map(s))],
        [for (final m in _list(j['members'])) QuizMember.fromJson(_map(m))],
      );

  final String termStart, votesAsOf;
  final List<Statement> statements;
  final List<QuizMember> members;
  final Map<int, QuizMember> byId = {};
}
