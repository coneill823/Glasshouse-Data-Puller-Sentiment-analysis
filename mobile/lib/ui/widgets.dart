/// Small pieces shared by every screen.
library;

import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';

const double kGutter = 16;

/// Lines of text much longer than this are hard to read, so on a tablet the
/// column stops growing and the margins take the rest.
const double kMaxContentWidth = 720;

bool reducedMotion(BuildContext context) => MediaQuery.disableAnimationsOf(context);

/// Opens a web page in the phone's browser.
Future<void> openLink(BuildContext context, String url) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  var opened = false;
  try {
    opened = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  } on Object {
    opened = false;
  }
  if (!opened) {
    messenger?.showSnackBar(const SnackBar(content: Text('That link could not be opened.')));
  }
}

/// One scrolling column with a gutter either side.
class PageScroll extends StatelessWidget {
  const PageScroll({super.key, required this.children, this.controller});

  final List<Widget> children;
  final ScrollController? controller;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, box) {
          final side = math.max(kGutter, (box.maxWidth - kMaxContentWidth) / 2);
          return SingleChildScrollView(
            controller: controller,
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: EdgeInsets.fromLTRB(side, 8, side, 32),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
          );
        },
      );
}

/// The heading and introduction at the top of a screen.
class PageHeading extends StatelessWidget {
  const PageHeading(this.title, {super.key, this.lede});

  final String title;
  final String? lede;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text(title, style: GlassText.display(27, color: c.ink)),
        ),
        if (lede != null) ...[
          const SizedBox(height: 8),
          Text(lede!, style: GlassText.body(15, color: c.ink2)),
        ],
        const SizedBox(height: 16),
      ],
    );
  }
}

/// A small capitalised label above a group of things.
class Eyebrow extends StatelessWidget {
  const Eyebrow(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Text(
        text.toUpperCase(),
        semanticsLabel: text,
        style: GlassText.eyebrow(context.glass.muted),
      );
}

/// A surface that holds one self-contained thing.
class Panel extends StatelessWidget {
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(16)});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border.all(color: c.line),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Padding(padding: padding, child: child),
    );
  }
}

/// A short label that classifies something: a role, a subject.
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return DecoratedBox(
      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(6)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        child: Text(text, style: GlassText.mono(11, weight: 500, color: c.ink2)),
      ),
    );
  }
}

/// Explanation in a quieter voice.
class Note extends StatelessWidget {
  const Note(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: GlassText.body(13, color: context.glass.muted));
}

/// Running text in which `**this**` is bold.
class Prose extends StatelessWidget {
  const Prose(this.source, {super.key, this.size = 15, this.color});

  final String source;
  final double size;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final parts = source.split('**');
    return Text.rich(
      TextSpan(
        children: [
          for (var i = 0; i < parts.length; i++)
            TextSpan(
              text: parts[i],
              style: i.isOdd ? GlassText.body(size, weight: 650, color: c.ink) : null,
            ),
        ],
      ),
      style: GlassText.body(size, color: color ?? c.ink2),
    );
  }
}

/// A link that leaves the app.
class ExtLink extends StatelessWidget {
  const ExtLink(this.label, this.url, {super.key, this.size = 15});

  final String label;
  final String url;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Semantics(
      link: true,
      child: InkWell(
        onTap: () => openLink(context, url),
        borderRadius: BorderRadius.circular(6),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Text.rich(
            TextSpan(
              children: [
                TextSpan(text: label),
                WidgetSpan(
                  alignment: PlaceholderAlignment.middle,
                  child: Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: Icon(Icons.open_in_new, size: size - 1, color: c.accent),
                  ),
                ),
              ],
            ),
            style: GlassText.body(size, weight: 500, color: c.accent).copyWith(
              decoration: TextDecoration.underline,
              decorationColor: c.accent.withValues(alpha: 0.45),
            ),
          ),
        ),
      ),
    );
  }
}

/// Three figures side by side, separated by hairlines.
class StatRow extends StatelessWidget {
  const StatRow(this.items, {super.key});

  /// Each figure and what it counts.
  final List<(String, String)> items;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < items.length; i++) ...[
            if (i > 0)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10),
                child: VerticalDivider(width: 1, thickness: 1, color: c.line),
              ),
            Expanded(
              child: MergeSemantics(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      items[i].$1,
                      style: GlassText.display(22, color: c.ink, height: 1.1),
                    ),
                    const SizedBox(height: 3),
                    Text(items[i].$2, style: GlassText.body(12, color: c.muted, height: 1.3)),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// One horizontal bar: a value out of 100, with an optional reference tick.
///
/// The label and figure sit above the bar rather than beside it, so the bar
/// keeps its full width on a narrow phone and nothing is squeezed when the
/// reader has made their text larger.
class MetricBar extends StatelessWidget {
  const MetricBar({
    super.key,
    required this.label,
    required this.value,
    this.median,
    this.valueText,
    this.fill,
    this.semantics,
  });

  final String label;

  /// 0–100, or null when there is nothing to show.
  final double? value;

  /// Where the typical member sits, drawn as a tick.
  final double? median;

  /// Printed figure, if not simply the value as a percentage.
  final String? valueText;

  /// How much of the bar to fill, if not the value itself.
  final double? fill;

  /// What a screen reader should say instead of the visible text.
  final String? semantics;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final figure = valueText ?? (value == null ? '—' : '${value!.toStringAsFixed(1)}%');
    return Semantics(
      label: semantics ?? '$label: ${value == null && valueText == null ? 'no figure' : figure}',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(child: Text(label, style: GlassText.body(13, color: c.ink2, height: 1.3))),
              const SizedBox(width: 12),
              Text(figure, style: GlassText.mono(13, weight: 500, color: c.ink)),
            ],
          ),
          const SizedBox(height: 4),
          SizedBox(
            height: 14,
            child: CustomPaint(
              painter: _BarPainter(
                fill: fill ?? value,
                median: median,
                data: c.data,
                track: c.track,
                tick: c.ink2,
                halo: c.surface,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _BarPainter extends CustomPainter {
  const _BarPainter({
    required this.fill,
    required this.median,
    required this.data,
    required this.track,
    required this.tick,
    required this.halo,
  });

  final double? fill, median;
  final Color data, track, tick, halo;

  @override
  void paint(Canvas canvas, Size size) {
    const barHeight = 8.0;
    final top = (size.height - barHeight) / 2;
    final bar = RRect.fromRectAndRadius(
      Rect.fromLTWH(0, top, size.width, barHeight),
      const Radius.circular(3),
    );
    canvas.drawRRect(bar, Paint()..color = track);
    final f = fill;
    if (f != null && f > 0) {
      // The filled end is square: it marks an exact value.
      canvas.save();
      canvas.clipRRect(bar);
      canvas.drawRect(
        Rect.fromLTWH(0, top, size.width * f.clamp(0, 100) / 100, barHeight),
        Paint()..color = data,
      );
      canvas.restore();
    }
    final m = median;
    if (m != null) {
      // Taller than the bar and outlined, so it reads over fill and track alike.
      final x = (size.width * m.clamp(0, 100) / 100).clamp(1.0, size.width - 1.0);
      canvas.drawRect(Rect.fromLTWH(x - 2, 0, 4, size.height), Paint()..color = halo);
      canvas.drawRect(Rect.fromLTWH(x - 1, 0, 2, size.height), Paint()..color = tick);
    }
  }

  @override
  bool shouldRepaint(_BarPainter old) =>
      old.fill != fill ||
      old.median != median ||
      old.data != data ||
      old.track != track ||
      old.tick != tick ||
      old.halo != halo;
}

/// The key to the reference tick on a [MetricBar].
class MedianKey extends StatelessWidget {
  const MedianKey({super.key, this.text = 'chamber median'});

  final String text;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Row(
      children: [
        Container(width: 2, height: 12, color: c.ink2),
        const SizedBox(width: 6),
        Flexible(child: Text(text, style: GlassText.body(12, color: c.muted))),
      ],
    );
  }
}

/// How far the ends of an [AxisBar] sit in from its edges, so a marker at
/// either extreme is not cut off.
const double kAxisInset = 9;

/// A position between "always against" and "always for": a filled dot for how
/// an MP voted and a hollow diamond for the visitor's own answer.
class AxisBar extends StatelessWidget {
  const AxisBar({super.key, this.them, this.you});

  /// -1 … +1, or null for no marker.
  final double? them, you;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return SizedBox(
      height: 22,
      child: CustomPaint(
        painter: _AxisPainter(
          them: them,
          you: you,
          data: c.data,
          track: c.track,
          mid: c.edge,
          join: c.muted,
          ink: c.ink,
          surface: c.surface,
        ),
      ),
    );
  }
}

class _AxisPainter extends CustomPainter {
  const _AxisPainter({
    required this.them,
    required this.you,
    required this.data,
    required this.track,
    required this.mid,
    required this.join,
    required this.ink,
    required this.surface,
  });

  final double? them, you;
  final Color data, track, mid, join, ink, surface;

  @override
  void paint(Canvas canvas, Size size) {
    final y = size.height / 2;
    final span = size.width - 2 * kAxisInset;
    double x(double v) => kAxisInset + (v.clamp(-1, 1) + 1) / 2 * span;

    canvas.drawLine(
      Offset(kAxisInset, y),
      Offset(size.width - kAxisInset, y),
      Paint()
        ..color = track
        ..strokeWidth = 3
        ..strokeCap = StrokeCap.round,
    );
    canvas.drawLine(
      Offset(size.width / 2, y - 6),
      Offset(size.width / 2, y + 6),
      Paint()
        ..color = mid
        ..strokeWidth = 1,
    );
    final t = them, u = you;
    if (t != null && u != null) {
      canvas.drawLine(
        Offset(x(t), y),
        Offset(x(u), y),
        Paint()
          ..color = join
          ..strokeWidth = 3,
      );
    }
    if (u != null) {
      const r = 8.0;
      final cx = x(u);
      final diamond = Path()
        ..moveTo(cx, y - r)
        ..lineTo(cx + r, y)
        ..lineTo(cx, y + r)
        ..lineTo(cx - r, y)
        ..close();
      canvas.drawPath(diamond, Paint()..color = surface);
      canvas.drawPath(
        diamond,
        Paint()
          ..color = ink
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..strokeJoin = StrokeJoin.round,
      );
    }
    if (t != null) {
      // Small enough to sit inside the diamond when the two coincide.
      final centre = Offset(x(t), y);
      final overlaps = u != null && (x(t) - x(u)).abs() < 10;
      if (!overlaps) canvas.drawCircle(centre, 6, Paint()..color = surface);
      canvas.drawCircle(centre, overlaps ? 3.6 : 4.6, Paint()..color = data);
    }
  }

  @override
  bool shouldRepaint(_AxisPainter old) =>
      old.them != them ||
      old.you != you ||
      old.data != data ||
      old.track != track ||
      old.mid != mid ||
      old.join != join ||
      old.ink != ink ||
      old.surface != surface;
}

/// "Against … For" above a column of [AxisBar]s.
class AxisEnds extends StatelessWidget {
  const AxisEnds({super.key});

  @override
  Widget build(BuildContext context) {
    final style = GlassText.mono(10.5, weight: 500, color: context.glass.muted);
    return ExcludeSemantics(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kAxisInset - 6),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [Text('AGAINST', style: style), Text('FOR', style: style)],
        ),
      ),
    );
  }
}

/// A shape and a name: one entry in a chart's key.
class KeyItem extends StatelessWidget {
  const KeyItem({super.key, required this.mark, required this.text});

  final KeyMark mark;
  final String text;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 16,
          height: 16,
          child: CustomPaint(
            painter: _KeyPainter(mark, data: c.data, ink: c.ink, surface: c.surface, dot: c.dot),
          ),
        ),
        const SizedBox(width: 6),
        Flexible(child: Text(text, style: GlassText.body(12.5, color: c.ink2, height: 1.3))),
      ],
    );
  }
}

enum KeyMark { you, them, others }

class _KeyPainter extends CustomPainter {
  const _KeyPainter(this.mark,
      {required this.data, required this.ink, required this.surface, required this.dot});

  final KeyMark mark;
  final Color data, ink, surface, dot;

  @override
  void paint(Canvas canvas, Size size) {
    final centre = size.center(Offset.zero);
    switch (mark) {
      case KeyMark.you:
        const r = 6.5;
        final diamond = Path()
          ..moveTo(centre.dx, centre.dy - r)
          ..lineTo(centre.dx + r, centre.dy)
          ..lineTo(centre.dx, centre.dy + r)
          ..lineTo(centre.dx - r, centre.dy)
          ..close();
        canvas.drawPath(diamond, Paint()..color = surface);
        canvas.drawPath(
          diamond,
          Paint()
            ..color = ink
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2
            ..strokeJoin = StrokeJoin.round,
        );
      case KeyMark.them:
        canvas.drawCircle(centre, 5, Paint()..color = data);
      case KeyMark.others:
        canvas.drawCircle(centre, 3, Paint()..color = dot);
    }
  }

  @override
  bool shouldRepaint(_KeyPainter old) =>
      old.mark != mark || old.data != data || old.ink != ink || old.surface != surface || old.dot != dot;
}

/// A heading that opens to show more.
class Disclosure extends StatefulWidget {
  const Disclosure({
    super.key,
    required this.title,
    required this.builder,
    this.initiallyOpen = false,
  });

  final Widget title;

  /// Built only once opened: some of these hold long lists.
  final WidgetBuilder builder;
  final bool initiallyOpen;

  @override
  State<Disclosure> createState() => _DisclosureState();
}

class _DisclosureState extends State<Disclosure> {
  late bool _open = widget.initiallyOpen;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final still = reducedMotion(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          button: true,
          expanded: _open,
          child: InkWell(
            onTap: () => setState(() => _open = !_open),
            borderRadius: BorderRadius.circular(8),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 48),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Row(
                  children: [
                    Expanded(child: widget.title),
                    const SizedBox(width: 8),
                    AnimatedRotation(
                      turns: _open ? 0.5 : 0,
                      duration: still ? Duration.zero : const Duration(milliseconds: 160),
                      child: Icon(Icons.expand_more, color: c.muted, size: 22),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        AnimatedSize(
          duration: still ? Duration.zero : const Duration(milliseconds: 180),
          curve: Curves.easeOut,
          alignment: Alignment.topCenter,
          child: _open
              ? Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: widget.builder(context),
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

/// A sub-heading inside a card or a detail page.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Semantics(
        header: true,
        child: Text(text, style: GlassText.body(14, weight: 650, color: context.glass.ink)),
      );
}
