// The whole app, driven the way a person would use it: real data, a fake
// postcode service, and answers kept in memory.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/core/app_state.dart';
import 'package:glasshouse/core/models.dart';
import 'package:glasshouse/core/place.dart';
import 'package:glasshouse/core/postcode.dart';
import 'package:glasshouse/main.dart';
import 'package:glasshouse/ui/compass.dart';
import 'package:glasshouse/ui/member.dart';
import 'package:glasshouse/ui/widgets.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:material_ui/material_ui.dart';

final AppData data = AppData.fromJson(
    jsonDecode(File('assets/data/data.json').readAsStringSync()) as Map<String, dynamic>);
final QuizData quiz = QuizData.fromJson(
    jsonDecode(File('assets/data/quiz.json').readAsStringSync()) as Map<String, dynamic>);

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

void main() {
  testWidgets('opens on an example and says that it is one', (tester) async {
    await open(tester);
    expect(find.text('Who represents you?'), findsOneWidget);
    expect(find.text('AN EXAMPLE — SEARCH ABOVE FOR YOURS'), findsOneWidget);
    expect(find.byType(MemberCard), findsOneWidget);
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
    await press(tester, find.text('Start the quiz'));
    expect(find.text('STATEMENT 1 OF ${quiz.statements.length}'), findsOneWidget);

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
    expect(find.text('Start the quiz'), findsOneWidget);
  });

  testWidgets('the match screen asks for answers before it shows anything', (tester) async {
    await open(tester);
    await tab(tester, 'Match');
    expect(find.text('You have answered 0 so far.'), findsOneWidget);
    await tester.tap(find.text('Take the quiz'));
    await tester.pumpAndSettle();
    expect(find.text('STATEMENT 1 OF ${quiz.statements.length}'), findsOneWidget);
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
    expect(find.text('STATEMENT 8 OF ${quiz.statements.length}'), findsOneWidget);
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
      await tester.enterText(find.byType(TextField), 'g12 8qq');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Find'));
      await tester.pumpAndSettle();
      await tester.dragUntilVisible(find.byType(MemberCard).last,
          find.byType(SingleChildScrollView).first, const Offset(0, -400));

      state.start();
      for (var i = 0; i < quiz.statements.length; i++) {
        state.answer(const [1.0, 0.5, 0.0, -0.5, -1.0][i % 5]);
        if (i % 4 == 0) state.setImportant(true);
        state.step(1);
      }
      await tester.pumpAndSettle();

      await tab(tester, 'Quiz');
      await press(tester, find.text('What did MPs vote on?', skipOffstage: false));
      await tab(tester, 'Match');
      final scroll = find.byType(SingleChildScrollView).last;
      for (var i = 0; i < 40; i++) {
        await tester.drag(scroll, const Offset(0, -500));
        await tester.pump();
      }
      await tester.pumpAndSettle();
      await tab(tester, 'About');

      // And the full record of the MP with the longest list of everything.
      final busiest = data.members.reduce((a, b) => a.rebellions >= b.rebellions ? a : b);
      state.setPlace(Place.area(data.areaByKey[busiest.areaKey]!));
      await tab(tester, 'Reps');
      await press(tester, find.text('Full record', skipOffstage: false));
      await press(tester, find.textContaining('How they voted on', skipOffstage: false));
      await press(tester, find.textContaining('When they broke', skipOffstage: false));
      expect(tester.takeException(), isNull);
    });
  }
}
