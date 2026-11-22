/// How your answers line up with how MPs voted.
library;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../core/scoring.dart';
import '../core/text.dart';
import '../theme.dart';
import 'compass.dart';
import 'member.dart';
import 'scope.dart';
import 'widgets.dart';

const int _matchTab = 2;

class MatchPage extends StatefulWidget {
  const MatchPage({super.key});

  @override
  State<MatchPage> createState() => _MatchPageState();
}

class _MatchPageState extends State<MatchPage> {
  final ScrollController _scroll = ScrollController();

  /// An MP tapped on the compass.
  int? _picked;

  int _lastTab = -1;
  int? _lastFocus;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Arriving here, or changing who the screen is about, starts at the top.
    final state = AppScope.of(context);
    final arrived = state.tab == _matchTab && _lastTab != _matchTab;
    final refocused = state.focusId != _lastFocus;
    if (arrived || refocused) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scroll.hasClients) _scroll.jumpTo(0);
      });
    }
    if (refocused) _picked = null;
    _lastTab = state.tab;
    _lastFocus = state.focusId;
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const title = 'How your views line up with how they voted';
    final state = AppScope.of(context);
    final quiz = state.quiz;
    if (quiz == null) {
      return const PageScroll(children: [
        PageHeading(title, lede: 'The quiz is missing from this copy of the app.'),
      ]);
    }
    final n = state.answeredCount;
    if (!state.canShowMatch) {
      return PageScroll(
        controller: _scroll,
        children: [
          const PageHeading(title,
              lede: 'Answer at least $kMinAnswers statements and your match appears here.'),
          Panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('You have answered $n so far.',
                    style: GlassText.body(15, color: context.glass.ink2)),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () {
                    state.start();
                    state.go(1);
                  },
                  child: Text(n > 0 ? 'Continue the quiz' : 'Take the quiz'),
                ),
              ],
            ),
          ),
        ],
      );
    }

    final ranked = state.ranked();
    final focus = state.focus(ranked);
    final others = state.place == null
        ? const <Area>[]
        : state.place!.areas(state.data).where((a) => a.parliament != kUkParliament).toList();

    return PageScroll(
      controller: _scroll,
      children: [
        PageHeading(
          title,
          lede: 'Based on the $n statements you answered, compared with how each MP voted on '
              'the same things.',
        ),
        if (focus != null) ...[
          _Headline(focus),
          const SizedBox(height: 12),
        ],
        _CompassPanel(
          focus: focus?.member,
          picked: _picked,
          onPick: (id) => setState(() => _picked = id),
        ),
        const SizedBox(height: 12),
        _Closest(ranked),
        if (focus != null) ...[
          const SizedBox(height: 12),
          _Breakdown(focus.member),
        ],
        if (others.isNotEmpty) ...[
          const SizedBox(height: 12),
          _Devolved(others),
        ],
      ],
    );
  }
}

/// The figure the screen leads with, and who it is about.
class _Headline extends StatelessWidget {
  const _Headline(this.focus);

  final Focused focus;

  Future<void> _clear(BuildContext context, AppState state) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Clear your answers?'),
        content: Text('This removes all ${state.answeredCount} of your answers from this device. '
            'It cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: const Text('Keep them'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: const Text('Clear answers'),
          ),
        ],
      ),
    );
    if (confirmed ?? false) {
      state.clearAnswers();
      state.go(1);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final mp = focus.member;
    final match = state.matchOf(mp);
    final enough = state.isEnough(match);
    final record = state.data.memberById[mp.id];
    final k = match.overlap;
    final noSeat = mp.party.toLowerCase().contains('sinn');

    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              // Never more than half the width: at large text sizes the figure
              // shrinks to leave room for the name it belongs to.
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    enough ? '${match.pct!.round()}%' : '—',
                    semanticsLabel: enough ? '${match.pct!.round()} percent match' : 'No match',
                    style: GlassText.display(52, height: 1, color: c.ink),
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                flex: 2,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Eyebrow(switch (focus.reason) {
                      FocusReason.yours => 'Your MP',
                      FocusReason.chosen => 'Selected MP',
                      FocusReason.closest => 'Your closest match in the House',
                    }),
                    const SizedBox(height: 3),
                    Text(mp.name, style: GlassText.display(21, color: c.ink)),
                    const SizedBox(height: 2),
                    Text('${partyLabel(mp.party)} · ${mp.area}',
                        style: GlassText.body(13, color: c.muted, height: 1.35)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            enough
                ? 'Agreement across the $k statement${k == 1 ? '' : 's'} you answered that '
                    '${mp.name} has voted on. 100% would mean they always voted the way you '
                    'feel; 50% is no relationship either way.'
                : '${mp.name} has voted on too few of the statements you answered to give a '
                    'match.${noSeat ? ' Sinn Féin MPs do not take their seats, so they have no voting record.' : ''}',
            style: GlassText.body(14, color: c.ink2),
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton(
                onPressed: () {
                  state.start();
                  state.go(1);
                },
                child: const Text('Change answers'),
              ),
              if (record != null)
                OutlinedButton(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(builder: (_) => MemberPage(record)),
                  ),
                  child: const Text('Full record'),
                ),
              if (focus.reason != FocusReason.yours)
                OutlinedButton(
                  onPressed: () {
                    state.focusOn(null);
                    if (state.place == null) state.go(0);
                  },
                  child: Text(state.place == null ? 'Find my MP' : 'Back to my MP'),
                ),
            ],
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => _clear(context, state),
              style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 4)),
              child: const Text('Clear my answers and start again'),
            ),
          ),
        ],
      ),
    );
  }
}

class _CompassPanel extends StatelessWidget {
  const _CompassPanel({required this.focus, required this.picked, required this.onPick});

  final QuizMember? focus;
  final int? picked;
  final ValueChanged<int?> onPick;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final placed = isPlacedVisitor(state.ownCompass);
    final tapped = picked == null ? null : state.quiz!.byId[picked];
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Eyebrow('Where the votes sit'),
          const SizedBox(height: 8),
          Compass(state: state, focus: focus, picked: picked, onPick: onPick),
          const SizedBox(height: 10),
          Wrap(
            spacing: 16,
            runSpacing: 6,
            children: [
              KeyItem(mark: KeyMark.you, text: placed ? 'You' : 'You (not placed yet)'),
              if (focus != null) KeyItem(mark: KeyMark.them, text: focus!.name),
              const KeyItem(mark: KeyMark.others, text: 'Every other MP'),
            ],
          ),
          const SizedBox(height: 10),
          Semantics(
            liveRegion: true,
            child: tapped == null
                ? const Note('Tap a dot to see whose it is.')
                : Row(
                    children: [
                      Expanded(
                        child: Text.rich(
                          TextSpan(
                            children: [
                              TextSpan(
                                text: tapped.name,
                                style: GlassText.body(14, weight: 650, color: c.ink, height: 1.35),
                              ),
                              TextSpan(text: ' · ${partyLabel(tapped.party)}, ${tapped.area}'),
                            ],
                          ),
                          style: GlassText.body(14, color: c.ink2, height: 1.35),
                        ),
                      ),
                      if (tapped.id != focus?.id)
                        TextButton(
                          onPressed: () => state.focusOn(tapped.id),
                          child: const Text('Compare'),
                        ),
                    ],
                  ),
          ),
          const SizedBox(height: 8),
          Note(placed
              ? 'Placed from votes, not beliefs: a dot shows where an MP\'s votes sit on the '
                  'statements we could tag, which reflects government and opposition as well as '
                  'conviction. Party names mark each party\'s average; dots are nudged slightly '
                  'so MPs with identical records do not hide one another.'
              : 'Answer at least three statements on each axis to place yourself. The tags '
                  'behind this compass are ours; see About.'),
        ],
      ),
    );
  }
}

/// The MPs closest to you, and how each party compares on average.
class _Closest extends StatelessWidget {
  const _Closest(this.ranked);

  final List<Ranked> ranked;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.read(context);

    final byParty = <String, List<double>>{};
    for (final r in ranked) {
      byParty.putIfAbsent(partyLabel(r.member.party), () => []).add(r.match.pct!);
    }
    final parties = [
      for (final e in byParty.entries)
        if (isParty(e.key) && e.value.length >= 4)
          (name: e.key, n: e.value.length, average: e.value.reduce((a, b) => a + b) / e.value.length),
    ]..sort((a, b) => b.average.compareTo(a.average));

    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Eyebrow('MPs who voted most like you'),
          const SizedBox(height: 4),
          for (final (i, r) in ranked.take(6).indexed) ...[
            if (i > 0) Divider(color: c.line),
            InkWell(
              onTap: () => state.focusOn(r.member.id),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 52),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(r.member.name,
                                style: GlassText.body(15, weight: 600, color: c.accent, height: 1.3)),
                            Text('${partyLabel(r.member.party)} · ${r.member.area}',
                                style: GlassText.body(12.5, color: c.muted, height: 1.35)),
                          ],
                        ),
                      ),
                      const SizedBox(width: 12),
                      Text('${r.match.pct!.round()}%',
                          style: GlassText.mono(15, weight: 500, color: c.ink)),
                    ],
                  ),
                ),
              ),
            ),
          ],
          if (parties.isNotEmpty) ...[
            const SizedBox(height: 18),
            const Eyebrow('Average match by party'),
            for (final p in parties) ...[
              const SizedBox(height: 10),
              MetricBar(
                label: p.name,
                value: p.average,
                valueText: '${p.average.round()}%',
                semantics: '${p.name}: average match ${p.average.toStringAsFixed(1)}% '
                    'across ${p.n} MPs',
              ),
            ],
            const SizedBox(height: 10),
            const Note('Parties with at least four MPs. Because most votes are whipped, your '
                'MP\'s match is usually close to their party\'s.'),
          ],
        ],
      ),
    );
  }
}

class _Compared {
  _Compared(this.statement, this.index, this.you, this.important, this.them)
      : agreement = them == null ? null : 1 - (you - them).abs() / 2;

  final Statement statement;
  final int index;
  final double you;
  final bool important;
  final double? them;

  /// 1 for identical views, 0 for opposite ones; null if they never voted.
  final double? agreement;
}

/// Your answer beside their votes, one statement at a time.
class _Breakdown extends StatelessWidget {
  const _Breakdown(this.member);

  final QuizMember member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final statements = state.quiz!.statements;

    final groups = <(String, List<_Compared>)>[
      ('You agree', []),
      ('Somewhere in between', []),
      ('You disagree', []),
      ('No voting record on these', []),
    ];
    for (var i = 0; i < statements.length; i++) {
      final answer = state.answers[statements[i].id];
      final you = answer?.value;
      if (you == null) continue;
      final them = i < member.pos.length ? member.pos[i] : null;
      final row = _Compared(statements[i], i, you, answer!.important, them);
      final a = row.agreement;
      groups[a == null ? 3 : a >= 0.75 ? 0 : a > 0.25 ? 1 : 2].$2.add(row);
    }
    for (final (g, (_, rows)) in groups.indexed) {
      rows.sort((a, b) {
        final byWeight = (b.important ? 1 : 0) - (a.important ? 1 : 0);
        if (byWeight != 0) return byWeight;
        final x = a.agreement ?? 0, y = b.agreement ?? 0;
        return g == 2 ? x.compareTo(y) : y.compareTo(x);
      });
    }
    final unanswered = statements.length - state.answeredCount;

    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Eyebrow('Statement by statement · ${member.name}'),
          const SizedBox(height: 10),
          const Wrap(
            spacing: 16,
            runSpacing: 6,
            children: [
              KeyItem(mark: KeyMark.you, text: 'Your answer'),
              KeyItem(mark: KeyMark.them, text: 'Their votes'),
            ],
          ),
          const SizedBox(height: 6),
          const Note('Open a statement to see every vote behind it.'),
          for (final (title, rows) in groups)
            if (rows.isNotEmpty) ...[
              const SizedBox(height: 18),
              SectionTitle('$title · ${rows.length}'),
              const SizedBox(height: 6),
              // The chevron on each row takes this much off the axis below.
              const Padding(padding: EdgeInsets.only(right: 30), child: AxisEnds()),
              for (final row in rows) ...[
                Divider(color: c.line),
                _ComparedRow(row, member),
              ],
              Divider(color: c.line),
            ],
          if (unanswered > 0) ...[
            const SizedBox(height: 12),
            Note('$unanswered statement${unanswered == 1 ? ' is' : 's are'} not counted because '
                'you skipped or have not reached ${unanswered == 1 ? 'it' : 'them'}.'),
          ],
        ],
      ),
    );
  }
}

class _ComparedRow extends StatelessWidget {
  const _ComparedRow(this.row, this.member);

  final _Compared row;
  final QuizMember member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final st = row.statement;
    final codes = row.index < member.votes.length ? member.votes[row.index] : '';
    final theirs = row.them == null
        ? '${member.name} has not voted on this'
        : '${member.name} ${band(row.them!, castCount(codes))}';
    final yours = 'You ${answerLabel(row.you)}${row.important ? ' (matters a lot)' : ''}';

    return Disclosure(
      key: ValueKey('cmp-${member.id}-${st.id}'),
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text.rich(
            TextSpan(
              children: [
                TextSpan(text: capitalise(st.text)),
                if (row.important)
                  WidgetSpan(
                    alignment: PlaceholderAlignment.middle,
                    child: Padding(
                      padding: const EdgeInsets.only(left: 6),
                      child: Icon(Icons.star, size: 15, color: c.ink2),
                    ),
                  ),
              ],
            ),
            style: GlassText.body(14.5, color: c.ink, height: 1.35),
          ),
          const SizedBox(height: 4),
          AxisBar(them: row.them, you: row.you),
          const SizedBox(height: 2),
          Text('$yours · $theirs', style: GlassText.body(12.5, color: c.muted, height: 1.35)),
        ],
      ),
      builder: (context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Stored oldest first; the newest reads better at the top.
          for (var j = st.divisions.length - 1; j >= 0; j--) ...[
            Row(
              children: [
                Text(st.divisions[j].date, style: GlassText.mono(12, color: c.muted)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    kVoteCodeLabels[j < codes.length ? codes[j] : ''] ?? '—',
                    textAlign: TextAlign.end,
                    style: GlassText.body(12.5, weight: 600, color: c.ink2, height: 1.3),
                  ),
                ),
              ],
            ),
            ExtLink(st.divisions[j].title, st.divisions[j].url, size: 14),
            const SizedBox(height: 6),
          ],
          const Note('For, against and so on are relative to the statement, not to the '
              'wording of the motion.'),
          if (st.freeVote) ...[
            const SizedBox(height: 6),
            const Note('A free vote: parties did not instruct their MPs.'),
          ],
        ],
      ),
    );
  }
}

/// Representatives the quiz cannot cover, and why.
class _Devolved extends StatelessWidget {
  const _Devolved(this.areas);

  final List<Area> areas;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final data = AppScope.of(context).data;
    final who = [
      for (final a in areas)
        '${a.members.length} ${data.roleOf(a.parliament)}${a.members.length == 1 ? '' : 's'} '
            'for ${a.area}',
    ].join(', ');
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Eyebrow('Your other representatives'),
          const SizedBox(height: 8),
          Text(
            'There is no match yet for $who. Nobody publishes an independent mapping of votes '
            'to policies for the devolved legislatures, and we will not invent one quietly. '
            'Their voting records are under Reps.',
            style: GlassText.body(14, color: c.ink2),
          ),
        ],
      ),
    );
  }
}
