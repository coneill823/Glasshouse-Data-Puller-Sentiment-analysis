// The whole app, driven the way a person would use it: real data, a fake
// postcode service, and answers kept in memory.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/app_state.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/place.dart';
import 'package:glasshouse/core/postcode.dart';
import 'package:glasshouse/main.dart';
import 'package:glasshouse/ui/compass.dart';
import 'package:glasshouse/ui/local.dart';
import 'package:glasshouse/ui/match_page.dart';
import 'package:glasshouse/ui/member.dart';
import 'package:glasshouse/ui/widgets.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:material_ui/material_ui.dart';

import 'support.dart';

// The real data, plus an invented ward with an election and a council (see
// support.dart), so nothing here depends on what is in the register today.
final AppData data = localData;
final QuizData quiz = bundledQuiz;

const String kAssembly = 'NI Assembly';
final QuizSet assembly = quiz.chambers[kAssembly]!;
final int commonsCount = quiz.commons.coreCount;

Area seat(String name, [String parliament = kUkParliament]) =>
    data.areas.firstWhere((a) => a.parliament == parliament && a.area == name);

/// postcodes.io, as far as the app can tell.
http.Client fakePostcodes() => MockClient((request) async {
      final path = request.url.path;
      Map<String, dynamic>? result;
      if (path == '/postcodes/G128QQ') {
        result = {
          'postcode': 'G12 8QQ',
          'country': 'Scotland',
          'codes': {'parliamentary_constituency_2024': seat('Glasgow North').members.first.gss},
        };
      } else if (path == '/scotland/postcodes/G128QQ') {
        result = {
          'scottish_parliamentary_constituency': 'Glasgow Kelvin and Maryhill',
          'scottish_parliamentary_region': 'Glasgow',
        };
      } else if (path == '/postcodes/BT71NN') {
        // One MP at Westminster, several MLAs at Stormont.
        result = {
          'postcode': 'BT7 1NN',
          'country': 'Northern Ireland',
          'parliamentary_constituency_2024': 'Belfast South and Mid Down',
          'codes': {
            'parliamentary_constituency_2024':
                seat('Belfast South and Mid Down').members.first.gss,
          },
        };
      } else if (path == '/postcodes/TE51ST') {
        // The invented ward: an election coming, and a council that was read.
        result = {
          'postcode': 'TE5 1ST',
          'country': 'England',
          'admin_ward': 'Ward Two',
          'codes': {
            'parliamentary_constituency_2024': seat('Islington North').members.first.gss,
            'admin_ward': kTestWard,
            'admin_district': kTestDistrict,
            'admin_county': kTestCounty,
          },
        };
      }
      return result == null
          ? http.Response('{"status":404}', 404)
          : http.Response(jsonEncode({'status': 200, 'result': result}), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
    });

late AppState state;

/// Starts the app on a phone-sized screen.
Future<void> open(
  WidgetTester tester, {
  Size size = const Size(390, 844),
  double textScale = 1,
  Brightness brightness = Brightness.light,
  MemoryStore? store,
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  tester.platformDispatcher.platformBrightnessTestValue = brightness;
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearAllTestValues);
  await tester.pumpWidget(GlasshouseApp(
    load: () async {
      state = AppState(data: data, quiz: quiz, store: store ?? MemoryStore());
      await state.restore();
      return state;
    },
    postcodes: (state) => PostcodeLookup(state.data, client: fakePostcodes()),
  ));
  await tester.pumpAndSettle();
}

Future<void> tab(WidgetTester tester, String label) async {
  await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text(label)));
  await tester.pumpAndSettle();
}

/// Taps something that may be below the fold.
Future<void> press(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder.first);
  await tester.pumpAndSettle();
  await tester.tap(finder.first);
  await tester.pumpAndSettle();
}

/// Answers the statement on screen and waits for the next one.
Future<void> answer(WidgetTester tester, String label) async {
  await press(tester, find.text(label));
  await tester.pump(const Duration(milliseconds: 400));
  await tester.pumpAndSettle();
}

/// Looks a postcode up the way a person would.
Future<void> lookUp(WidgetTester tester, String postcode) async {
  await tester.enterText(find.byType(TextField), postcode);
  await tester.pumpAndSettle();
  await tester.tap(find.text('Find'));
  await tester.pumpAndSettle();
}

/// Answers every question of one part of the quiz, without the tapping.
void answerPart(String id, {int? first, double Function(int i)? value}) {
  state.openSection(id);
  final n = first ?? state.section.order.length;
  for (var i = 0; i < n; i++) {
    state.answer(value?.call(i) ?? (i.isEven ? 1 : -1));
    state.step(1);
  }
}

/// Something on the match screen, not on a screen kept behind it.
Finder onMatch(Finder finder) => find.descendant(of: find.byType(MatchPage), matching: finder);

/// The text of one part's Start, Continue or Review button on the quiz screen.
Finder partButton(String title) => find.descendant(
    of: find.ancestor(of: find.text(title), matching: find.byType(Panel)),
    matching: find.byWidgetPredicate((w) => w is FilledButton || w is OutlinedButton));

void main() {
  testWidgets('opens on an example and says that it is one', (tester) async {
    await open(tester);
    expect(find.text('Who represents you?'), findsOneWidget);
    expect(find.text('AN EXAMPLE — SEARCH ABOVE FOR YOURS'), findsOneWidget);
    expect(find.byType(MemberCard), findsOneWidget);
    // An example is not somewhere you live: nothing local is claimed for it.
    expect(find.byType(ElectionsHere, skipOffstage: false), findsNothing);
    expect(find.byType(CouncillorsHere, skipOffstage: false), findsNothing);
  });

  testWidgets('typing a name finds a constituency and choosing it shows who sits for it',
      (tester) async {
    await open(tester);
    await tester.enterText(find.byType(TextField), 'ynys mon');
    await tester.pumpAndSettle();
    expect(find.text('Ynys Môn'), findsWidgets); // found without typing the accent
    await tester.tap(find.widgetWithText(InkWell, 'Ynys Môn').first);
    await tester.pumpAndSettle();
    expect(state.place!.label, 'Ynys Môn');
    expect(find.text('AN EXAMPLE — SEARCH ABOVE FOR YOURS'), findsNothing);
    expect(find.byType(MemberCard), findsWidgets);
  });

  testWidgets('a search that matches nothing says so', (tester) async {
    await open(tester);
    await tester.enterText(find.byType(TextField), 'zzzzzz');
    await tester.pumpAndSettle();
    expect(find.text('No constituency or representative matches that.'), findsOneWidget);
  });

  testWidgets('a Scottish postcode brings back the MP, the MSP and the regional list',
      (tester) async {
    await open(tester);
    // Half a postcode is not searched for as if it were a name.
    await tester.enterText(find.byType(TextField), 'g12 8');
    await tester.pumpAndSettle();
    expect(find.text('Type the whole postcode, then tap Find.'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'g12 8qq');
    await tester.pumpAndSettle();
    expect(find.text('Tap Find to look up G12 8QQ.'), findsOneWidget);
    await tester.tap(find.text('Find'));
    await tester.pumpAndSettle();
    expect(state.place!.label, 'G12 8QQ');
    final expected = state.place!.areas(data).fold<int>(0, (n, a) => n + a.members.length);
    expect(expected, greaterThan(5));
    expect(find.text('$expected REPRESENTATIVES'), findsOneWidget);
    expect(find.byType(MemberCard, skipOffstage: false), findsNWidgets(expected));
  });

  testWidgets('an unknown postcode explains what to do instead', (tester) async {
    await open(tester);
    await tester.enterText(find.byType(TextField), 'ZZ99 9ZZ');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Find'));
    await tester.pumpAndSettle();
    expect(find.textContaining('That postcode was not recognised'), findsOneWidget);
    expect(state.place, isNull);
  });

  testWidgets('a card opens the full record, with the votes behind each issue', (tester) async {
    await open(tester);
    state.setPlace(Place.area(seat('Islington North')));
    await tester.pumpAndSettle();
    await press(tester, find.text('Full record'));
    expect(find.text('House of Commons'), findsOneWidget);
    expect(find.text('Voting record'), findsOneWidget);
    expect(find.textContaining('Voted in '), findsOneWidget); // the figures are explained
    await press(tester, find.textContaining('How they voted on'));
    expect(find.byType(AxisBar), findsWidgets);
    await press(tester, find.textContaining('When they broke with their party'));
    expect(find.textContaining('party '), findsWidgets);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Who represents you?'), findsOneWidget);
  });

  testWidgets('a member who never votes is explained, not scored', (tester) async {
    await open(tester);
    final sinnFein = data.members.firstWhere(
        (m) => m.parliament == kUkParliament && m.party.contains('Sinn') && m.neverVoted);
    state.setPlace(Place.area(data.areaByKey[sinnFein.areaKey]!));
    await tester.pumpAndSettle();
    expect(find.textContaining('do not take their seats'), findsOneWidget);
    expect(find.byType(MetricBar), findsNothing);
  });

  testWidgets('the quiz: five answers unlock a match, and the match shows the working',
      (tester) async {
    await open(tester);
    await tab(tester, 'Quiz');
    expect(find.text('Where do you stand?'), findsOneWidget);
    // One part for each parliament, and one for earlier ones.
    for (final title in ['House of Commons', 'Earlier parliaments', 'Northern Ireland Assembly']) {
      expect(find.text(title, skipOffstage: false), findsOneWidget);
    }
    await press(tester, partButton('House of Commons'));
    expect(find.text('STATEMENT 1 OF $commonsCount'), findsOneWidget);
    expect(find.text('I support…'), findsOneWidget);

    FilledButton seeMatch() =>
        tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'See my match'));
    expect(seeMatch().onPressed, isNull);
    expect(find.text('Answer 5 more to see a match.'), findsOneWidget);

    await answer(tester, 'Strongly agree');
    expect(state.at, 1); // moved on by itself
    expect(find.text('Answer 4 more to see a match.'), findsOneWidget);

    // Marking one as important, and going back to change an answer.
    await press(tester, find.text('This one matters a lot to me'));
    expect(state.answerFor(state.current)!.important, isTrue);
    await answer(tester, 'Disagree');
    await tester.tap(find.byTooltip('Previous statement'));
    await tester.pumpAndSettle();
    expect(state.at, 1);
    expect(state.answerFor(state.current)!.value, -0.5);
    await tester.tap(find.byTooltip('Next statement'));
    await tester.pumpAndSettle();

    await press(tester, find.text('Skip'));
    expect(state.answeredCount, 2);
    for (final label in ['Agree', 'Neutral', 'Strongly disagree']) {
      await answer(tester, label);
    }
    expect(state.answeredCount, 5);
    expect(seeMatch().onPressed, isNotNull);

    await tester.tap(find.text('See my match'));
    await tester.pumpAndSettle();
    expect(find.text('How your views line up with how they voted'), findsOneWidget);
    expect(find.text('YOUR CLOSEST MATCH IN THE HOUSE'), findsOneWidget);
    expect(find.text('Find my representatives'), findsOneWidget); // no place chosen yet
    final best = state.ranked().first;
    expect(find.text('${best.match.pct!.round()}%'), findsWidgets);
    expect(find.byType(Compass, skipOffstage: false), findsOneWidget);

    // Every figure can be traced to named divisions.
    final first = find.byWidgetPredicate(
        (w) => w is Disclosure && w.key.toString().contains('cmp-'),
        skipOffstage: false);
    expect(first, findsNWidgets(5));
    await press(tester, find.descendant(of: first.first, matching: find.byType(InkWell)));
    expect(find.byType(ExtLink, skipOffstage: false), findsWidgets);
  });

  testWidgets('with a place chosen the match is about your own MP', (tester) async {
    await open(tester);
    final islington = seat('Islington North');
    state.setPlace(Place.area(islington));
    state.start();
    for (var i = 0; i < 12; i++) {
      state.answer(i.isEven ? 1 : -1);
      state.step(1);
    }
    await tester.pumpAndSettle();

    // The card now carries the match, and leads to it.
    final mp = islington.members.first;
    final pct = state.matchOf(quiz.byId[mp.id]!).pct!.round();
    await press(tester, find.text('$pct% match with your answers'));
    expect(find.text('YOUR MP'), findsOneWidget);
    expect(find.text(mp.name), findsWidgets);

    // Choosing someone else from the list, then coming back.
    final other = state.ranked().firstWhere((r) => r.member.id != mp.id).member;
    await press(tester, find.text(other.name));
    expect(find.text('SELECTED MP'), findsOneWidget);
    await press(tester, find.text('Back to my MP'));
    expect(find.text('YOUR MP'), findsOneWidget);
  });

  testWidgets('tapping the compass names the MP nearest your finger', (tester) async {
    await open(tester);
    state.start();
    for (var i = 0; i < 12; i++) {
      state.answer(0.5);
      state.step(1);
    }
    await tab(tester, 'Match');
    expect(find.text('Tap a dot to see whose it is.', skipOffstage: false), findsOneWidget);
    final compass = find.byType(Compass);
    await tester.ensureVisible(compass);
    await tester.pumpAndSettle();
    // The crowd is densest along the middle; sweep until a dot is in reach.
    final box = tester.getRect(compass);
    for (var dx = 0.2; dx < 0.85 && find.text('Compare').evaluate().isEmpty; dx += 0.05) {
      await tester.tapAt(Offset(box.left + box.width * dx, box.top + box.height * 0.5));
      await tester.pumpAndSettle();
    }
    expect(find.text('Tap a dot to see whose it is.', skipOffstage: false), findsNothing);
  });

  testWidgets('clearing answers asks first', (tester) async {
    await open(tester);
    state.start();
    for (var i = 0; i < 6; i++) {
      state.answer(1);
      state.step(1);
    }
    await tab(tester, 'Match');
    await press(tester, find.text('Clear my answers and start again'));
    expect(find.text('Clear your answers?'), findsOneWidget);
    await tester.tap(find.text('Keep them'));
    await tester.pumpAndSettle();
    expect(state.answeredCount, 6);

    await press(tester, find.text('Clear my answers and start again'));
    await tester.tap(find.text('Clear answers'));
    await tester.pumpAndSettle();
    expect(state.answeredCount, 0);
    expect(find.text('Where do you stand?'), findsOneWidget); // back at the list of parts
    expect(find.text('0 of $commonsCount answered'), findsOneWidget);
  });

  testWidgets('the match screen asks for answers before it shows anything', (tester) async {
    await open(tester);
    await tab(tester, 'Match');
    expect(find.text('You have answered 0 so far.'), findsOneWidget);
    await tester.tap(find.text('Take the quiz'));
    await tester.pumpAndSettle();
    expect(find.text('Where do you stand?'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Start'), findsWidgets);
  });

  testWidgets('what was saved is there when the app is opened again', (tester) async {
    final store = MemoryStore();
    await open(tester, store: store);
    state.setPlace(Place.area(seat('Islington North')));
    state.start();
    for (var i = 0; i < 7; i++) {
      state.answer(-1);
      state.step(1);
    }
    await tester.pumpAndSettle();

    await tester.pumpWidget(const SizedBox()); // the app is closed
    await open(tester, store: store);
    expect(find.text('Islington North'), findsWidgets);
    expect(state.answeredCount, 7);
    await tab(tester, 'Quiz');
    expect(find.text('STATEMENT 8 OF $commonsCount'), findsOneWidget);
  });

  testWidgets('About says where the figures come from and what leaves the device',
      (tester) async {
    await open(tester);
    await tab(tester, 'About');
    expect(find.text('Actions, not words'), findsOneWidget);
    expect(find.textContaining('They are political opinions', findRichText: true,
        skipOffstage: false), findsOneWidget);
    expect(find.textContaining('not affiliated with', findRichText: true, skipOffstage: false),
        findsOneWidget);
    // What was added is explained, with its limits and whose data it is.
    for (final heading in [
      'The Scottish Parliament, the Senedd and the Assembly',
      'When a match is shown',
      'People who do not represent you now',
      'What is missing',
    ]) {
      expect(find.text(heading, skipOffstage: false), findsOneWidget);
    }
    for (final said in ['One vote is thinner evidence', 'none is given a score',
        'do not record who voted which way', 'Democracy Club (CC BY 4.0)']) {
      expect(find.textContaining(said, findRichText: true, skipOffstage: false), findsWidgets);
    }
  });

  group('a parliament of your own', () {
    testWidgets('a Belfast postcode finds the MP and every MLA, and offers the Assembly\'s questions',
        (tester) async {
      await open(tester);
      await lookUp(tester, 'BT7 1NN');
      final mlas = state.repsIn(assembly);
      expect(mlas.length, greaterThan(3));
      expect(find.byType(MemberCard), findsNWidgets(mlas.length + 1));

      await press(tester, find.text('Answer the Northern Ireland Assembly questions'));
      expect((state.tab, state.sectionId), (1, kAssembly));
      expect(find.text('VOTE 1 OF ${assembly.statements.length}'), findsOneWidget);
      expect(find.text('I would have voted for…'), findsOneWidget);

      // What exactly was voted on is one tap away, with the result.
      await press(tester, find.text('What exactly was voted on?'));
      expect(find.textContaining('One vote, on '), findsOneWidget);
      expect(find.textContaining('Agreeing means you would have voted for it'), findsOneWidget);

      // Back to the list: the Assembly's part is marked as being about your MLAs.
      await press(tester, find.widgetWithText(TextButton, 'Northern Ireland Assembly'));
      expect(find.text('Where do you stand?'), findsOneWidget);
      expect(find.text('Your MLAs'), findsOneWidget);
    });

    testWidgets('answering the Assembly\'s votes gives every MLA a match, not only the MP',
        (tester) async {
      await open(tester);
      await lookUp(tester, 'BT7 1NN');
      answerPart(kAssembly);
      await tester.pumpAndSettle();
      await tab(tester, 'Match');

      expect(find.text('YOUR REPRESENTATIVES · BT7 1NN'), findsOneWidget);
      final mlas = state.repsIn(assembly);
      final matched = [
        for (final m in mlas)
          if (state.isShown(state.matchOf(m, assembly), assembly)) m,
      ];
      expect(matched.length, greaterThan(2));
      for (final m in mlas) {
        expect(find.text(m.name), findsWidgets, reason: m.name);
      }
      for (final m in matched) {
        final pct = '${state.matchOf(m, assembly).pct!.round()}%';
        expect(find.text(pct), findsWidgets, reason: m.name);
      }
      // Anyone without a figure says why, rather than showing nothing.
      if (matched.length < mlas.length) {
        expect(find.textContaining('has not voted on these'), findsWidgets);
      }
      // The MP is not forgotten: Westminster has its own questions, and it says so.
      expect(find.textContaining('Answer at least 5 of its statements'),
          findsOneWidget);

      // The Assembly's results: about your closest MLA, vote by vote.
      expect(find.text('YOUR MLA'), findsOneWidget);
      expect(find.text('MLAS WHO VOTED MOST LIKE YOU'), findsOneWidget);
      expect(find.textContaining('VOTE BY VOTE · '), findsOneWidget);
      expect(find.byType(Compass), findsNothing); // the compass is Commons only

      // Choosing another of your MLAs from the summary makes the results about them.
      final focus = state.focusIn(assembly, state.ranked(assembly))!;
      final another = matched.firstWhere((m) => m.id != focus.id);
      await press(tester, onMatch(find.text(another.name)));
      expect(state.focusIn(assembly, state.ranked(assembly))!.id, another.id);
      expect(find.text('YOUR MLA'), findsOneWidget);

      // And someone else's MLA, from the list of the closest.
      final mine = {for (final m in mlas) m.id};
      final stranger = state.ranked(assembly).take(6).firstWhere((r) => !mine.contains(r.member.id));
      await press(tester, onMatch(find.text(stranger.member.name)));
      expect(find.text('SELECTED MLA'), findsOneWidget);

      // Each row opens onto the vote itself.
      final rows = find.byWidgetPredicate(
          (w) => w is Disclosure && w.key.toString().contains('cmp-${stranger.member.id}-'),
          );
      expect(rows, findsNWidgets(assembly.statements.length));
      await press(tester, find.descendant(of: rows.first, matching: find.byType(InkWell)));
      expect(find.byType(ExtLink), findsWidgets);
    });

    testWidgets('with only Westminster answered, the match screen says what is missing and how to add it',
        (tester) async {
      await open(tester);
      await lookUp(tester, 'BT7 1NN');
      answerPart(kCommonsSection, first: 8);
      await tester.pumpAndSettle();
      await tab(tester, 'Match');
      expect(find.text('YOUR MP'), findsOneWidget);
      expect(find.textContaining('It votes on different things from Westminster'), findsOneWidget);
      expect(find.textContaining('${state.repsIn(assembly).length} MLAs compare'), findsOneWidget);
      await press(tester, find.text('Answer its ${assembly.statements.length} questions'));
      expect((state.tab, state.sectionId, state.started), (1, kAssembly, true));
      expect(find.text('VOTE 1 OF ${assembly.statements.length}'), findsOneWidget);
    });

    testWidgets('an MLA\'s own card carries their match and leads to their results',
        (tester) async {
      await open(tester);
      await lookUp(tester, 'BT7 1NN');
      answerPart(kAssembly);
      await tester.pumpAndSettle();
      final mla = state.repsIn(assembly).lastWhere(
          (m) => state.isShown(state.matchOf(m, assembly), assembly));
      final pct = state.matchOf(mla, assembly).pct!.round();
      final card = find.ancestor(
          of: find.text(mla.name),
          matching: find.byType(MemberCard));
      await press(tester, find.descendant(
          of: card, matching: find.text('$pct% match with your answers')));
      expect(state.tab, 2);
      expect(state.focusIn(assembly, state.ranked(assembly))!.id, mla.id);
      expect(find.text('YOUR MLA'), findsOneWidget);
      // The MP's card has no figure: nothing was answered about Westminster.
      await tab(tester, 'Reps');
      final mp = state.repsIn(quiz.commons).single;
      final mpCard = find.ancestor(
          of: find.text(mp.name),
          matching: find.byType(MemberCard));
      expect(find.descendant(of: mpCard, matching: find.textContaining('% match')),
          findsNothing);
    });

    testWidgets('an MLA\'s full record shows how they voted in the quiz\'s votes', (tester) async {
      await open(tester);
      state.setPlace(Place.area(seat('Belfast South', kAssembly)));
      await tester.pumpAndSettle();
      final voter = state.repsIn(assembly).firstWhere((m) => m.pos.any((p) => p != null));
      final card = find.ancestor(
          of: find.text(voter.name),
          matching: find.byType(MemberCard));
      await press(tester,
          find.descendant(of: card, matching: find.text('Full record')));
      expect(find.text('Northern Ireland Assembly'), findsOneWidget);
      await press(tester, find.textContaining('of the quiz\'s votes'));
      expect(find.byType(AxisBar), findsWidgets);
      expect(find.textContaining('(1 vote)'), findsWidgets);
    });
  });

  testWidgets('an MP who voted on under half of it is shown as a partial picture, not hidden',
      (tester) async {
    await open(tester);
    final core = quiz.commons.coreCount;
    final mp = quiz.members.firstWhere((m) {
      final voted = m.pos.take(core).where((p) => p != null).length;
      return voted >= 7 && voted * 3 < core;
    });
    state.setPlace(Place.area(data.areaByKey[data.memberById[mp.id]!.areaKey]!));
    answerPart(kCommonsSection);
    await tester.pumpAndSettle();
    final r = state.matchOf(mp);
    expect((state.isShown(r), state.isEnough(r)), (true, false));

    // Their card carries the figure, and so does the match screen, with its basis.
    await tab(tester, 'Reps');
    await press(tester, find.text('${r.pct!.round()}% match with your answers'));
    expect(find.text('YOUR MP'), findsOneWidget);
    expect(onMatch(find.text('${r.pct!.round()}%')), findsWidgets);
    expect(find.textContaining('voted on ${r.overlap} of ${r.eligible} statements they could have'),
        findsOneWidget);
    expect(find.textContaining('so this is a partial picture'), findsOneWidget);
    expect(find.textContaining('are ranked or averaged here'), findsOneWidget);
  });

  group('people who hold no seat', () {
    testWidgets('a former MP is found by name and shown by what they did', (tester) async {
      await open(tester);
      final former = data.others.firstWhere((m) =>
          m.isFormer && m.parliament == kUkParliament && data.recordsOf(m.id).length == 1 &&
          data.search(m.name).isEmpty);
      await tester.enterText(find.byType(TextField), former.name);
      await tester.pumpAndSettle();
      expect(find.text('Former MP'), findsWidgets);
      await press(tester, find.widgetWithText(InkWell, former.name));
      expect(find.text(former.name), findsOneWidget);
      expect(find.textContaining('No longer sits in the House of Commons'), findsOneWidget);
      expect(find.textContaining('${former.since}–${former.until}'), findsOneWidget);
      expect(find.byType(MetricBar), findsWidgets);
      // Not measured against a chamber they are no longer in, nor shown a
      // count of speeches nobody collected.
      final page = find.byType(MemberPage);
      expect(find.descendant(of: page, matching: find.byType(MedianKey)), findsNothing);
      expect(find.descendant(of: page, matching: find.text('questions & speeches')), findsNothing);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Who represents you?'), findsOneWidget);
    });

    testWidgets('a former MP can still be matched with your answers', (tester) async {
      await open(tester);
      answerPart(kEarlierSection, first: 40);
      await tester.pumpAndSettle();
      final former = quiz.commons.former.firstWhere((m) =>
          state.isShown(state.matchOf(m)) && data.recordIn(m.id, kUkParliament) != null &&
          data.search(m.name).isEmpty);
      await tester.enterText(find.byType(TextField), former.name);
      await tester.pumpAndSettle();
      await press(tester, find.widgetWithText(InkWell, former.name));
      final pct = state.matchOf(former).pct!.round();
      await press(tester, find.text('$pct% match with your answers'));
      expect(state.tab, 2);
      expect(find.text('FORMER MP'), findsOneWidget);
      expect(find.text(former.name), findsWidgets);
    });

    testWidgets('a peer is found by name, and is not described as if elected or whipped',
        (tester) async {
      await open(tester);
      final peer = data.others.firstWhere(
          (m) => m.isPeer && m.party == 'Crossbench' && m.rebellions > 0 && (m.termVotes ?? 0) > 0);
      await tester.enterText(find.byType(TextField), peer.name);
      await tester.pumpAndSettle();
      expect(find.text('Peer'), findsWidgets);
      await press(tester, find.widgetWithText(InkWell, peer.name));
      expect(find.text('House of Lords'), findsOneWidget);
      expect(find.textContaining('Nobody votes for a member of the House of Lords'), findsOneWidget);
      final page = find.byType(MemberPage);
      expect(find.descendant(of: page, matching: find.text('With their group')), findsOneWidget);
      expect(find.descendant(of: page, matching: find.text('With their party')), findsNothing);
      expect(find.descendant(of: page, matching: find.byType(MedianKey)), findsOneWidget);
      expect(find.textContaining('% match'), findsNothing); // no quiz for the Lords
    });

    testWidgets('someone who moved from one chamber to another has both records, linked',
        (tester) async {
      await open(tester);
      final moved = data.others.firstWhere((m) => m.isFormer && data.memberById.containsKey(m.id));
      final now = data.memberById[moved.id]!;
      state.setPlace(Place.area(data.areaByKey[now.areaKey]!));
      await tester.pumpAndSettle();
      final card = find.ancestor(
          of: find.text(now.name),
          matching: find.byType(MemberCard));
      await press(tester,
          find.descendant(of: card, matching: find.text('Full record')));
      final house = data.chamber(moved.parliament)!.house;
      await press(tester, find.text('Used to sit in the $house'));
      expect(find.textContaining('No longer sits in the $house'), findsOneWidget);
    });
  });

  group('who can I vote for', () {
    testWidgets('a postcode shows the elections coming up there and who is standing',
        (tester) async {
      await open(tester);
      await lookUp(tester, 'TE5 1ST');
      expect(find.text('Elections coming up here'), findsOneWidget);
      expect(find.byType(BallotCard), findsNWidgets(2));
      for (final shown in ['Ward One, Testshire', 'THURSDAY 7 MAY 2099', 'Pat Example',
          'Independent · no record in office', 'North Division, Testshire County', 'Cancelled']) {
        expect(find.text(shown), findsWidgets, reason: shown);
      }
      expect(find.text('Council by-election · 1 seat · 2 standing so far'),
          findsOneWidget);
      expect(find.text('Council election · 2 seats · no candidates announced yet',
          ), findsOneWidget);
      // Standing is not an act in office, and the screen says so.
      expect(find.textContaining('Nobody here is scored for standing'),
          findsWidgets);
      expect(find.textContaining('% match'), findsNothing);

      // Someone who has held a seat before links to what they did in it.
      await press(tester, find.textContaining('has a record: see it'));
      expect(find.textContaining('No longer sits in'), findsOneWidget);
    });

    testWidgets('a candidate is found by name and shown on their ballot', (tester) async {
      await open(tester);
      await tester.enterText(find.byType(TextField), 'pat exam');
      await tester.pumpAndSettle();
      expect(find.text('Candidate'), findsOneWidget);
      expect(find.text('Independent · Ward One, Testshire · 7 May 2099'), findsOneWidget);
      await press(tester, find.widgetWithText(InkWell, 'Pat Example'));
      expect(find.text('Council by-election'), findsOneWidget);
      expect(find.byType(BallotCard), findsOneWidget);
      expect(find.textContaining('Democracy Club'), findsOneWidget);
    });

    testWidgets('a place chosen by name says what a postcode would add', (tester) async {
      await open(tester);
      final islington = seat('Islington North');
      state.setPlace(Place.area(islington));
      await tester.pumpAndSettle();
      if (data.ballotsFor(state.place!.codes).isEmpty) {
        expect(find.textContaining('Search by postcode to see elections for your council ward',
            ), findsOneWidget);
      }
      expect(find.textContaining('Search by postcode to find your ward'),
          findsOneWidget);
    });
  });

  group('councillors', () {
    testWidgets('where a council has been read, a postcode shows its councillors and their attendance',
        (tester) async {
      await open(tester);
      await lookUp(tester, 'TE5 1ST');
      expect(find.text('Your councillors'), findsOneWidget);
      for (final shown in ['TESTSHIRE COUNCIL', 'Riverside',
          'The electoral area that Ward Two ward is part of.', '15 of 20',
          'Attendance not recorded']) {
        expect(find.text(shown), findsOneWidget, reason: shown);
      }
      expect(find.textContaining('Sam Sample', findRichText: true), findsOneWidget);
      // What attendance is, and why there is no match.
      expect(find.textContaining('absence is not always a choice'), findsOneWidget);
      expect(find.textContaining('There is no match with your answers'),
          findsOneWidget);
    });

    testWidgets('everywhere else it says plainly that they are not here yet', (tester) async {
      await open(tester);
      await lookUp(tester, 'G12 8QQ');
      expect(find.textContaining('Not here yet.'), findsOneWidget);
      expect(find.textContaining('Almost no council records how each councillor voted',
          ), findsOneWidget);
    });
  });

  // Nothing may overflow or be cut off on the smallest phones, with the text
  // made larger, in either theme. Test fonts are wider than the real ones, so
  // this is a stricter check than any real device.
  for (final (name, size, scale, brightness) in const [
    ('a small phone', Size(320, 568), 1.0, Brightness.light),
    ('a small phone with large text', Size(320, 568), 1.6, Brightness.dark),
    ('a phone on its side', Size(740, 360), 1.0, Brightness.light),
    ('a tablet', Size(1024, 1366), 1.3, Brightness.dark),
  ]) {
    testWidgets('every screen lays out on $name', (tester) async {
      await open(tester, size: size, textScale: scale, brightness: brightness);
      await lookUp(tester, 'g12 8qq');
      await tester.dragUntilVisible(find.byType(MemberCard).last,
          find.byType(SingleChildScrollView).first, const Offset(0, -400));

      // Every part of the quiz answered in full, with some marked important.
      for (final part in state.sections) {
        answerPart(part.id, value: (i) => const [1.0, 0.5, 0.0, -0.5, -1.0][i % 5]);
        for (var i = 0; i < part.order.length; i += 4) {
          state.answers[part.statementAt(i).id]!.important = true;
        }
      }
      state.leaveSection();
      await tester.pumpAndSettle();

      // The list of parts, a Commons statement, and a devolved vote with its motion.
      await tab(tester, 'Quiz');
      state.openSection(kCommonsSection);
      await tester.pumpAndSettle();
      await press(tester, find.text('What did MPs vote on?', skipOffstage: false));
      final worded = assembly.statements.indexWhere((s) => s.detail.length > 400);
      state.openSection(kAssembly);
      while (worded >= 0 && state.current.id != assembly.statements[worded].id && state.step(-1)) {}
      await tester.pumpAndSettle();
      if (find.text('Read the whole motion', skipOffstage: false).evaluate().isNotEmpty) {
        await press(tester, find.text('Read the whole motion', skipOffstage: false));
      }
      await press(tester, find.text('What exactly was voted on?', skipOffstage: false));

      // Every result at once: the Commons, the compass, and three more parliaments.
      Future<void> sweep() async {
        final scroll = find.byType(SingleChildScrollView).last;
        for (var i = 0; i < 80; i++) {
          await tester.drag(scroll, const Offset(0, -500));
          await tester.pump();
        }
        await tester.pumpAndSettle();
      }

      await tab(tester, 'Match');
      await sweep();
      await tab(tester, 'About');
      await sweep();

      // Somewhere with an election, candidates and councillors.
      await tab(tester, 'Reps');
      await lookUp(tester, 'TE5 1ST');
      final reps = find.byType(SingleChildScrollView).first;
      for (var i = 0; i < 12; i++) {
        await tester.drag(reps, const Offset(0, -500));
        await tester.pump();
      }
      await tester.pumpAndSettle();
      await tab(tester, 'Match');
      await sweep();

      // Search results of every kind in one list.
      await tab(tester, 'Reps');
      await tester.enterText(find.byType(TextField), 'pat exam');
      await tester.pumpAndSettle();
      await press(tester, find.widgetWithText(InkWell, 'Pat Example'));
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'smith');
      await tester.pumpAndSettle();

      // The full record of whoever has the longest list of everything, in the
      // Commons and out of it.
      Member busiest(Iterable<Member> people) =>
          people.reduce((a, b) => a.rebellions >= b.rebellions ? a : b);
      for (final who in [
        busiest(data.members),
        busiest(data.others.where((m) => m.isPeer)),
        busiest(data.others.where((m) => m.isFormer)),
        busiest(data.members.where((m) => m.parliament == kAssembly)),
      ]) {
        final navigator = tester.state<NavigatorState>(find.byType(Navigator).first);
        navigator.push(MaterialPageRoute<void>(builder: (_) => MemberPage(who)));
        await tester.pumpAndSettle();
        for (final opens in ['How they voted', 'When they broke', 'When they voted unlike']) {
          final heading = find.textContaining(opens, skipOffstage: false);
          if (heading.evaluate().isNotEmpty) await press(tester, heading);
        }
        final page = find.byType(SingleChildScrollView).last;
        for (var i = 0; i < 30; i++) {
          await tester.drag(page, const Offset(0, -600));
          await tester.pump();
        }
        await tester.pumpAndSettle();
        navigator.pop();
        await tester.pumpAndSettle();
      }
      final problem = tester.takeException();
      expect(problem, isNull,
          reason: problem is FlutterError ? problem.toStringDeep() : '$problem');
    });
  }
}
