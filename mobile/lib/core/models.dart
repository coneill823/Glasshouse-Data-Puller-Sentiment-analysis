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
      const {'commons': 'mp', 'scotland': 'msp', 'senedd': 'ms', 'ni': 'mla', 'lords': 'peer'}[slug];
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
    this.status = '',
    this.until = '',
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
      status: _string(j['status']),
      until: _string(j['until']),
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

  /// Empty for a sitting member; "former" for someone who has left the
  /// chamber, "peer" for a member of the House of Lords.
  final String status;

  /// The year a former member left.
  final String until;
  final String? mnis, gss, recordAsOf;
  final int votesCast, eligible, partyLineDivisions, rebellions;
  final int? termVotes, questions, speeches;
  final double? turnout, partyAgreement, chamberAgreement;
  final List<Topic> topics;
  final List<Receipt> receipts;
  final Motions? motions;

  String get areaKey => '$parliament||$area';
  bool get isFormer => status == 'former';
  bool get isPeer => status == 'peer';
  bool get isSitting => status.isEmpty;

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

/// Someone standing in an election that has not happened yet.
class Candidate {
  const Candidate(this.name, this.party, this.record);
  final String name, party;

  /// Their id here, if they have ever held an office we have a record for.
  final int? record;
}

/// One ballot paper in an upcoming election.
class Ballot {
  const Ballot({
    required this.id,
    required this.date,
    required this.kind,
    required this.title,
    required this.body,
    required this.area,
    required this.gss,
    required this.seats,
    required this.byElection,
    required this.cancelled,
    required this.url,
    required this.candidates,
  });

  factory Ballot.fromJson(Map<String, dynamic> j) => Ballot(
        id: _string(j['id']),
        date: _string(j['date']),
        kind: _string(j['kind']),
        title: _string(j['title']),
        body: _string(j['body']),
        area: _string(j['area']),
        gss: _string(j['gss']),
        seats: _int(j['seats'], 1),
        byElection: j['byElection'] == true,
        cancelled: j['cancelled'] == true,
        url: _string(j['url']),
        candidates: [
          for (final c in _list(j['candidates']))
            Candidate(_string(_map(c)['name']), _string(_map(c)['party']),
                _intOrNull(_map(c)['record'])),
        ],
      );

  final String id, date, kind, title, body, area, gss, url;
  final int seats;
  final bool byElection, cancelled;
  final List<Candidate> candidates;
}

class Councillor {
  const Councillor(this.name, this.party, this.url, this.expected, this.present);
  final String name, party, url;

  /// Meetings they were expected at, and attended, over the council's period.
  final int? expected, present;
  double? get attendance =>
      expected == null || expected == 0 || present == null ? null : 100 * present! / expected!;
}

/// The area a group of councillors is elected for, and the wards it covers.
class CouncilWard {
  const CouncilWard(this.name, this.covers, this.councillors);
  final String name;
  final List<String> covers;
  final List<Councillor> councillors;
}

class CouncilBody {
  const CouncilBody(this.name, this.gss, this.url, this.hasAttendance, this.wards);
  final String name, gss, url;
  final bool hasAttendance;
  final List<CouncilWard> wards;
}

class AppData {
  AppData._(this.generated, this.sources, this.chambers, this.members, this.others,
      this.ballots, this.electionsAsOf, this.councils, this.councilPeriod) {
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
    for (final m in [...members, ...others]) {
      _records.putIfAbsent(m.id, () => []).add(m);
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
    final elections = _map(j['elections']);
    final councils = _map(j['councils']);
    final period = _list(councils['period']);
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
      [for (final m in _list(j['others'])) Member.fromJson(_map(m))],
      [for (final b in _list(elections['ballots'])) Ballot.fromJson(_map(b))],
      _string(elections['asOf']),
      [
        for (final b in _list(councils['bodies']))
          CouncilBody(
            _string(_map(b)['name']),
            _string(_map(b)['gss']),
            _string(_map(b)['url']),
            _map(b)['attendance'] == true,
            [
              for (final w in _list(_map(b)['wards']))
                CouncilWard(
                  _string(_map(w)['name']),
                  [for (final c in _list(_map(w)['covers'])) _string(c)],
                  [
                    for (final c in _list(_map(w)['councillors']))
                      Councillor(_string(_map(c)['name']), _string(_map(c)['party']),
                          _string(_map(c)['url']), _intOrNull(_map(c)['expected']),
                          _intOrNull(_map(c)['present'])),
                  ],
                ),
            ],
          ),
      ],
      (from: period.isNotEmpty ? _string(period.first) : '', to: period.length > 1 ? _string(period[1]) : ''),
    );
  }

  final String generated;
  final Sources sources;
  final Map<String, Chamber> chambers;

  /// Everyone sitting in one of the four elected chambers.
  final List<Member> members;

  /// Former members, and the House of Lords: found by name, not by place.
  final List<Member> others;

  /// Elections that have not happened yet.
  final List<Ballot> ballots;
  final String electionsAsOf;

  /// Councils whose own records have been read (a pilot: a couple so far).
  final List<CouncilBody> councils;
  final ({String from, String to}) councilPeriod;

  final List<Area> areas = [];
  final Map<String, Area> areaByKey = {};
  final Map<String, Area> areaByGss = {};
  final Map<String, Area> areaByName = {};
  final Map<int, Member> memberById = {};

  /// Every record held for a person: the seat they sit in now first, then
  /// any they used to hold, then the House of Lords.
  final Map<int, List<Member>> _records = {};

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

  /// Former members and peers whose name contains the query. Three letters
  /// are needed: there are thousands of them.
  List<Member> searchOthers(String query, {int limit = 12}) {
    final q = norm(query);
    if (q.length < 3) return const [];
    final starts = <Member>[], contains = <Member>[];
    for (final m in others) {
      final n = norm(m.name);
      if (n.startsWith(q) || n.contains(' $q')) {
        starts.add(m);
      } else if (n.contains(q)) {
        contains.add(m);
      }
    }
    final out = [...starts, ...contains];
    return out.length > limit ? out.sublist(0, limit) : out;
  }

  /// Everything held on one person. A former MP who now sits in the Lords,
  /// or in a devolved parliament, has a record in each.
  List<Member> recordsOf(int id) => _records[id] ?? const [];

  /// Their record in one chamber, whether they sit there now or used to.
  Member? recordIn(int id, String parliament) {
    for (final m in recordsOf(id)) {
      if (m.parliament == parliament) return m;
    }
    return null;
  }

  /// People standing in an upcoming election whose name contains the query.
  List<({Candidate candidate, Ballot ballot})> searchCandidates(String query, {int limit = 6}) {
    final q = norm(query);
    if (q.length < 3) return const [];
    final out = <({Candidate candidate, Ballot ballot})>[];
    for (final b in ballots) {
      for (final c in b.candidates) {
        final n = norm(c.name);
        if (n.startsWith(q) || n.contains(' $q')) out.add((candidate: c, ballot: b));
      }
    }
    return out.length > limit ? out.sublist(0, limit) : out;
  }

  /// Ballots for any of these official area codes, soonest first.
  List<Ballot> ballotsFor(Iterable<String> codes) {
    final wanted = codes.where((c) => c.isNotEmpty).toSet();
    if (wanted.isEmpty) return const [];
    return [for (final b in ballots) if (wanted.contains(b.gss)) b];
  }

  /// The councillors for a ward, if its council is one we have read.
  ({CouncilBody body, CouncilWard ward})? councilFor(String districtGss, String wardName) {
    final wanted = norm(wardName);
    if (wanted.isEmpty) return null;
    for (final body in councils) {
      if (body.gss != districtGss) continue;
      for (final ward in body.wards) {
        if (norm(ward.name) == wanted || ward.covers.any((c) => norm(c) == wanted)) {
          return (body: body, ward: ward);
        }
      }
    }
    return null;
  }
}

/// One division that counts towards a statement.
class Division {
  const Division(this.key, this.date, this.number, this.title, this.alignment, [this.link = '']);
  final String key, date, title, alignment;
  final int number;

  /// Where to read about it, for chambers other than the Commons.
  final String link;

  String get url => link.isNotEmpty
      ? link
      : 'https://votes.theyworkforyou.com/decisions/division/commons/$date/$number';

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
    this.result = const [],
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
        result: [for (final r in _list(j['result'])) _int(r)],
        divisions: [
          for (final d in _list(j['divisions']))
            Division(_string(_map(d)['key']), _string(_map(d)['date']),
                _int(_map(d)['number']), _string(_map(d)['title']),
                _string(_map(d)['alignment']), _string(_map(d)['url'])),
        ],
      );

  final int id, termVotes;
  final String name, text, detail, link, group;
  final bool freeVote;

  /// Which way supporting this statement moves you on each compass axis.
  /// Zero means it does not move that axis at all.
  final double econ, social;
  final List<Division> divisions;

  /// For a question that is a single vote: how many voted for and against.
  final List<int> result;
}

/// A member's position on each statement of a quiz, and the votes behind it.
class QuizMember {
  const QuizMember({
    required this.id,
    required this.name,
    required this.party,
    required this.area,
    required this.pos,
    required this.votes,
    this.from = '',
    this.to = '',
    this.former = false,
  });

  /// `more` is how many statements follow the core list. Someone with no
  /// record on any of them carries no entries for them at all.
  factory QuizMember.fromJson(Map<String, dynamic> j, {int more = 0, bool former = false}) {
    final morePos = _list(j['morePos']);
    final moreVotes = _list(j['moreVotes']);
    return QuizMember(
      id: _int(j['id']),
      name: _string(j['name']),
      party: _string(j['party']),
      area: _string(j['area']),
      from: _string(j['from']),
      to: _string(j['to']),
      former: former,
      pos: [
        for (final p in _list(j['pos'])) _double(p),
        for (var i = 0; i < more; i++) i < morePos.length ? _double(morePos[i]) : null,
      ],
      votes: [
        for (final v in _list(j['votes'])) _string(v),
        for (var i = 0; i < more; i++) i < moreVotes.length ? _string(moreVotes[i]) : '',
      ],
    );
  }

  final int id;
  final String name, party, area;

  /// For a former member: the years they sat.
  final String from, to;
  final bool former;

  /// One entry per statement: +1 always voted for it, -1 always against,
  /// null if they never voted on it.
  final List<double?> pos;

  /// One string per statement, one character per division:
  /// f for, a against, b abstained, x absent, . not a member at the time.
  /// Empty if they were not a member for any of them.
  final List<String> votes;
}

/// One quiz: a list of statements and where each member of a chamber stands
/// on them. The Commons has one; so does each devolved legislature.
class QuizSet {
  QuizSet({
    required this.parliament,
    required this.statements,
    required this.coreCount,
    required this.members,
    required this.former,
    required this.termStart,
    required this.votesAsOf,
    required this.source,
  }) {
    for (final m in former) {
      byId[m.id] = m;
    }
    for (final m in members) {
      byId[m.id] = m;
    }
  }

  final String parliament, termStart, votesAsOf, source;

  /// Every statement: the first [coreCount] were voted on in the current
  /// term; any after that only in earlier ones.
  final List<Statement> statements;
  final int coreCount;

  /// Sitting members.
  final List<QuizMember> members;

  /// People who used to sit and have a position on something.
  final List<QuizMember> former;

  /// Sitting and former, by id.
  final Map<int, QuizMember> byId = {};

  bool get isCommons => parliament == kUkParliament;
}

class QuizData {
  QuizData._(this.commons, this.chambers);

  factory QuizData.fromJson(Map<String, dynamic> j) {
    final core = [for (final s in _list(j['statements'])) Statement.fromJson(_map(s))];
    final more = [for (final s in _list(j['moreStatements'])) Statement.fromJson(_map(s))];
    final commons = QuizSet(
      parliament: kUkParliament,
      statements: [...core, ...more],
      coreCount: core.length,
      members: [
        for (final m in _list(j['members'])) QuizMember.fromJson(_map(m), more: more.length),
      ],
      former: [
        for (final m in _list(j['former']))
          QuizMember.fromJson(_map(m), more: more.length, former: true),
      ],
      termStart: _string(j['termStart']),
      votesAsOf: _string(j['votesAsOf']),
      source: _string(_map(j['source'])['name']),
    );
    final chambers = <String, QuizSet>{};
    for (final e in _map(j['chambers']).entries) {
      final c = _map(e.value);
      final statements = [for (final s in _list(c['statements'])) Statement.fromJson(_map(s))];
      if (statements.isEmpty) continue;
      chambers[e.key] = QuizSet(
        parliament: e.key,
        statements: statements,
        coreCount: statements.length,
        members: [for (final m in _list(c['members'])) QuizMember.fromJson(_map(m))],
        former: const [],
        termStart: _string(c['termStart']),
        votesAsOf: _string(c['votesAsOf']),
        source: _string(c['source']),
      );
    }
    return QuizData._(commons, chambers);
  }

  /// The House of Commons quiz, built on mySociety's policy groupings.
  final QuizSet commons;

  /// One quiz per devolved legislature, built on its own divisions.
  final Map<String, QuizSet> chambers;

  Iterable<QuizSet> get sets => [commons, ...chambers.values];
  QuizSet? setFor(String parliament) =>
      parliament == kUkParliament ? commons : chambers[parliament];

  // The Commons quiz is what most of the app talks about.
  String get termStart => commons.termStart;
  String get votesAsOf => commons.votesAsOf;
  List<Statement> get statements => commons.statements;
  List<QuizMember> get members => commons.members;
  Map<int, QuizMember> get byId => commons.byId;
}
