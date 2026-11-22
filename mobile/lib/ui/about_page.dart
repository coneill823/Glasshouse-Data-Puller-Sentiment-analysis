/// How the figures are made, what they cannot tell you, and where they come from.
library;

import 'package:material_ui/material_ui.dart';

import '../theme.dart';
import 'scope.dart';
import 'widgets.dart';

class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final quiz = state.quiz;
    final statements = quiz?.statements.length ?? 0;
    final untagged = quiz?.statements.where((s) => s.econ == 0 && s.social == 0).length ?? 0;
    final votesAsOf = state.data.sources.votesAsOf;
    final speechAsOf = state.data.sources.speechAsOf;

    return PageScroll(
      children: [
        const PageHeading('How this works, and what it cannot tell you'),

        const _Heading('Actions, not words', first: true),
        const _Para('Everything here is built from what representatives did, weighted by how '
            'directly the act changes anything:'),
        const _Bullet('**Votes that use the powers of Parliament** — passing a stage of a bill, '
            'amending it, approving an order — decide your match. These are the only votes the '
            'quiz counts.'),
        const _Bullet('**Motions that only express a view** (“this House regrets…”) are left out '
            'of the match, however heated the debate.'),
        const _Bullet('**Motions signed** are shown as activity. Signing one is entirely the '
            'member\'s own choice, but it changes no law, so it never feeds a score.'),
        const _Bullet('**Questions and speeches** tell you what a member spends time on, never '
            'which side they are on. Words are too easy to misread, so they are counted and not '
            'interpreted.'),

        const _Heading('Whose judgement is in the quiz'),
        _Para('Deciding that a vote was “for” or “against” something is a judgement, and it is '
            'not ours. The $statements statements, the votes behind each one and which way each '
            'vote counts are the published policy groupings of TheyWorkForYou, run by the '
            'non-partisan charity mySociety. Every score in this app can be traced to the named '
            'divisions behind it — open any statement in your results to see them.'),
        const ExtLink('TheyWorkForYou\'s policy groupings', 'https://votes.theyworkforyou.com/policies'),
        const SizedBox(height: 6),
        const _Para('A member\'s position on a statement is simply their votes on it: votes for, '
            'minus votes against, over the votes they cast. Absences count for nothing either '
            'way, and decisions made without a recorded vote are excluded, because nobody '
            'individually did anything. Where the same policy was voted on in earlier '
            'parliaments those votes count too, so a long-serving MP\'s position rests on more '
            'votes than a new one\'s; each match shows how many.'),

        const _Heading('What a vote does and does not mean'),
        const _Para('A vote is not an opinion. Most votes are whipped: the typical member votes '
            'with their party about 99% of the time, so on most statements your MP\'s record is '
            'their party\'s. And MPs vote against things for different reasons — an opposition '
            'MP may oppose a bill because it goes too far, or not far enough. What the record '
            'does show, without interpretation, is how each MP used the power you gave them.'),
        const _Para('Because the statements must have been voted on in this parliament, they '
            'mostly follow the government\'s programme. Subjects Parliament has not voted on '
            'are not here.'),

        const _Heading('The compass'),
        _Para('The compass is the one interpretive layer we add. Each statement that sits '
            'clearly on an economic (left–right) or social (liberal–authoritarian) axis is '
            'tagged with one; $untagged that do not are left untagged. You and every MP are '
            'placed with the same tags, so any mistake in them moves everyone identically. As a '
            'check, the tags were compared with the structure of the voting record itself: with '
            'no tagging at all, the leading pattern in MPs\' positions lines up with our '
            'economic axis (correlation 0.98) and the second with our social axis (0.76). It '
            'shows where votes sit, not what anyone believes.'),

        const _Heading('The record'),
        const _Para('**Turnout** is the share of divisions a member voted in this term, out of '
            'those they were eligible for. Missing a vote is not always a choice: ministers are '
            'often excused, members are “paired” with an opponent so both can be absent, and '
            'illness or parental leave leaves a gap.'),
        const _Para('**Broke with party** counts divisions where a member did something '
            'different from most of their party at the time — each one is listed.'),
        const _Para('**What they work on** counts which subjects their questions and speeches '
            'mention, sorted with keyword lists; that is categorisation rather than opinion, '
            'but it is the one place a list we wrote touches these numbers.'),

        const _Heading('What is missing'),
        const _Bullet('The quiz covers the **House of Commons only**. Nobody publishes an '
            'independent vote-by-vote policy mapping for the Scottish Parliament, the Senedd or '
            'the Northern Ireland Assembly, and we will not invent one quietly. Their members\' '
            'records are shown without a match.'),
        const _Bullet('A Welsh postcode finds your MP but not yet your Senedd constituency: '
            'search for that by name. Northern Ireland Assembly seats still use pre-2024 '
            'boundaries, so near an edge the lookup can return the neighbouring seat.'),

        const _Heading('What this app knows about you'),
        const _Bullet('**Your answers never leave this device.** They are political opinions, '
            'so they are kept in this app\'s own storage and nowhere else. Clearing your '
            'answers, or deleting the app, removes them.'),
        const _Bullet('**A postcode you search for is sent to postcodes.io**, an open lookup '
            'service, to find its constituencies. Searching by name sends nothing.'),
        const _Bullet('**The app fetches newer voting data** from this project\'s public '
            'repository on GitHub, at most twice a day. That request carries nothing about you '
            'or your answers.'),
        const _Bullet('There are no accounts, no adverts and no analytics.'),

        const _Heading('Sources'),
        _Para('Votes and memberships: TheyWorkForYou Votes and the parlparse register, by '
            'mySociety (CC BY 4.0)${votesAsOf.isEmpty ? '' : ', as of $votesAsOf'}.'),
        if (speechAsOf.isNotEmpty)
          _Para('Questions, speeches and Northern Ireland Assembly votes: Glasshouse\'s own '
              'collection from the four legislatures, as of $speechAsOf.'),
        const _Para('Contains Parliamentary information licensed under the Open Parliament '
            'Licence v3.0, and information from the Scottish Parliament, Senedd Cymru and the '
            'Northern Ireland Assembly under their open licences.'),
        const _Para('**Glasshouse is independent.** It is not affiliated with, or endorsed by, '
            'any parliament, government, political party or mySociety.'),
        const SizedBox(height: 4),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            onPressed: () => showLicensePage(context: context, applicationName: 'Glasshouse'),
            child: const Text('Open-source licences'),
          ),
        ),
        const SizedBox(height: 12),
        Text('Glasshouse', style: GlassText.display(16, color: c.muted)),
      ],
    );
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.text, {this.first = false});

  final String text;
  final bool first;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(top: first ? 0 : 20, bottom: 8),
        child: Semantics(
          header: true,
          child: Text(text, style: GlassText.display(21, color: context.glass.ink)),
        ),
      );
}

class _Para extends StatelessWidget {
  const _Para(this.text);

  final String text;

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.only(bottom: 10), child: Prose(text));
}

class _Bullet extends StatelessWidget {
  const _Bullet(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ExcludeSemantics(
            child: SizedBox(
              width: 18,
              child: Text('•', style: GlassText.body(15, color: c.muted)),
            ),
          ),
          Expanded(child: Prose(text)),
        ],
      ),
    );
  }
}
