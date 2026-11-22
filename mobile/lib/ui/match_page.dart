/// How your answers line up with how your representatives voted.
library;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../core/scoring.dart';
import '../core/text.dart';
import '../theme.dart';
import 'compass.dart';
import 'member.dart';
import 'quiz_page.dart' show rolePlural;
import 'scope.dart';
import 'widgets.dart';

const int _matchTab = 2;
const String _title = 'How your views line up with how they voted';

String _house(AppState state, QuizSet set) =>
    state.data.chamber(set.parliament)?.house ?? set.parliament;

/// Why a member has no match, in a few words.
String _whyNoMatch(QuizSet set, QuizMember m, MatchResult r) {
  if (r.overlap == 0 && r.eligible > 0) {
    // Sinn Féin MPs do not sit at Westminster. Its MLAs do sit, and vote.
    if (set.isCommons && m.party.toLowerCase().contains('sinn')) return 'does not take their seat';
    return 'has not voted on these';
  }
  if (r.eligible == 0) return 'was not a member for these votes';
  return 'too few votes in common';
}

/// What a figure rests on, in a few words: how much the two have in common,
/// or, where the member skipped most of it, how much of what they could have
/// voted on they did.
String _basis(QuizSet set, MatchResult r, {required bool enough}) {
  final things = set.isCommons ? 'statements' : 'votes';
  if (enough) return '${r.overlap} $things in common';
  return 'voted on ${r.overlap} of ${r.eligible} $things they could have';
}

/// The same in a sentence, for a figure that rests on under half.
String _partial(MatchResult r, {required String role, required String list}) {
  final missed = r.eligible - r.overlap;
  final article = RegExp('^M[A-Z]').hasMatch(role) ? 'an' : 'a';
  return ' They were $article $role for $missed more that you answered and did not vote on '
      '${missed == 1 ? 'it' : 'them'}, so this is a partial picture, and they are left out '
      'of the $list below.';
}

class MatchPage extends StatefulWidget {
  const MatchPage({super.key});

  @override
  State<MatchPage> createState() => _MatchPageState();
}

class _MatchPageState extends State<MatchPage> {
  final ScrollController _scroll = ScrollController();
  final Map<String, GlobalKey> _blocks = {};

  /// An MP tapped on the compass.
  int? _picked;
  int _lastTab = -1;

  GlobalKey _block(QuizSet set) => _blocks.putIfAbsent(set.parliament, GlobalKey.new);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final state = AppScope.of(context);
    final wanted = state.reveal;
    if (state.tab == _matchTab && wanted != null) {
      // Arriving from one member's page: open at their results.
      state.reveal = null;
      _picked = null;
      _bringUp(wanted);
    } else if (state.tab == _matchTab && _lastTab != _matchTab) {
      // Arriving any other way starts at the top.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scroll.hasClients) _scroll.jumpTo(0);
      });
    }
    _lastTab = state.tab;
  }

  /// Scrolls one parliament's results to the top of the screen.
  void _bringUp(String parliament) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final target = _blocks[parliament]?.currentContext;
      if (!mounted || target == null) return;
      Scrollable.ensureVisible(
        target,
        duration: reducedMotion(context) ? Duration.zero : const Duration(milliseconds: 280),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  /// Makes one member the subject of their parliament's results, and brings
  /// those results up.
  void _show(QuizSet set, int memberId) {
    final state = AppScope.read(context);
    if (set.isCommons) {
      _picked = null;
      state.focusOn(memberId);
    } else {
      state.focusOnIn(set, memberId);
    }
    _bringUp(set.parliament);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final quiz = state.quiz;
    if (quiz == null) {
      return const PageScroll(children: [
        PageHeading(_title, lede: 'The quiz is missing from this copy of the app.'),
      ]);
    }
    if (!state.hasAnyMatch) {
      final n = state.answeredCount;
      return PageScroll(
        controller: _scroll,
        children: [
          const PageHeading(_title,
              lede: 'Answer at least $kMinAnswers statements in any part of the quiz and your '
                  'match appears here.'),
          Panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('You have answered $n so far.',
                    style: GlassText.body(15, color: context.glass.ink2)),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () {
                    if (n > 0) state.start();
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

    final commons = quiz.commons;
    final ranked = state.canShowMatch ? state.ranked() : const <Ranked>[];
    final focus = state.canShowMatch ? state.focus(ranked) : null;
    final n = state.answeredCount;

    return PageScroll(
      controller: _scroll,
      children: [
        PageHeading(
          _title,
          lede: 'Based on the $n statement${n == 1 ? '' : 's'} you answered, compared with how '
              'each member voted on the same things.',
        ),
        _YourRepresentatives(onShow: _show),
        if (focus != null) ...[
          SizedBox(key: _block(commons), height: 24),
          Semantics(
            header: true,
            child: Text('House of Commons', style: GlassText.display(24, color: context.glass.ink)),
          ),
          const SizedBox(height: 12),
          _Headline(focus),
          const SizedBox(height: 12),
          _CompassPanel(
            focus: focus.member,
            picked: _picked,
            onPick: (id) => setState(() => _picked = id),
            onCompare: (id) => _show(commons, id),
          ),
          const SizedBox(height: 12),
          _Closest(commons, ranked, onShow: _show),
          const SizedBox(height: 12),
          _Breakdown(commons, focus.member),
        ],
        for (final set in quiz.chambers.values)
          if (state.canShowMatchFor(set)) ...[
            SizedBox(key: _block(set), height: 24),
            _ChamberResults(set, onShow: _show),
          ],
        const SizedBox(height: 16),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: () => _confirmClear(context, state),
            style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 4)),
            child: const Text('Clear my answers and start again'),
          ),
        ),
      ],
    );
  }
}

Future<void> _confirmClear(BuildContext context, AppState state) async {
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

typedef _Show = void Function(QuizSet set, int memberId);

/// Everyone who represents the visitor, in every parliament, with their match.
/// This is the answer to the question the app exists for.
class _YourRepresentatives extends StatelessWidget {
  const _YourRepresentatives({required this.onShow});

  final _Show onShow;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final quiz = state.quiz!;
    final place = state.place;
    if (place == null) {
      return Panel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Eyebrow('Your representatives'),
            const SizedBox(height: 8),
            Text('Choose where you live to see how your own representatives compare. '
                'Until then, this screen shows whoever voted most like you.',
                style: GlassText.body(14, color: c.ink2)),
            const SizedBox(height: 10),
            OutlinedButton(onPressed: () => state.go(0), child: const Text('Find my representatives')),
          ],
        ),
      );
    }

    final blocks = <Widget>[];
    for (final set in quiz.sets) {
      final mine = state.repsIn(set);
      if (mine.isEmpty) continue;
      final house = _house(state, set);
      final role = rolePlural(state, set);
      if (blocks.isNotEmpty) blocks.add(const SizedBox(height: 14));
      blocks.add(SectionTitle(house));
      if (!state.canShowMatchFor(set)) {
        final section = state.sectionFor(set);
        blocks.add(const SizedBox(height: 4));
        final answered = state.answeredInSet(set);
        final who = mine.length == 1
            ? '${state.data.roleOf(set.parliament)}, ${mine.first.name}, compares'
            : '${mine.length} $role compare';
        blocks.add(Text(
          set.isCommons
              ? 'Answer at least $kMinAnswers of its statements to see how your $who.'
              : 'It votes on different things from Westminster, so it has its own questions. '
                  'Answer at least $kMinAnswers to see how your $who.'
                  '${answered > 0 ? ' You have answered $answered.' : ''}',
          style: GlassText.body(14, color: c.ink2),
        ));
        if (section != null) {
          blocks.add(const SizedBox(height: 8));
          blocks.add(Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(
              onPressed: () {
                state.openSection(section.id);
                state.go(1);
              },
              child: Text(set.isCommons ? 'Answer its statements' : 'Answer its ${set.statements.length} questions'),
            ),
          ));
        }
        continue;
      }
      final rows = [for (final m in mine) (member: m, match: state.matchOf(m, set))]
        ..sort((a, b) {
          final x = state.isShown(a.match, set) ? a.match.pct! : -1.0;
          final y = state.isShown(b.match, set) ? b.match.pct! : -1.0;
          return y.compareTo(x);
        });
      for (final row in rows) {
        final shown = state.isShown(row.match, set);
        final party = partyLabel(row.member.party);
        blocks.add(InkWell(
          onTap: () => onShow(set, row.member.id),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(row.member.name,
                            style: GlassText.body(15, weight: 600, color: c.accent, height: 1.3)),
                        Text(
                          shown
                              ? '$party · ${_basis(set, row.match, enough: state.isEnough(row.match, set))}'
                              : '$party · ${_whyNoMatch(set, row.member, row.match)}',
                          style: GlassText.body(12.5, color: c.muted, height: 1.35),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(shown ? '${row.match.pct!.round()}%' : '—',
                      style: GlassText.display(22, color: c.ink, height: 1)),
                ],
              ),
            ),
          ),
        ));
      }
    }
    if (blocks.isEmpty) return const SizedBox.shrink();
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Eyebrow('Your representatives · ${place.label}'),
          const SizedBox(height: 10),
          ...blocks,
          const SizedBox(height: 10),
          const Note('Each figure compares your answers with that member\'s own votes in their '
              'own parliament. Different parliaments vote on different things, so compare '
              'members within one, not across.'),
        ],
      ),
    );
  }
}

/// The figure the Commons results lead with, and who it is about.
class _Headline extends StatelessWidget {
  const _Headline(this.focus);

  final Focused focus;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final mp = focus.member;
    final match = state.matchOf(mp);
    final enough = state.isShown(match);
    final partial = enough && !state.isEnough(match);
    final record = state.data.recordIn(mp.id, kUkParliament);
    final k = match.overlap;
    final noSeat = mp.party.toLowerCase().contains('sinn');

    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              // Never more than a third of the width: at large text sizes the
              // figure shrinks to leave room for the name it belongs to.
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
                      FocusReason.chosen => mp.former ? 'Former MP' : 'Selected MP',
                      FocusReason.closest => 'Your closest match in the House',
                    }),
                    const SizedBox(height: 3),
                    Text(mp.name, style: GlassText.display(21, color: c.ink)),
                    const SizedBox(height: 2),
                    Text(
                      '${partyLabel(mp.party)} · ${mp.area}'
                      '${mp.former && mp.to.isNotEmpty ? ' · ${mp.from}–${mp.to}' : ''}',
                      style: GlassText.body(13, color: c.muted, height: 1.35),
                    ),
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
                    '${partial ? _partial(match, role: 'MP', list: 'list of closest MPs') : ''}'
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
                  state.openSection(kCommonsSection);
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
        ],
      ),
    );
  }
}

class _CompassPanel extends StatelessWidget {
  const _CompassPanel({
    required this.focus,
    required this.picked,
    required this.onPick,
    required this.onCompare,
  });

  final QuizMember? focus;
  final int? picked;
  final ValueChanged<int?> onPick;
  final ValueChanged<int> onCompare;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final own = state.ownCompass;
    final placed = isPlacedVisitor(own);
    final tapped = picked == null ? null : state.quiz!.byId[picked];
    final section = state.sections.where((s) => s.id == kEarlierSection).firstOrNull;
    final moreToAnswer = section != null && state.answeredIn(section) < section.order.length;
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
                          onPressed: () => onCompare(tapped.id),
                          child: const Text('Compare'),
                        ),
                    ],
                  ),
          ),
          const SizedBox(height: 8),
          Note(placed
              ? 'You are placed from ${own.econWeight.round()} economic and '
                  '${own.socialWeight.round()} social statements. Placed from votes, not '
                  'beliefs: a dot shows where an MP\'s votes sit on the statements we could '
                  'tag, which reflects government and opposition as well as conviction. Party '
                  'names mark each party\'s average; dots are nudged slightly so MPs with '
                  'identical records do not hide one another.'
              : 'Answer at least three statements on each axis to place yourself. The tags '
                  'behind this compass are ours; see About.'),
          if (moreToAnswer) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () {
                  state.openSection(kEarlierSection);
                  state.go(1);
                },
                style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 4)),
                child: const Text('Sharpen it: answer earlier parliaments'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// The members closest to you, and how each party compares on average.
class _Closest extends StatelessWidget {
  const _Closest(this.set, this.ranked, {required this.onShow});

  final QuizSet set;
  final List<Ranked> ranked;
  final _Show onShow;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final role = rolePlural(state, set);

    final byParty = <String, List<double>>{};
    for (final r in ranked) {
      byParty.putIfAbsent(partyLabel(r.member.party), () => []).add(r.match.pct!);
    }
    // Enough members for an average to mean something: four in the Commons,
    // three in the smaller chambers.
    final least = set.isCommons ? 4 : 3;
    final parties = [
      for (final e in byParty.entries)
        if (isParty(e.key) && e.value.length >= least)
          (name: e.key, n: e.value.length, average: e.value.reduce((a, b) => a + b) / e.value.length),
    ]..sort((a, b) => b.average.compareTo(a.average));

    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Eyebrow('$role who voted most like you'),
          const SizedBox(height: 4),
          if (ranked.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Note('No $role have enough votes in common with your answers yet.'),
            ),
          for (final (i, r) in ranked.take(6).indexed) ...[
            if (i > 0) Divider(color: c.line),
            InkWell(
              onTap: () => onShow(set, r.member.id),
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
                    'across ${p.n} $role',
              ),
            ],
            const SizedBox(height: 10),
            Note('Parties with at least ${least == 4 ? 'four' : 'three'} $role. Because most '
                'votes are whipped, a member\'s match is usually close to their party\'s.'),
          ],
          const SizedBox(height: 10),
          Note('Only $role who voted on at least half of what you answered, of the votes '
              'held while they were a member, are ranked or averaged here.'),
        ],
      ),
    );
  }
}

/// One devolved legislature: who its results are about, the closest members,
/// and vote by vote.
class _ChamberResults extends StatelessWidget {
  const _ChamberResults(this.set, {required this.onShow});

  final QuizSet set;
  final _Show onShow;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final ranked = state.ranked(set);
    final focus = state.focusIn(set, ranked);
    final house = _house(state, set);
    final answered = state.answeredInSet(set);
    final section = state.sectionFor(set);
    final mine = {for (final m in state.repsIn(set)) m.id};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text(house, style: GlassText.display(24, color: c.ink)),
        ),
        const SizedBox(height: 4),
        Text(
          'From the $answered of its ${set.statements.length} votes you answered. Each is one '
          'vote the ${house.split(' ').last} actually held: you said how you would have voted, '
          'and this is how they did.',
          style: GlassText.body(14, color: c.ink2),
        ),
        const SizedBox(height: 12),
        if (focus != null) ...[
          _ChamberHeadline(
            set,
            focus,
            // Yours, one you picked, or simply whoever voted most like you.
            why: mine.contains(focus.id)
                ? FocusReason.yours
                : state.pickedIn(set)
                    ? FocusReason.chosen
                    : FocusReason.closest,
          ),
          const SizedBox(height: 12),
        ],
        _Closest(set, ranked, onShow: onShow),
        if (focus != null) ...[
          const SizedBox(height: 12),
          _Breakdown(set, focus),
        ],
        if (section != null && answered < set.statements.length) ...[
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () {
                state.openSection(section.id);
                state.go(1);
              },
              style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 4)),
              child: Text('Answer more of its votes (${set.statements.length - answered} left)'),
            ),
          ),
        ],
      ],
    );
  }
}

class _ChamberHeadline extends StatelessWidget {
  const _ChamberHeadline(this.set, this.member, {required this.why});

  final QuizSet set;
  final QuizMember member;
  final FocusReason why;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final match = state.matchOf(member, set);
    final enough = state.isShown(match, set);
    final partial = enough && !state.isEnough(match, set);
    final role = state.data.roleOf(set.parliament);
    final record = state.data.recordIn(member.id, set.parliament);
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    enough ? '${match.pct!.round()}%' : '—',
                    semanticsLabel: enough ? '${match.pct!.round()} percent match' : 'No match',
                    style: GlassText.display(44, height: 1, color: c.ink),
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                flex: 2,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Eyebrow(switch (why) {
                      FocusReason.yours => 'Your $role',
                      FocusReason.chosen => 'Selected $role',
                      FocusReason.closest => 'The $role who voted most like you',
                    }),
                    const SizedBox(height: 3),
                    Text(member.name, style: GlassText.display(20, color: c.ink)),
                    const SizedBox(height: 2),
                    Text('${partyLabel(member.party)} · ${member.area}',
                        style: GlassText.body(13, color: c.muted, height: 1.35)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            enough
                ? 'Agreement across the ${match.overlap} of these votes that ${member.name} '
                    'took part in.'
                    '${partial ? _partial(match, role: role, list: 'list of the closest') : ''}'
                : '${member.name} ${_whyNoMatch(set, member, match)}, so there is no match to show.',
            style: GlassText.body(14, color: c.ink2),
          ),
          if (record != null) ...[
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(builder: (_) => MemberPage(record)),
                ),
                child: const Text('Full record'),
              ),
            ),
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
  const _Breakdown(this.set, this.member);

  final QuizSet set;
  final QuizMember member;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final statements = set.statements;

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
    final unanswered = statements.length - state.answeredInSet(set);

    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Eyebrow('${set.isCommons ? 'Statement by statement' : 'Vote by vote'} · ${member.name}'),
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
          Note(set.isCommons
              ? 'Open a statement to see every vote behind it.'
              : 'Open one to see the vote itself.'),
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
            Note('$unanswered ${set.isCommons ? 'statement' : 'vote'}${unanswered == 1 ? ' is' : 's are'} '
                'not counted because you skipped or have not reached '
                '${unanswered == 1 ? 'it' : 'them'}.'),
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
        ? couldVote(codes)
            ? '${member.name} did not vote on this'
            : '${member.name} was not a member when this was voted on'
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
                    kVoteCodeLabels[j < codes.length ? codes[j] : '.'] ?? '—',
                    textAlign: TextAlign.end,
                    style: GlassText.body(12.5, weight: 600, color: c.ink2, height: 1.3),
                  ),
                ),
              ],
            ),
            ExtLink(st.divisions[j].title, st.divisions[j].url, size: 14),
            const SizedBox(height: 6),
          ],
          if (st.divisions.length > 1 || st.divisions.first.alignment != 'agree')
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
