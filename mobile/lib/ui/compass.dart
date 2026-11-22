/// Where each MP's votes sit on two axes, and where your answers put you.
///
/// Across is economic, left to right. Up is social: liberal at the bottom,
/// authoritarian at the top. Everyone is placed by the same function, from
/// the same tagged statements.
library;

import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../core/scoring.dart';
import '../theme.dart';

/// An MP is only drawn once their position rests on this many tagged
/// statements on each axis.
const double kMinEconVotes = 4, kMinSocialVotes = 3;

/// And the visitor once they have answered this many on each.
const double kMinAxisAnswers = 3;

bool isPlacedVisitor(CompassPoint p) =>
    p.placed && p.econWeight >= kMinAxisAnswers && p.socialWeight >= kMinAxisAnswers;

bool _isDrawn(CompassPoint p) =>
    p.placed && p.econWeight >= kMinEconVotes && p.socialWeight >= kMinSocialVotes;

/// In words, for anyone who cannot see the chart.
String describePosition(CompassPoint p) {
  String along(double v, String low, String high) =>
      v.abs() < 0.1 ? 'in the centre' : v < 0 ? low : high;
  return '${along(p.econ!, 'left of centre', 'right of centre')} economically and '
      '${along(p.social!, 'on the liberal side', 'on the authoritarian side')} socially';
}

/// The square the points are plotted in, inside the space for its labels.
class _Frame {
  _Frame(Size size)
      : side = math.max(0, math.min(size.width - 2 * padX, size.height - padTop - padBottom)),
        left = padX,
        top = padTop;

  static const double padX = 9, padTop = 22, padBottom = 24;

  /// Kept clear inside the border, so a dot at either extreme is not drawn on it.
  static const double margin = 9;

  final double side, left, top;

  double x(double econ) => left + margin + (econ + 1) / 2 * (side - 2 * margin);
  double y(double social) => top + margin + (1 - (social + 1) / 2) * (side - 2 * margin);
  Rect get rect => Rect.fromLTWH(left, top, side, side);
}

class _Dot {
  const _Dot(this.member, this.point, this.at);
  final QuizMember member;
  final CompassPoint point;
  final Offset at;
}

class Compass extends StatelessWidget {
  const Compass({
    super.key,
    required this.state,
    required this.onPick,
    this.focus,
    this.picked,
  });

  final AppState state;

  /// The MP the screen is about.
  final QuizMember? focus;

  /// An MP the visitor has tapped, to find out who they are.
  final int? picked;
  final ValueChanged<int?> onPick;

  /// Many MPs have identical records and would sit on one point. A small fixed
  /// nudge per member lets the crowd show without moving anyone far.
  static Offset _nudge(int id) => Offset(
        ((id * 9301 + 49297) % 233280) / 233280 - 0.5,
        ((id * 4099 + 7919) % 104729) / 104729 - 0.5,
      ) * 6;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final quiz = state.quiz!;
    final you = state.ownCompass;
    final focusPoint = focus == null ? null : state.compass[focus!.id];

    final said = StringBuffer('Compass of how MPs voted. Across is economic, left to right. '
        'Up is social, from liberal at the bottom to authoritarian at the top.');
    if (isPlacedVisitor(you)) said.write(' Your answers put you ${describePosition(you)}.');
    if (focusPoint != null && focusPoint.placed) {
      said.write(' ${focus!.name}\'s votes sit ${describePosition(focusPoint)}.');
    }

    return LayoutBuilder(
      builder: (context, box) {
        final width = math.min(box.maxWidth, 440.0);
        final size = Size(width, width - 2 * _Frame.padX + _Frame.padTop + _Frame.padBottom);
        final frame = _Frame(size);
        final dots = <_Dot>[
          for (final m in quiz.members)
            if (state.compass[m.id] case final p? when _isDrawn(p))
              _Dot(m, p, Offset(frame.x(p.econ!), frame.y(p.social!)) + _nudge(m.id)),
        ];

        int? nearest(Offset tap) {
          // A fingertip is a blunt instrument: take the closest dot within reach.
          const reach = 22.0;
          _Dot? best;
          var bestDistance = reach * reach;
          for (final d in dots) {
            final distance = (d.at - tap).distanceSquared;
            if (distance < bestDistance) {
              best = d;
              bestDistance = distance;
            }
          }
          return best?.member.id;
        }

        return Center(
          child: Semantics(
            image: true,
            label: said.toString(),
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapUp: (details) => onPick(nearest(details.localPosition)),
              child: CustomPaint(
                size: size,
                painter: _CompassPainter(
                  frame: frame,
                  dots: dots,
                  you: isPlacedVisitor(you) ? Offset(frame.x(you.econ!), frame.y(you.social!)) : null,
                  focus: focusPoint != null && focusPoint.placed
                      ? Offset(frame.x(focusPoint.econ!), frame.y(focusPoint.social!))
                      : null,
                  picked: picked,
                  colors: c,
                  textScaler: MediaQuery.textScalerOf(context).clamp(maxScaleFactor: 1.3),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _CompassPainter extends CustomPainter {
  const _CompassPainter({
    required this.frame,
    required this.dots,
    required this.you,
    required this.focus,
    required this.picked,
    required this.colors,
    required this.textScaler,
  });

  final _Frame frame;
  final List<_Dot> dots;
  final Offset? you, focus;
  final int? picked;
  final GlassColors colors;
  final TextScaler textScaler;

  TextPainter _text(String text, TextStyle style) => TextPainter(
        text: TextSpan(text: text, style: style),
        textDirection: TextDirection.ltr,
        textScaler: textScaler,
      )..layout();

  @override
  void paint(Canvas canvas, Size size) {
    final c = colors;
    final r = frame.rect;

    // --- the field ---
    canvas.drawRect(r, Paint()..color = c.surface);
    final rule = Paint()
      ..color = c.line
      ..strokeWidth = 1;
    canvas.drawLine(Offset(r.left, r.center.dy), Offset(r.right, r.center.dy), rule);
    canvas.drawLine(Offset(r.center.dx, r.top), Offset(r.center.dx, r.bottom), rule);
    canvas.drawRect(
      r,
      Paint()
        ..color = c.edge
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1,
    );

    // --- what the directions mean ---
    final axis = GlassText.mono(10.5, weight: 500, color: c.muted).copyWith(letterSpacing: 0.6);
    final up = _text('AUTHORITARIAN', axis);
    up.paint(canvas, Offset(r.center.dx - up.width / 2, r.top - up.height - 5));
    final down = _text('LIBERAL', axis);
    down.paint(canvas, Offset(r.center.dx - down.width / 2, r.bottom + 6));
    _text('← LEFT', axis).paint(canvas, Offset(r.left, r.bottom + 6));
    final right = _text('RIGHT →', axis);
    right.paint(canvas, Offset(r.right - right.width, r.bottom + 6));

    // --- every MP ---
    final crowd = Paint()..color = c.dot.withValues(alpha: 0.6);
    final sums = <String, ({double e, double s, int n})>{};
    _Dot? chosen;
    for (final d in dots) {
      if (d.member.id == picked) chosen = d;
      canvas.drawCircle(d.at, 2.3, crowd);
      final party = partyLabel(d.member.party);
      final sum = sums[party] ?? (e: 0.0, s: 0.0, n: 0);
      sums[party] = (e: sum.e + d.point.econ!, s: sum.s + d.point.social!, n: sum.n + 1);
    }

    // --- party names at each party's average ---
    // Largest first, each moved to the nearest spot that does not sit on a
    // name already placed, on you, or on the MP in focus.
    final taken = <Rect>[
      if (you != null) Rect.fromCircle(center: you!, radius: 10),
      if (focus != null) Rect.fromCircle(center: focus!, radius: 9),
    ];
    final parties = sums.keys.where((p) => isParty(p) && sums[p]!.n >= 4).toList()
      ..sort((a, b) => sums[b]!.n.compareTo(sums[a]!.n));
    final nameStyle = GlassText.body(11, weight: 650, height: 1.15, color: c.ink2);
    final halo = nameStyle.copyWith(
      foreground: Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..strokeJoin = StrokeJoin.round
        ..color = c.surface,
    );
    for (final party in parties) {
      final sum = sums[party]!;
      final name = kShortParty[party] ?? party;
      final label = _text(name, nameStyle);
      final w = label.width + 6, h = label.height + 2;
      final cx = frame.x(sum.e / sum.n), cy = frame.y(sum.s / sum.n);
      final offsets = <Offset>[
        Offset(0, -h * 0.5 - 6), Offset(0, h * 0.5 + 6),
        Offset(w / 2 + 6, 0), Offset(-w / 2 - 6, 0),
        Offset(0, -h * 1.5 - 8), Offset(0, h * 1.5 + 8),
        Offset(w / 2 + 6, -h), Offset(-w / 2 - 6, -h),
        Offset(w / 2 + 6, h), Offset(-w / 2 - 6, h),
      ];
      for (final offset in offsets) {
        final centre = Offset(
          (cx + offset.dx).clamp(r.left + w / 2, math.max(r.left + w / 2, r.right - w / 2)),
          (cy + offset.dy).clamp(r.top + h / 2, math.max(r.top + h / 2, r.bottom - h / 2)),
        );
        final box = Rect.fromCenter(center: centre, width: w, height: h);
        if (taken.any(box.overlaps)) continue; // no room here: try the next spot
        taken.add(box);
        final at = Offset(centre.dx - label.width / 2, centre.dy - label.height / 2);
        _text(name, halo).paint(canvas, at);
        label.paint(canvas, at);
        break; // and if nowhere is free, better no name than a collision
      }
    }

    // --- the one you tapped ---
    if (chosen != null) {
      canvas.drawCircle(chosen.at, 6.5, Paint()..color = c.surface);
      canvas.drawCircle(chosen.at, 3.2, Paint()..color = c.ink);
      canvas.drawCircle(
        chosen.at,
        6.5,
        Paint()
          ..color = c.ink
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
    }

    // --- the MP in focus, then you ---
    // If the two land on the same spot the dot shrinks to sit inside the
    // diamond, so both can still be seen.
    final together = you != null && focus != null && (focus! - you!).distance < 10;
    if (focus != null) {
      if (!together) canvas.drawCircle(focus!, 7.5, Paint()..color = c.surface);
      canvas.drawCircle(focus!, together ? 3.6 : 5.8, Paint()..color = c.data);
    }
    if (you != null) {
      const d = 8.0;
      final diamond = Path()
        ..moveTo(you!.dx, you!.dy - d)
        ..lineTo(you!.dx + d, you!.dy)
        ..lineTo(you!.dx, you!.dy + d)
        ..lineTo(you!.dx - d, you!.dy)
        ..close();
      if (!together) canvas.drawPath(diamond, Paint()..color = c.surface);
      canvas.drawPath(
        diamond,
        Paint()
          ..color = c.ink
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.2
          ..strokeJoin = StrokeJoin.round,
      );
    }
  }

  @override
  bool shouldRepaint(_CompassPainter old) => true;
}
