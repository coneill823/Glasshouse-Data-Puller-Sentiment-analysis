/// Find a place, see who represents it.
library;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../core/place.dart';
import '../core/postcode.dart';
import '../core/text.dart';
import '../theme.dart';
import 'local.dart';
import 'member.dart';
import 'quiz_page.dart' show rolePlural;
import 'scope.dart';
import 'widgets.dart';

class RepsPage extends StatefulWidget {
  const RepsPage({super.key});

  @override
  State<RepsPage> createState() => _RepsPageState();
}

class _RepsPageState extends State<RepsPage> {
  /// More matches than this and the list pushes the results off the screen.
  static const int _maxHits = 8;

  final TextEditingController _query = TextEditingController();
  final FocusNode _focus = FocusNode();
  final ScrollController _scroll = ScrollController();
  final GlobalKey _placeKey = GlobalKey();

  List<Area> _hits = const [];

  /// People found by name who are not in a seat: former members, peers, and
  /// candidates in an election that has not happened yet.
  List<Member> _people = const [];
  List<({Candidate candidate, Ballot ballot})> _standing = const [];
  String _message = '';
  bool _busy = false;

  @override
  void dispose() {
    _query.dispose();
    _focus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _nothingFound() {
    _hits = const [];
    _people = const [];
    _standing = const [];
  }

  void _onChanged(String q) {
    final data = AppScope.read(context).data;
    setState(() {
      if (looksLikePostcode(q)) {
        _nothingFound();
        _message = 'Tap Find to look up ${q.trim().toUpperCase()}.';
      } else if (looksLikePartPostcode(q)) {
        _nothingFound();
        _message = 'Type the whole postcode, then tap Find.';
      } else {
        _hits = data.search(q);
        _people = data.searchOthers(q, limit: 6);
        _standing = data.searchCandidates(q, limit: 4);
        _message = norm(q).length >= 2 && _hits.isEmpty && _people.isEmpty && _standing.isEmpty
            ? 'No constituency or representative matches that.'
            : '';
      }
    });
  }

  Future<void> _submit() async {
    final q = _query.text.trim();
    if (q.isEmpty || _busy) return;
    if (looksLikePostcode(q)) {
      await _lookUp(q);
      return;
    }
    if (looksLikePartPostcode(q)) {
      setState(() => _message = 'That is only part of a postcode. Type all of it, like G12 8QQ.');
      return;
    }
    final data = AppScope.read(context).data;
    final found = data.search(q);
    final people = data.searchOthers(q, limit: 6).length + data.searchCandidates(q, limit: 4).length;
    if (found.length == 1 && people == 0) {
      _choose(found.first);
    } else if (found.isEmpty && people == 0) {
      setState(() => _message = 'No constituency or representative matches that. Try a postcode.');
    } else {
      _focus.unfocus();
    }
  }

  Future<void> _lookUp(String raw) async {
    final state = AppScope.read(context);
    final postcodes = AppScope.postcodesOf(context);
    setState(() {
      _busy = true;
      _nothingFound();
      _message = 'Looking up ${raw.replaceAll(RegExp(r'\s+'), '').toUpperCase()}…';
    });
    try {
      final place = await postcodes.find(raw);
      if (!mounted) return;
      state.setPlace(place);
      setState(() {
        _busy = false;
        _message = '';
      });
      _reveal();
    } on PostcodeException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _message = e.message;
      });
    }
  }

  void _choose(Area area) {
    AppScope.read(context).setPlace(Place.area(area));
    setState(() {
      _nothingFound();
      _message = '';
    });
    _reveal();
  }

  void _clear() {
    _query.clear();
    setState(() {
      _nothingFound();
      _message = '';
    });
  }

  /// Puts the results at the top of the screen and the keyboard away.
  void _reveal() {
    _focus.unfocus();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final target = _placeKey.currentContext;
      if (!mounted || target == null) return;
      Scrollable.ensureVisible(
        target,
        duration: reducedMotion(context) ? Duration.zero : const Duration(milliseconds: 280),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final data = state.data;
    final shown = state.shownPlace;
    final areas = shown.place.areas(data);
    final total = areas.fold<int>(0, (n, a) => n + a.members.length);

    return PageScroll(
      controller: _scroll,
      children: [
        const PageHeading(
          'Who represents you?',
          lede: 'Find your representatives and see their record: how often they vote, when they '
              'have broken with their party, and what they spend their time on.',
        ),
        Text('Postcode, constituency, or a politician\'s name',
            style: GlassText.body(13, weight: 600, color: c.ink2)),
        const SizedBox(height: 6),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                controller: _query,
                focusNode: _focus,
                onChanged: _onChanged,
                onSubmitted: (_) => _submit(),
                textInputAction: TextInputAction.search,
                autocorrect: false,
                enableSuggestions: false,
                style: GlassText.body(16, color: c.ink),
                decoration: InputDecoration(
                  hintText: 'e.g. BT7 1NN, Glasgow North',
                  suffixIcon: _query.text.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.close, size: 20),
                          tooltip: 'Clear',
                          onPressed: _clear,
                        ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(
              onPressed: _busy ? null : _submit,
              style: FilledButton.styleFrom(minimumSize: const Size(72, 52)),
              child: _busy
                  ? SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: c.muted),
                    )
                  : const Text('Find'),
            ),
          ],
        ),
        if (_hits.isNotEmpty) ...[
          const SizedBox(height: 8),
          _Hits(_hits.take(_maxHits).toList(), onChoose: _choose),
          if (_hits.length > _maxHits)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Note('Showing $_maxHits of ${_hits.length}'
                  '${_hits.length >= 36 ? ' or more' : ''}. Keep typing to narrow it down.'),
            ),
        ],
        if (_people.isNotEmpty || _standing.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text(
            _hits.isEmpty ? 'People' : 'People not in a seat now',
            style: GlassText.body(13, weight: 600, color: c.ink2),
          ),
          const SizedBox(height: 6),
          _PeopleHits(_people, _standing),
        ],
        Semantics(
          liveRegion: true,
          child: _message.isEmpty
              ? const SizedBox(height: 0)
              : Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_message, style: GlassText.body(14, color: c.ink2)),
                ),
        ),
        SizedBox(key: _placeKey, height: 24),
        Eyebrow(shown.isExample
            ? 'An example — search above for yours'
            : '$total representative${total == 1 ? '' : 's'}'),
        const SizedBox(height: 2),
        Semantics(
          header: true,
          child: Text(shown.place.label, style: GlassText.display(24, color: c.ink)),
        ),
        for (final note in shown.place.notes) ...[
          const SizedBox(height: 10),
          _Notice(note),
        ],
        for (final area in areas) ...[
          const SizedBox(height: 20),
          _AreaHeading(area, house: data.chamber(area.parliament)?.house ?? area.parliament),
          for (final m in area.members) ...[
            const SizedBox(height: 10),
            MemberCard(m),
          ],
        ],
        const SizedBox(height: 20),
        const _QuizPrompt(),
        if (!shown.isExample) ...[
          const SizedBox(height: 24),
          ElectionsHere(shown.place),
          const SizedBox(height: 24),
          CouncillorsHere(shown.place),
        ],
      ],
    );
  }
}

/// Places that match what has been typed.
class _Hits extends StatelessWidget {
  const _Hits(this.areas, {required this.onChoose});

  final List<Area> areas;
  final ValueChanged<Area> onChoose;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final data = AppScope.of(context).data;
    return Material(
      color: c.surface,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: c.line),
        borderRadius: BorderRadius.circular(12),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < areas.length; i++) ...[
            if (i > 0) Divider(color: c.line),
            InkWell(
              onTap: () => onChoose(areas[i]),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(areas[i].area,
                            style: GlassText.body(15, weight: 600, color: c.ink, height: 1.3)),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        '${data.roleOf(areas[i].parliament)}${areas[i].isRegion ? ' · region' : ''}',
                        style: GlassText.mono(11, weight: 500, color: c.muted),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// People who match what has been typed but hold no seat to list them under.
class _PeopleHits extends StatelessWidget {
  const _PeopleHits(this.people, this.standing);

  final List<Member> people;
  final List<({Candidate candidate, Ballot ballot})> standing;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final data = AppScope.of(context).data;
    final rows = <({String name, String what, String detail, VoidCallback open})>[
      for (final m in people)
        (
          name: m.name,
          what: m.isPeer ? 'Peer' : 'Former ${data.roleOf(m.parliament)}',
          detail: [
            if (m.party.isNotEmpty) m.party,
            if (m.area.isNotEmpty) m.area,
            if (m.isFormer && m.until.isNotEmpty) 'until ${m.until}',
          ].join(' · '),
          open: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => MemberPage(m)),
              ),
        ),
      for (final s in standing)
        (
          name: s.candidate.name,
          what: 'Candidate',
          detail: '${s.candidate.party} · ${ballotWhere(s.ballot)} · '
              '${longDate(s.ballot.date)}',
          open: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => BallotPage(s.ballot, highlight: s.candidate.name),
                ),
              ),
        ),
    ];
    return Material(
      color: c.surface,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: c.line),
        borderRadius: BorderRadius.circular(12),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (final (i, row) in rows.indexed) ...[
            if (i > 0) Divider(color: c.line),
            InkWell(
              onTap: row.open,
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(row.name,
                                style: GlassText.body(15, weight: 600, color: c.ink, height: 1.3)),
                            if (row.detail.isNotEmpty)
                              Text(row.detail,
                                  style: GlassText.body(12.5, color: c.muted, height: 1.35)),
                          ],
                        ),
                      ),
                      const SizedBox(width: 10),
                      Text(row.what, style: GlassText.mono(11, weight: 500, color: c.muted)),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Something the visitor should know about how their place was found.
class _Notice extends StatelessWidget {
  const _Notice(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return DecoratedBox(
      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(10)),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Icon(Icons.info_outline, size: 18, color: c.ink2),
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(text, style: GlassText.body(13.5, color: c.ink2))),
          ],
        ),
      ),
    );
  }
}

class _AreaHeading extends StatelessWidget {
  const _AreaHeading(this.area, {required this.house});

  final Area area;
  final String house;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Semantics(
      header: true,
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(text: house, style: GlassText.body(14, weight: 650, color: c.ink)),
            TextSpan(text: ' · ${area.area}${area.isRegion ? ' (regional list)' : ''}'),
          ],
        ),
        style: GlassText.body(14, color: c.muted),
      ),
    );
  }
}

/// The next step once you have seen who represents you.
class _QuizPrompt extends StatelessWidget {
  const _QuizPrompt();

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final quiz = state.quiz;
    if (quiz == null) return const SizedBox.shrink();
    final n = state.answeredCount;
    final ready = state.hasAnyMatch;
    // Each parliament the visitor is represented in has questions of its own.
    final waiting = [
      for (final s in state.sections)
        if (s.id != kEarlierSection &&
            state.hasRepsIn(s.set) &&
            !state.canShowMatchFor(s.set) &&
            (ready || s.isDevolved))
          s,
    ];
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            ready
                ? 'You have answered $n question${n == 1 ? '' : 's'}'
                : 'Do their votes match your views?',
            style: GlassText.display(20, color: c.ink),
          ),
          const SizedBox(height: 6),
          Text(
            ready
                ? 'See how the votes of the people who represent you line up with what you said.'
                : '${quiz.commons.coreCount} statements, each one something MPs have actually '
                    'voted on. Your answers never leave this device.',
            style: GlassText.body(14, color: c.ink2),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: () => state.go(ready ? 2 : 1),
            child: Text(ready
                ? 'See your match'
                : n > 0
                    ? 'Continue the quiz'
                    : 'Take the quiz'),
          ),
          for (final s in waiting) ...[
            const SizedBox(height: 12),
            Text(
              s.isDevolved
                  ? 'Your ${rolePlural(state, s.set)} are matched on the ${s.title}\'s own '
                      'votes, which are different questions.'
                  : 'Your MP is matched on what the House of Commons has voted on.',
              style: GlassText.body(14, color: c.ink2),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: () {
                state.openSection(s.id);
                state.go(1);
              },
              child: Text(s.isDevolved
                  ? 'Answer the ${s.title} questions'
                  : 'Answer the House of Commons statements'),
            ),
          ],
        ],
      ),
    );
  }
}
