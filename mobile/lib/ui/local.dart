/// What is local to a place besides its parliaments: the elections coming
/// up there, and (where a council's own records could be read) its
/// councillors.
library;

import 'package:material_ui/material_ui.dart';

import '../core/models.dart';
import '../core/place.dart';
import '../theme.dart';
import 'member.dart';
import 'scope.dart';
import 'widgets.dart';

const List<String> _months = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const List<String> _days = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
];

/// "2026-11-26" -> "26 November 2026", with the day of the week if asked.
String longDate(String iso, {bool weekday = false}) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final date = '${d.day} ${_months[d.month - 1]} ${d.year}';
  return weekday ? '${_days[d.weekday - 1]} $date' : date;
}

/// "Council by-election".
String ballotKind(Ballot b) => '${b.kind} ${b.byElection ? 'by-election' : 'election'}';

/// Where a ballot is for: "Shard End, Birmingham".
String ballotWhere(Ballot b) =>
    b.area.isEmpty || b.area == b.body ? b.body : '${b.area}${b.body.isEmpty ? '' : ', ${b.body}'}';

/// The elections coming up for a place, and who is standing.
class ElectionsHere extends StatelessWidget {
  const ElectionsHere(this.place, {super.key});

  final Place place;

  @override
  Widget build(BuildContext context) {
    final data = AppScope.of(context).data;
    final ballots = data.ballotsFor(place.codes);
    final checked = data.electionsAsOf.isEmpty ? '' : ' (checked ${longDate(data.electionsAsOf)})';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Elections coming up here'),
        const SizedBox(height: 8),
        if (ballots.isEmpty)
          Note(place.isPostcode
              ? 'None is scheduled for this postcode in Democracy Club\'s register$checked.'
              : 'None is scheduled for this constituency$checked. Search by postcode to '
                  'see elections for your council ward as well.')
        else ...[
          for (final (i, b) in ballots.indexed) ...[
            if (i > 0) const SizedBox(height: 10),
            BallotCard(b),
          ],
        ],
      ],
    );
  }
}

/// One ballot paper: when, what for, and who is on it.
class BallotCard extends StatelessWidget {
  const BallotCard(this.ballot, {super.key, this.highlight});

  final Ballot ballot;

  /// A candidate to pick out, when the visitor searched for them by name.
  final String? highlight;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final data = AppScope.of(context).data;
    final b = ballot;
    final n = b.candidates.length;
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 10,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Eyebrow(longDate(b.date, weekday: true)),
              if (b.cancelled) const Tag('Cancelled'),
            ],
          ),
          const SizedBox(height: 4),
          Text(ballotWhere(b), style: GlassText.display(20, color: c.ink)),
          const SizedBox(height: 2),
          Text(
            '${ballotKind(b)} · ${b.seats} seat${b.seats == 1 ? '' : 's'} · '
            '${n == 0 ? 'no candidates announced yet' : '$n standing so far'}',
            style: GlassText.body(13.5, color: c.ink2),
          ),
          for (final person in b.candidates) ...[
            const SizedBox(height: 8),
            Divider(color: c.line),
            const SizedBox(height: 8),
            _CandidateRow(
              person,
              record: person.record == null ? null : data.recordsOf(person.record!).firstOrNull,
              picked: highlight != null && person.name == highlight,
            ),
          ],
          const SizedBox(height: 12),
          const Note('Nobody here is scored for standing: a candidate has done nothing in '
              'office yet. Anyone who has held a seat before links to that record.'),
          const SizedBox(height: 4),
          if (b.url.isNotEmpty) ExtLink('This election on WhoCanIVoteFor', b.url, size: 14),
        ],
      ),
    );
  }
}

class _CandidateRow extends StatelessWidget {
  const _CandidateRow(this.candidate, {required this.record, required this.picked});

  final Candidate candidate;
  final Member? record;
  final bool picked;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final name = Text(candidate.name,
        style: GlassText.body(15,
            weight: picked ? 700 : 600, color: record == null ? c.ink : c.accent, height: 1.3));
    final row = Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              name,
              Text(
                record == null
                    ? '${candidate.party} · no record in office'
                    : '${candidate.party} · has a record: see it',
                style: GlassText.body(12.5, color: c.muted, height: 1.35),
              ),
            ],
          ),
        ),
        if (record != null) Icon(Icons.chevron_right, size: 20, color: c.accent),
      ],
    );
    if (record == null) return row;
    return InkWell(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => MemberPage(record!)),
      ),
      child: ConstrainedBox(constraints: const BoxConstraints(minHeight: 44), child: row),
    );
  }
}

/// A ballot on a screen of its own, reached by searching for a candidate.
class BallotPage extends StatelessWidget {
  const BallotPage(this.ballot, {super.key, this.highlight});

  final Ballot ballot;
  final String? highlight;

  @override
  Widget build(BuildContext context) {
    final data = AppScope.of(context).data;
    return Scaffold(
      appBar: AppBar(title: Text(ballotKind(ballot), overflow: TextOverflow.ellipsis)),
      body: SafeArea(
        top: false,
        child: PageScroll(
          children: [
            BallotCard(ballot, highlight: highlight),
            const SizedBox(height: 12),
            Note('Candidates as announced so far, from Democracy Club\'s register'
                '${data.electionsAsOf.isEmpty ? '' : ', ${longDate(data.electionsAsOf)}'} '
                '(CC BY 4.0). Close to polling day the list is complete; earlier, it holds '
                'only those who have declared.'),
          ],
        ),
      ),
    );
  }
}

/// The councillors for a postcode's ward, where its council has been read.
class CouncillorsHere extends StatelessWidget {
  const CouncillorsHere(this.place, {super.key});

  final Place place;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final data = AppScope.of(context).data;
    if (data.councils.isEmpty) return const SizedBox.shrink();
    final found = data.councilFor(place.district, place.ward);
    final read = [for (final b in data.councils) b.name.replaceFirst(RegExp(r' (City )?Council$'), '')];

    if (found == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SectionTitle('Your councillors'),
          const SizedBox(height: 8),
          Note('Not here yet. Councils each publish their own records, and so far only '
              '${read.join(' and ')} ${read.length == 1 ? 'has' : 'have'} been read, as a trial. '
              '${place.isPostcode ? '' : 'Search by postcode to find your ward. '}'
              'Almost no council records how each councillor voted.'),
        ],
      );
    }

    final body = found.body;
    final ward = found.ward;
    final period = data.councilPeriod;
    final within = ward.covers.length > 1 && place.ward.isNotEmpty && place.ward != ward.name;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Your councillors'),
        const SizedBox(height: 8),
        Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Eyebrow(body.name),
              const SizedBox(height: 4),
              Text(ward.name, style: GlassText.display(20, color: c.ink)),
              if (within) ...[
                const SizedBox(height: 2),
                Text('The electoral area that ${place.ward} ward is part of.',
                    style: GlassText.body(13.5, color: c.ink2)),
              ],
              for (final person in ward.councillors) ...[
                const SizedBox(height: 14),
                _CouncillorRow(person, showAttendance: body.hasAttendance),
              ],
              const SizedBox(height: 14),
              Note(body.hasAttendance
                  ? 'The bar is how many of the meetings they were expected at they attended'
                      '${period.from.isEmpty ? '' : ', ${longDate(period.from)} to ${longDate(period.to)}'}, '
                      'from the council\'s own records. It counts only the committees they '
                      'sit on, and absence is not always a choice.'
                  : '${body.name} does not publish attendance in a form that could be read, '
                      'so only names and parties are shown.'),
              const SizedBox(height: 6),
              const Note('There is no match with your answers. Councils record most votes '
                  'only as carried or lost, not who voted which way, so there is nothing '
                  'to compare.'),
            ],
          ),
        ),
      ],
    );
  }
}

class _CouncillorRow extends StatelessWidget {
  const _CouncillorRow(this.person, {required this.showAttendance});

  final Councillor person;
  final bool showAttendance;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final attendance = person.attendance;
    return InkWell(
      onTap: person.url.isEmpty ? null : () => openLink(context, person.url),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: person.name,
                        style: GlassText.body(15, weight: 600, color: c.accent, height: 1.3),
                      ),
                      TextSpan(text: ' · ${person.party}'),
                    ],
                  ),
                  style: GlassText.body(13.5, color: c.ink2, height: 1.3),
                ),
              ),
              if (person.url.isNotEmpty) ...[
                const SizedBox(width: 6),
                Icon(Icons.open_in_new, size: 15, color: c.muted),
              ],
            ],
          ),
          if (showAttendance) ...[
            const SizedBox(height: 4),
            MetricBar(
              // The figure stays short: it shares a line with its label.
              label: attendance == null ? 'Attendance not recorded' : 'Meetings attended',
              value: attendance,
              valueText: attendance == null ? '—' : '${person.present} of ${person.expected}',
              semantics: attendance == null
                  ? '${person.name}: attendance not recorded'
                  : '${person.name} attended ${person.present} of the ${person.expected} '
                      'meetings they were expected at',
            ),
          ],
        ],
      ),
    );
  }
}
