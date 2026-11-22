/// One representative: the summary card in a list, and the full record.
library;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../core/scoring.dart';
import '../core/text.dart';
import '../theme.dart';
import 'scope.dart';
import 'widgets.dart';

String _pct(double? v) => v == null ? '—' : '${v.toStringAsFixed(1)}%';

/// The years someone sat: "2019–2024".
String _years(Member m) {
  if (m.since.isEmpty) return m.until.isEmpty ? '' : 'until ${m.until}';
  return m.until.isEmpty || m.until == m.since ? m.since : '${m.since}–${m.until}';
}

/// Party and length of service, in one line.
String memberLine(Member m, String role, {bool withArea = false}) {
  final party = m.party.isEmpty ? 'No party' : m.party;
  if (m.isFormer) {
    final years = _years(m);
    final seat = withArea && m.area.isNotEmpty ? '$role for ${m.area}' : 'former $role';
    return years.isEmpty ? '$party · $seat' : '$party · $seat, $years';
  }
  if (m.isPeer) return m.since.isEmpty ? party : '$party · in the Lords since ${m.since}';
  final seat = withArea ? '$role for ${m.area}' : role;
  if (m.since.isEmpty) return withArea ? '$party · $seat' : party;
  return '$party · $seat since ${m.since}';
}

/// Crossbenchers, bishops and the like sit in a group, but nobody tells them
/// how to vote. Voting unlike the rest of the group is not breaking a whip.
bool _whipped(Member m) =>
    !(m.isPeer &&
        RegExp(r'^(crossbench|bishop|non-affiliated|judge)', caseSensitive: false).hasMatch(m.party));

List<(String, String)> _tiles(Member m) => [
      m.termKnown
          ? (thousands(m.termVotes), 'of ${thousands(m.eligible)} votes this term')
          : (thousands(m.votesCast), 'votes cast'),
      // This one covers their whole record, not just this term, so it says
      // how many votes it is out of.
      m.partyLineDivisions > 0
          ? (
              thousands(m.rebellions),
              '${_whipped(m) ? 'breaks with party' : 'votes unlike their group'} '
                  'in ${thousands(m.partyLineDivisions)} votes'
            )
          : ('—', 'breaks with party'),
      // Questions and speeches are only collected for people sitting now.
      if (m.isSitting) (m.spoken == null ? '—' : thousands(m.spoken), 'questions & speeches'),
    ];

/// Why a member has no votes at all this term.
String _whyNoVotes(Member m) {
  final party = m.party.toLowerCase();
  if (m.parliament == kUkParliament && party.contains('sinn')) {
    return 'Sinn Féin MPs do not take their seats at Westminster, so they do not vote.';
  }
  if (party.startsWith('speaker') || party.startsWith('presiding')) {
    return 'Whoever chairs the chamber does not vote.';
  }
  return 'Has not voted this term. Some members do not vote by convention, such as Deputy Speakers.';
}

typedef _Match = ({QuizSet set, QuizMember member, MatchResult match});

/// The match with the visitor's answers, if there is one to show. Each
/// parliament has its own questions, so each member is matched on their own.
_Match? _matchFor(AppState state, Member m) {
  final set = state.quiz?.setFor(m.parliament);
  if (set == null || !state.canShowMatchFor(set)) return null;
  final qm = set.byId[m.id];
  if (qm == null) return null;
  final match = state.matchOf(qm, set);
  return state.isShown(match, set) ? (set: set, member: qm, match: match) : null;
}

class _MatchButton extends StatelessWidget {
  const _MatchButton(this.found);

  final _Match found;

  @override
  Widget build(BuildContext context) => FilledButton.tonal(
        onPressed: () {
          final state = AppScope.read(context);
          Navigator.of(context).popUntil((route) => route.isFirst);
          state.showMatchFor(found.set, found.member.id);
        },
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Flexible(child: Text('${found.match.pct!.round()}% match with your answers')),
            const SizedBox(width: 6),
            const Icon(Icons.arrow_forward, size: 18),
          ],
        ),
      );
}

/// Turnout and agreement, each against the chamber's median.
class _VotingRecord extends StatelessWidget {
  const _VotingRecord(this.member, {required this.explain});

  final Member member;

  /// Whether to spell out what each figure means.
  final bool explain;

  @override
  Widget build(BuildContext context) {
    final m = member;
    final chamber = AppScope.of(context).data.chamber(m.parliament);
    // A peer who has not voted lately still has a record from before.
    if (m.neverVoted && !m.isPeer) return Note(_whyNoVotes(m));

    // The medians are of the people sitting now. Someone who has left is not
    // measured against a chamber they were never in.
    final ch = m.isFormer ? null : chamber;
    final whipped = _whipped(m);
    final since = (chamber?.termStart ?? '').isEmpty ? 'the election' : chamber!.termStart;
    final rows = <Widget>[];
    void add(String label, double? value, double? median, String explanation) {
      if (rows.isNotEmpty) rows.add(SizedBox(height: explain ? 16 : 10));
      rows.add(MetricBar(
        label: label,
        value: value,
        median: median,
        semantics: median == null
            ? '$label ${_pct(value)}'
            : '$label ${_pct(value)}, chamber median ${_pct(median)}',
      ));
      if (explain) {
        rows.add(const SizedBox(height: 6));
        rows.add(Note(explanation));
      }
    }

    if (m.termKnown) {
      add(
        'Turnout',
        m.turnout,
        ch?.turnout,
        'Voted in ${thousands(m.termVotes)} of the ${thousands(m.eligible)} divisions they were '
            'eligible for since $since. Chamber median ${_pct(ch?.turnout)}. Absence is not always '
            'a choice: ministers are often excused and members can be paired.',
      );
    }
    add(
      whipped ? 'With their party' : 'With their group',
      m.partyAgreement,
      whipped ? ch?.partyAgreement : null,
      whipped
          ? 'Did the same as most of their party at the time in ${_pct(m.partyAgreement)} of '
              '${thousands(m.partyLineDivisions)} divisions on record. Almost every member sits near 99%.'
          : 'Did the same as most of the ${m.party.toLowerCase()} peers voting in '
              '${_pct(m.partyAgreement)} of ${thousands(m.partyLineDivisions)} divisions on '
              'record. Nobody instructs them how to vote, so this is not loyalty to a party.',
    );
    add(
      'With the result',
      m.chamberAgreement,
      ch?.chamberAgreement,
      'How often they were on the winning side. This mostly reflects being in government or opposition.',
    );

    final lowTurnout = !m.isPeer && m.termKnown && m.turnout != null && m.turnout! < 20;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...rows,
        if (ch != null) ...[
          const SizedBox(height: 10),
          const MedianKey(),
        ],
        if (m.isPeer && explain) ...[
          const SizedBox(height: 8),
          const Note('Peers are not expected to attend every vote: many have other work, and '
              'the typical peer votes in well under half.'),
        ],
        if (lowTurnout) ...[
          const SizedBox(height: 8),
          const Note('Turnout this low usually has a reason other than absence: presiding '
              'officers do not vote, and ministers are often excused.'),
        ],
        if (m.recordAsOf != null) ...[
          const SizedBox(height: 8),
          Note('Votes collected by Glasshouse from the legislature\'s own records, ${m.recordAsOf}.'
              '${m.termKnown ? '' : ' Turnout is shown once it has been recomputed for the current term.'}'),
        ],
      ],
    );
  }
}

/// A representative in a list. Tapping it opens their full record.
class MemberCard extends StatelessWidget {
  const MemberCard(this.member, {super.key});

  final Member member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final role = state.data.roleOf(member.parliament);
    final match = _matchFor(state, member);
    return Material(
      color: c.surface,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: c.line),
        borderRadius: BorderRadius.circular(14),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => MemberPage(member)),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(member.name, style: GlassText.display(20, color: c.ink)),
                  ),
                  const SizedBox(width: 10),
                  Padding(padding: const EdgeInsets.only(top: 3), child: Tag(role)),
                ],
              ),
              const SizedBox(height: 2),
              Text(memberLine(member, role), style: GlassText.body(13.5, color: c.ink2)),
              if (match != null) ...[
                const SizedBox(height: 12),
                _MatchButton(match),
              ],
              const SizedBox(height: 14),
              StatRow(_tiles(member)),
              const SizedBox(height: 16),
              _VotingRecord(member, explain: false),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerRight,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 40),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Flexible(
                        child: Text('Full record',
                            style: GlassText.body(14, weight: 600, color: c.accent)),
                      ),
                      Icon(Icons.chevron_right, size: 20, color: c.accent),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Everything held on one person in one chamber.
class MemberPage extends StatelessWidget {
  const MemberPage(this.member, {super.key});

  final Member member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final m = member;
    final ch = state.data.chamber(m.parliament);
    final role = state.data.roleOf(m.parliament);
    final house = ch?.house ?? m.parliament;
    final match = _matchFor(state, m);
    final set = state.quiz?.setFor(m.parliament);
    final qm = set?.byId[m.id];
    final segment = ch?.twfySegment;
    final elsewhere = [
      for (final r in state.data.recordsOf(m.id))
        if (r.parliament != m.parliament) r,
    ];

    return Scaffold(
      appBar: AppBar(title: Text(house, overflow: TextOverflow.ellipsis)),
      body: SafeArea(
        top: false,
        child: PageScroll(
          children: [
            Semantics(
              header: true,
              child: Text(m.name, style: GlassText.display(29, color: c.ink)),
            ),
            const SizedBox(height: 6),
            Text(memberLine(m, role, withArea: true), style: GlassText.body(15, color: c.ink2)),
            if (m.isFormer) ...[
              const SizedBox(height: 10),
              Note('No longer sits in the $house. This is what they did while they were there; '
                  'nothing is added from anything they have said or done since.'),
            ],
            if (m.isPeer) ...[
              const SizedBox(height: 10),
              const Note('Nobody votes for a member of the House of Lords: peers are appointed, '
                  'or sit by inheritance or office. They are here because they vote on the same '
                  'laws.'),
            ],
            if (match != null) ...[
              const SizedBox(height: 16),
              _MatchButton(match),
            ],
            const SizedBox(height: 16),
            Panel(child: StatRow(_tiles(m))),
            const SizedBox(height: 12),
            Panel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SectionTitle('Voting record'),
                  const SizedBox(height: 12),
                  _VotingRecord(m, explain: true),
                ],
              ),
            ),
            if (set != null && qm != null) _Issues(set, qm),
            if (m.topics.isNotEmpty) ...[
              const SizedBox(height: 12),
              _Topics(m),
            ],
            _Breaks(m),
            for (final other in elsewhere) ...[
              const SizedBox(height: 12),
              _Elsewhere(other),
            ],
            const SizedBox(height: 8),
            if (segment != null)
              ExtLink('Full record on TheyWorkForYou',
                  'https://www.theyworkforyou.com/$segment/${m.id}'),
            if (m.mnis != null && m.isSitting)
              ExtLink('Contact ${m.name}', 'https://members.parliament.uk/member/${m.mnis}/contact'),
          ],
        ),
      ),
    );
  }
}

/// The same person's record somewhere else: an MP who went to the Lords, or
/// to a devolved parliament.
class _Elsewhere extends StatelessWidget {
  const _Elsewhere(this.record);

  final Member record;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final data = AppScope.of(context).data;
    final house = data.chamber(record.parliament)?.house ?? record.parliament;
    return Panel(
      padding: EdgeInsets.zero,
      child: InkWell(
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(builder: (_) => MemberPage(record)),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 10, 12),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      record.isSitting
                          ? 'Now in the $house'
                          : record.isPeer
                              ? 'Also in the House of Lords'
                              : 'Used to sit in the $house',
                      style: GlassText.body(15, weight: 600, color: c.accent, height: 1.3),
                    ),
                    Text(memberLine(record, data.roleOf(record.parliament), withArea: true),
                        style: GlassText.body(12.5, color: c.muted, height: 1.35)),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, size: 20, color: c.accent),
            ],
          ),
        ),
      ),
    );
  }
}

/// Where a member's votes put them on each thing the quiz asks about.
class _Issues extends StatelessWidget {
  const _Issues(this.set, this.member);

  final QuizSet set;
  final QuizMember member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final statements = set.statements;
    final rows = <({Statement statement, double position, int votes})>[
      for (var i = 0; i < statements.length && i < member.pos.length; i++)
        if (member.pos[i] != null)
          (statement: statements[i], position: member.pos[i]!, votes: castCount(member.votes[i])),
    ]..sort((a, b) {
        final byPosition = b.position.compareTo(a.position);
        return byPosition != 0 ? byPosition : b.votes.compareTo(a.votes);
      });
    if (rows.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Panel(
        padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
        child: Disclosure(
          title: SectionTitle(set.isCommons
              ? 'How they voted on ${rows.length} issues'
              : 'How they voted in ${rows.length} of the quiz\'s votes'),
          builder: (context) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const AxisEnds(),
              for (final r in rows) ...[
                const SizedBox(height: 10),
                Semantics(
                  label: '${capitalise(r.statement.text)}: ${band(r.position, r.votes)}',
                  excludeSemantics: true,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      AxisBar(them: r.position),
                      Text(capitalise(r.statement.text),
                          style: GlassText.body(14, color: c.ink, height: 1.35)),
                      Text(capitalise(band(r.position, r.votes)),
                          style: GlassText.body(12.5, color: c.muted, height: 1.35)),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                Divider(color: c.line),
              ],
              const SizedBox(height: 10),
              Note(set.isCommons
                  ? 'From the votes that used the powers of Parliament. Take the quiz to '
                      'compare these with your own views.'
                  : 'One vote each, picked by a fixed rule rather than by us: see About. Take '
                      'the quiz to compare these with your own views.'),
            ],
          ),
        ),
      ),
    );
  }
}

/// The subjects a member's questions and speeches mention most.
class _Topics extends StatelessWidget {
  const _Topics(this.member);

  final Member member;

  @override
  Widget build(BuildContext context) {
    final topics = member.topics.take(5).toList();
    final peak = topics.first.count;
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SectionTitle('What they work on'),
          for (final t in topics) ...[
            const SizedBox(height: 12),
            MetricBar(
              label: t.name,
              value: t.share,
              fill: (100 * t.count / peak).clamp(2, 100).toDouble(),
              semantics: '${t.name}: mentioned in ${thousands(t.count)} of their questions and '
                  'speeches, ${t.share.toStringAsFixed(1)}%',
            ),
          ],
          const SizedBox(height: 10),
          const Note('The share of their questions and speeches that mention each subject. '
              'It shows what they spend time on, never which side they take.'),
          if (member.motions != null) ...[
            const SizedBox(height: 8),
            Note('Motions this parliament: proposed ${thousands(member.motions!.proposed)}, '
                'signed ${thousands(member.motions!.signed)}. Signing is unwhipped but changes no law.'),
          ],
        ],
      ),
    );
  }
}

/// The occasions a member did something other than most of their party.
class _Breaks extends StatelessWidget {
  const _Breaks(this.member);

  final Member member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final m = member;
    final whipped = _whipped(m);
    if (m.partyLineDivisions > 0 && m.rebellions == 0) {
      return Padding(
        padding: const EdgeInsets.only(top: 12),
        child: Note(m.isSitting || m.isPeer
            ? 'Has never voted differently from most of their ${whipped ? 'party' : 'group'}.'
            : 'Never voted differently from most of their party.'),
      );
    }
    if (m.receipts.isEmpty) return const SizedBox.shrink();
    final shown = m.receipts.length;
    final count = m.rebellions > shown ? 'latest $shown of ${thousands(m.rebellions)}' : '$shown';
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Panel(
        padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
        child: Disclosure(
          title: SectionTitle(whipped
              ? 'When they broke with their party · $count'
              : 'When they voted unlike their group · $count'),
          builder: (context) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final r in m.receipts) ...[
                Divider(color: c.line),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Text(r.date, style: GlassText.mono(12, color: c.muted)),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Voted ${r.theirVote} · ${whipped ? 'party' : 'group'} ${r.partyVote}',
                        textAlign: TextAlign.end,
                        style: GlassText.body(12.5, weight: 600, color: c.ink2, height: 1.3),
                      ),
                    ),
                  ],
                ),
                if (r.url != null)
                  ExtLink(r.title.isEmpty ? '(untitled division)' : r.title, r.url!, size: 14)
                else
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Text(r.title.isEmpty ? '(untitled division)' : r.title,
                        style: GlassText.body(14, color: c.ink)),
                  ),
                const SizedBox(height: 4),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
