/// How the figures are made, what they cannot tell you, and where they come from.
library;

import 'package:material_ui/material_ui.dart';

import '../core/models.dart';
import '../core/text.dart';
import '../theme.dart';
import 'scope.dart';
import 'widgets.dart';

class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  /// "Scotland, Wales and Northern Ireland"-style lists.
  static String _list(List<String> items) => items.length < 2
      ? items.join()
      : '${items.sublist(0, items.length - 1).join(', ')} and ${items.last}';

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    final data = state.data;
    final quiz = state.quiz;
    final commons = quiz?.commons;
    final core = commons?.coreCount ?? 0;
    final earlier = (commons?.statements.length ?? 0) - core;
    final tagged =
        commons?.statements.where((s) => s.econ != 0 || s.social != 0).length ?? 0;
    final votesAsOf = data.sources.votesAsOf;
    final speechAsOf = data.sources.speechAsOf;
    final devolved = [
      for (final set in quiz?.chambers.values ?? const <QuizSet>[])
        '${set.statements.length} for the ${data.chamber(set.parliament)?.house ?? set.parliament}',
    ];
    final former = data.others.where((m) => m.isFormer).length;
    final peers = data.others.where((m) => m.isPeer).length;
    final councils = [
      for (final b in data.councils) b.name.replaceFirst(RegExp(r' (City )?Council$'), ''),
    ];

    return PageScroll(
      children: [
        const PageHeading('How this works, and what it cannot tell you'),

        const _Heading('Actions, not words', first: true),
        const _Para('Everything here is built from what people did in office, weighted by how '
            'directly the act changes anything:'),
        const _Bullet('**Votes that use the powers of Parliament** — passing a stage of a '
            'bill, amending it, approving an order — decide your House of Commons match. They '
            'are the only votes that quiz counts.'),
        const _Bullet('**Motions that only express a view** (“this House regrets…”) are left out '
            'of the House of Commons match, however heated the debate. The devolved '
            'legislatures are different, for a reason given below.'),
        const _Bullet('**Motions signed** are shown as activity. Signing one is entirely the '
            'member\'s own choice, but it changes no law, so it never feeds a score.'),
        const _Bullet('**Questions and speeches** tell you what a member spends time on, never '
            'which side they are on. Words are too easy to misread, so they are counted and not '
            'interpreted.'),
        const _Para('Nothing comes from news coverage, social media, donations or anyone\'s '
            'opinion of a person, including ours.'),

        const _Heading('Whose judgement is in the House of Commons quiz'),
        _Para('Deciding that a vote was “for” or “against” something is a judgement, and it is '
            'not ours. The $core statements about this parliament${earlier > 0 ? ' and the '
                '$earlier about earlier ones' : ''}, the votes behind each one and which way '
            'each vote counts are the published policy groupings of TheyWorkForYou, run by the '
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

        if (devolved.isNotEmpty) ...[
          const _Heading('The Scottish Parliament, the Senedd and the Assembly'),
          _Para('Nobody publishes policy groupings for the devolved legislatures, and we will '
              'not invent them. So their questions involve no grouping at all: each one is a '
              '**single vote the legislature actually held**, and you say how you would have '
              'voted. There are ${_list(devolved)}.'),
          const _Para('Which votes are asked is fixed by a rule rather than chosen by subject: '
              'the most recent votes of the current term on a whole bill or a whole motion — '
              'never an amendment, a single clause or a point of procedure — where at least '
              'one member in ten of those voting was on the losing side, one question per bill '
              'or motion, up to 30. Where a new term has fewer than 20 such votes, the newest '
              'from the term before fill the gap.'),
          const _Para('The wording is the legislature\'s own title, and the motion as it was '
              'put where its records give it. Voting aye is “for”; nothing is paraphrased.'),
          const _Bullet('**Most of these are motions that express a view, not laws.** The '
              'devolved legislatures divide on few bills, so leaving such motions out, as the '
              'Commons quiz does, would leave almost nothing to ask. Voting on one is still '
              'something each member did, but it changes less than a vote on a bill. Every '
              'question is marked Bill or Motion so you can tell.'),
          const _Bullet('**One vote is thinner evidence** than a Commons statement, which pools '
              'several. Members sometimes vote against a motion they sympathise with because '
              'of its wording or who proposed it.'),
          const _Bullet('The Scottish Parliament and the Senedd were elected in May 2026, so '
              'most of their questions come from the term before. **A member first elected '
              'in 2026 did not vote on those**, and gets a match only once they have voted '
              'on enough.'),
          const _Bullet('The Senedd\'s record gives each vote\'s title but not its wording. '
              'Follow the link on a question before answering if its title could be read '
              'either way.'),
          const _Bullet('Figures from different parliaments cannot be compared with each '
              'other: they are answers to different questions.'),
        ],

        const _Heading('When a match is shown'),
        const _Para('A figure is shown once you and a member both have a view on at least '
            'five things, and it always says how many it rests on.'),
        const _Para('To be **ranked** among those who voted most like you, or counted in a '
            'party\'s average, a member must also have voted on at least half of what you '
            'answered, out of the votes held while they were a member. Someone elected in '
            '2024 could not have voted on tuition fees in 2004, and that is not held against '
            'them. Someone who was a member and did not vote has left a gap. An MP from '
            'Northern Ireland or Scotland who stays out of votes on laws for England may '
            'have voted on a third of what you answered: you still see their figure and '
            'what it rests on, marked as a partial picture, but it is not ranked above '
            'members with a full record.'),

        const _Heading('What a vote does and does not mean'),
        const _Para('A vote is not an opinion. Most votes are whipped: the typical member votes '
            'with their party about 99% of the time, so on most statements your MP\'s record is '
            'their party\'s. And members vote against things for different reasons — an '
            'opposition MP may oppose a bill because it goes too far, or not far enough. What '
            'the record does show, without interpretation, is how each of them used the power '
            'you gave them.'),
        const _Para('The questions follow what was actually voted on, which is mostly the '
            'government\'s programme. Subjects no parliament has voted on are not here.'),

        const _Heading('The compass'),
        _Para('The compass is the one interpretive layer we add, and it covers the House of '
            'Commons only. Each statement that sits clearly on an economic (left–right) or '
            'social (liberal–authoritarian) axis is tagged with one: $tagged are, and '
            '${core + earlier - tagged} that do not are left untagged. You and every MP are '
            'placed with the same tags, so any mistake in them moves everyone identically.'),
        const _Para('As a check, the tags were compared with the structure of the voting '
            'record itself, with no tagging at all. Among sitting MPs on this parliament\'s '
            'statements, the leading pattern lines up with our economic axis (correlation '
            '0.98) and the second with our social axis (0.76). Across every statement and '
            'everyone who has voted on them since 1997 the economic axis still holds (0.89) '
            'but the social one is much weaker (0.40): over thirty years, what divides MPs '
            'on social questions has changed more than our one axis can follow. Treat the '
            'up-and-down position as rougher than the left-and-right one. It shows where '
            'votes sit, not what anyone believes.'),

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

        const _Heading('People who do not represent you now'),
        if (former + peers > 0)
          _Para('Searching by name also finds **${thousands(former)} former MPs, MSPs and '
              'MSs** and the **${thousands(peers)} members of the House of Lords**. They are '
              'shown the same way, by what they did with their votes, and a former MP can be '
              'matched with your answers on the statements they voted on. Peers are not '
              'elected, and there is no quiz for the Lords.'),
        _Para('**Candidates** in an election that has not happened yet are listed under the '
            'place they are standing${data.ballots.isEmpty ? '' : ' (${data.ballots.length} '
                'ballots are in the register now)'}. The list is Democracy Club\'s, compiled by '
            'volunteers from each council\'s official notices. A candidate has done nothing in '
            'office, so none is given a score; one who has held a seat before links to that '
            'record. Only a name, a party and where they are standing are kept. Nobody appears '
            'until they are on that register: this app does not guess who might stand.'),
        if (councils.isNotEmpty)
          _Para('**Councillors** are a trial, with ${_list(councils)} so far. What it found is '
              'that councils do not record who voted which way — most votes are a show of '
              'hands, written down only as carried or lost — so a councillor cannot be '
              'matched with your views from their record. Where a council publishes '
              'attendance, that is shown, with what it covers, and nothing more is made of it.'),

        const _Heading('What is missing'),
        const _Bullet('Former members of the Northern Ireland Assembly, and votes there before '
            'the current term.'),
        const _Bullet('Mayors, police and crime commissioners and the London Assembly, except '
            'as candidates when an election is coming.'),
        const _Bullet('A Welsh postcode finds your MP but not yet your Senedd constituency: '
            'search for that by name. Northern Ireland Assembly seats still use pre-2024 '
            'boundaries, so near an edge the lookup can return the neighbouring seat.'),

        const _Heading('What this app knows about you'),
        const _Bullet('**Your answers never leave this device.** They are political opinions, '
            'so they are kept in this app\'s own storage and nowhere else. Clearing your '
            'answers, or deleting the app, removes them.'),
        const _Bullet('**A postcode you search for is sent to postcodes.io**, an open lookup '
            'service, to find its constituencies, ward and council. Elections and councillors '
            'are then found on this device from those. Searching by name sends nothing.'),
        const _Bullet('**The app fetches newer data** from this project\'s public repository '
            'on GitHub, at most twice a day. That request carries nothing about you or your '
            'answers.'),
        const _Bullet('There are no accounts, no adverts and no analytics.'),

        const _Heading('Sources'),
        _Para('Votes and memberships: TheyWorkForYou Votes and the parlparse register, by '
            'mySociety (CC BY 4.0)${votesAsOf.isEmpty ? '' : ', as of $votesAsOf'}.'),
        if (speechAsOf.isNotEmpty)
          _Para('Questions, speeches and Northern Ireland Assembly votes: Glasshouse\'s own '
              'collection from the four legislatures, as of $speechAsOf.'),
        _Para('Elections and candidates: Democracy Club (CC BY 4.0)'
            '${data.electionsAsOf.isEmpty ? '' : ', as of ${data.electionsAsOf}'}.'),
        const ExtLink('Democracy Club', 'https://democracyclub.org.uk/'),
        if (councils.isNotEmpty)
          _Para('Councillors and attendance: each council\'s own published committee records'
              '${data.councilPeriod.to.isEmpty ? '' : ', as of ${data.councilPeriod.to}'}. '
              'Northern Ireland\'s electoral areas: the District Electoral Areas (Northern '
              'Ireland) Order 2014, on legislation.gov.uk.'),
        const _Para('Contains Parliamentary information licensed under the Open Parliament '
            'Licence v3.0, public sector information licensed under the Open Government '
            'Licence v3.0, and information from the Scottish Parliament, Senedd Cymru and the '
            'Northern Ireland Assembly under their open licences.'),
        const _Para('**Glasshouse is independent.** It is not affiliated with, or endorsed by, '
            'any parliament, council, government, political party, mySociety or Democracy '
            'Club.'),
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
