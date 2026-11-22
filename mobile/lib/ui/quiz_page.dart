/// One statement at a time, five ways to answer.
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../core/scoring.dart';
import '../core/text.dart';
import '../theme.dart';
import 'scope.dart';
import 'widgets.dart';

class QuizPage extends StatefulWidget {
  const QuizPage({super.key});

  @override
  State<QuizPage> createState() => _QuizPageState();
}

class _QuizPageState extends State<QuizPage> {
  /// Long enough to see your answer register before the next statement.
  static const Duration _pause = Duration(milliseconds: 280);

  final ScrollController _scroll = ScrollController();
  Timer? _moveOn;

  @override
  void dispose() {
    _moveOn?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  void _answer(AppState state, double value) {
    _moveOn?.cancel();
    final asked = state.current.id;
    state.answer(value);
    _moveOn = Timer(_pause, () {
      if (mounted && state.current.id == asked) _next(state);
    });
  }

  void _next(AppState state) {
    _moveOn?.cancel();
    if (state.step(1)) {
      _toTop();
    } else if (state.canShowMatch) {
      state.go(2);
    }
  }

  void _back(AppState state) {
    _moveOn?.cancel();
    if (state.step(-1)) _toTop();
  }

  void _skip(AppState state) {
    state.skip();
    _next(state);
  }

  void _toTop() {
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final quiz = state.quiz;
    if (quiz == null) {
      return const PageScroll(children: [
        PageHeading('Where do you stand?', lede: 'The quiz is missing from this copy of the app.'),
      ]);
    }
    if (!state.started) return _Intro(quiz);

    final c = context.glass;
    final statement = state.current;
    final given = state.answerFor(statement);
    final total = state.order.length;
    final still = reducedMotion(context);

    return Column(
      children: [
        Expanded(
          child: PageScroll(
            controller: _scroll,
            children: [
              Wrap(
                alignment: WrapAlignment.spaceBetween,
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 12,
                runSpacing: 6,
                children: [
                  Eyebrow('Statement ${state.at + 1} of $total'),
                  if (statement.group.isNotEmpty) Tag(statement.group),
                ],
              ),
              const SizedBox(height: 10),
              _Progress((state.at + 1) / total),
              const SizedBox(height: 20),
              AnimatedSwitcher(
                duration: still ? Duration.zero : const Duration(milliseconds: 200),
                switchInCurve: Curves.easeOut,
                layoutBuilder: (current, previous) => Stack(
                  alignment: Alignment.topLeft,
                  children: [...previous, ?current],
                ),
                child: _Asked(statement, key: ValueKey(statement.id)),
              ),
              const SizedBox(height: 20),
              for (final (label, value) in kAnswerScale) ...[
                _AnswerButton(
                  label: label,
                  selected: given?.value == value,
                  onTap: () => _answer(state, value),
                ),
                const SizedBox(height: 8),
              ],
              Row(
                children: [
                  Expanded(
                    child: _Important(
                      value: given?.important ?? false,
                      onChanged: state.setImportant,
                    ),
                  ),
                  TextButton(onPressed: () => _skip(state), child: const Text('Skip')),
                ],
              ),
              Divider(color: c.line),
              Disclosure(
                key: ValueKey('votes-${statement.id}'),
                title: Text('What did MPs vote on?',
                    style: GlassText.body(14.5, weight: 600, color: c.accent)),
                builder: (_) => _Evidence(statement),
              ),
            ],
          ),
        ),
        _Actions(
          answered: state.answeredCount,
          onBack: state.at == 0 ? null : () => _back(state),
          onNext: state.atLast ? null : () => _next(state),
          onMatch: state.canShowMatch ? () => state.go(2) : null,
        ),
      ],
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro(this.quiz);

  final QuizData quiz;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.read(context);
    final since = quiz.termStart.length >= 4 ? quiz.termStart.substring(0, 4) : 'the election';
    return PageScroll(
      children: [
        PageHeading(
          'Where do you stand?',
          lede: '${quiz.statements.length} statements, all of them voted on by MPs since $since. '
              'The quiz covers the House of Commons.',
        ),
        Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Prose('Every statement is something MPs have **actually voted on** in this '
                  'parliament. Say how you feel about each one, and we compare your answers with '
                  'how each MP used their vote — not with what they have said.'),
              const SizedBox(height: 12),
              const Note('Your answers stay on this device. Nothing you choose is sent or stored '
                  'anywhere else. You can skip any statement and stop whenever you like; more '
                  'answers make the match more reliable.'),
              const SizedBox(height: 16),
              FilledButton(onPressed: state.start, child: const Text('Start the quiz')),
            ],
          ),
        ),
      ],
    );
  }
}

/// How far through the statements you are.
class _Progress extends StatelessWidget {
  const _Progress(this.fraction);

  final double fraction;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return ExcludeSemantics(
      child: ClipRRect(
        borderRadius: BorderRadius.circular(2),
        child: SizedBox(
          height: 4,
          child: Stack(
            fit: StackFit.expand,
            children: [
              ColoredBox(color: c.track),
              FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: fraction.clamp(0, 1).toDouble(),
                child: ColoredBox(color: c.data),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The statement itself.
class _Asked extends StatelessWidget {
  const _Asked(this.statement, {super.key});

  final Statement statement;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final length = statement.text.length;
    final size = length > 150 ? 19.0 : length > 90 ? 21.0 : 24.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('I support…', style: GlassText.body(14, color: c.muted)),
        const SizedBox(height: 4),
        Text('${statement.text}.',
            style: GlassText.display(size, weight: 500, height: 1.26, color: c.ink)),
        if (statement.freeVote) ...[
          const SizedBox(height: 12),
          const Align(
            alignment: Alignment.centerLeft,
            child: Tag('Free vote: parties did not instruct their MPs'),
          ),
        ],
      ],
    );
  }
}

class _AnswerButton extends StatelessWidget {
  const _AnswerButton({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final shape = RoundedRectangleBorder(
      side: BorderSide(color: selected ? c.accent : c.edge),
      borderRadius: BorderRadius.circular(10),
    );
    return Semantics(
      button: true,
      inMutuallyExclusiveGroup: true,
      checked: selected,
      child: Material(
        color: selected ? c.accent : c.surface,
        shape: shape,
        child: InkWell(
          onTap: onTap,
          customBorder: shape,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      label,
                      style: GlassText.body(15.5,
                          weight: 600, height: 1.25, color: selected ? c.onAccent : c.ink),
                    ),
                  ),
                  // Not colour alone: the chosen answer also carries a tick.
                  if (selected) Icon(Icons.check, size: 20, color: c.onAccent),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// "This one matters a lot to me": the statement then counts twice.
class _Important extends StatelessWidget {
  const _Important({required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return MergeSemantics(
      child: InkWell(
        onTap: () => onChanged(!value),
        borderRadius: BorderRadius.circular(8),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: Row(
            children: [
              Checkbox(value: value, onChanged: (v) => onChanged(v ?? false)),
              Flexible(
                child: Text('This one matters a lot to me',
                    style: GlassText.body(14, color: c.ink2, height: 1.3)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The votes a statement rests on.
class _Evidence extends StatelessWidget {
  const _Evidence(this.statement);

  final Statement statement;

  static final RegExp _linkText =
      RegExp(r'\s*-\s*learn more about this legislation\.?\s*$', caseSensitive: false);

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final st = statement;
    final detail = st.detail.replaceFirst(_linkText, '');
    final all = st.divisions.length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (detail.isNotEmpty && norm(detail) != norm(st.text)) ...[
          Text(detail, style: GlassText.body(14, color: c.ink2)),
          const SizedBox(height: 8),
        ],
        Text(
          '$all vote${all == 1 ? '' : 's'} in all, ${st.termVotes} in this parliament. '
          'The most recent:',
          style: GlassText.body(14, color: c.ink2),
        ),
        for (final d in st.divisions.reversed.take(3)) ...[
          const SizedBox(height: 10),
          Text(d.date, style: GlassText.mono(12, color: c.muted)),
          ExtLink(d.title, d.url, size: 14),
          Note(d.ayeSupports
              ? 'Voting aye supported the statement.'
              : 'Voting no supported the statement.'),
        ],
        if (st.link.isNotEmpty) ...[
          const SizedBox(height: 10),
          ExtLink('The legislation on Parliament\'s website', st.link, size: 14),
        ],
      ],
    );
  }
}

/// Back, forward and the way out, always within reach of a thumb.
class _Actions extends StatelessWidget {
  const _Actions({
    required this.answered,
    required this.onBack,
    required this.onNext,
    required this.onMatch,
  });

  final int answered;
  final VoidCallback? onBack, onNext, onMatch;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final left = kMinAnswers - answered;
    return DecoratedBox(
      decoration: BoxDecoration(color: c.paper, border: Border(top: BorderSide(color: c.line))),
      child: LayoutBuilder(
        builder: (context, box) {
          final side = math.max(kGutter, (box.maxWidth - kMaxContentWidth) / 2);
          return Padding(
            padding: EdgeInsets.fromLTRB(side, 10, side, 8),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    IconButton.outlined(
                      onPressed: onBack,
                      icon: const Icon(Icons.arrow_back),
                      tooltip: 'Previous statement',
                      constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: FilledButton(onPressed: onMatch, child: const Text('See my match')),
                    ),
                    const SizedBox(width: 8),
                    IconButton.outlined(
                      onPressed: onNext,
                      icon: const Icon(Icons.arrow_forward),
                      tooltip: 'Next statement',
                      constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  left > 0
                      ? 'Answer $left more to see a match.'
                      : '$answered answered. Keep going for a more reliable match.',
                  textAlign: TextAlign.center,
                  style: GlassText.body(12.5, color: c.muted, height: 1.3),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
