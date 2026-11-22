// Runs the real app on a real device or emulator:
//
//   flutter test integration_test            (with a phone or emulator attached)
//
// The tests in test/ replace the phone's storage and the network with
// stand-ins. This one does not: it reads the data the app shipped with,
// saves answers through the phone's own storage, closes the app and opens
// it again. It is what shows the installed app works, not just its code.
import 'package:flutter_test/flutter_test.dart';
import 'package:glasshouse/main.dart';
import 'package:glasshouse/ui/member.dart';
import 'package:integration_test/integration_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Waits for something to appear: loading is real here, so it takes real time.
Future<void> appears(WidgetTester tester, Finder finder, {int seconds = 60}) async {
  for (var i = 0; i < seconds * 5; i++) {
    if (finder.evaluate().isNotEmpty) return;
    await tester.pump(const Duration(milliseconds: 200));
  }
  expect(finder, findsWidgets);
}

Future<void> press(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder.first);
  await tester.pumpAndSettle();
  await tester.tap(finder.first);
  await tester.pumpAndSettle();
}

/// Types into the search box.
///
/// The test binding asks for the keyboard only when the field being typed into
/// is a different one from last time. On a real device nothing tells it that
/// the box was left in between, so typing into the same box twice would be
/// dropped the second time unless it is made to forget the first.
Future<void> search(WidgetTester tester, String text) async {
  tester.binding.focusedEditable = null;
  await tester.enterText(find.byType(TextField), text);
  await tester.pumpAndSettle();
}

Future<void> tab(WidgetTester tester, String label) => press(
    tester, find.descendant(of: find.byType(NavigationBar), matching: find.text(label)));

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('the installed app opens, takes answers, and still has them next time',
      (tester) async {
    // Start from a clean install, whatever an earlier run left behind.
    await (await SharedPreferences.getInstance()).clear();

    await tester.pumpWidget(const GlasshouseApp());
    await appears(tester, find.text('Who represents you?'));
    expect(find.byType(MemberCard), findsWidgets); // the bundled data was read

    // Search works on the real data.
    await search(tester, 'Islington North');
    await press(tester, find.widgetWithText(InkWell, 'Islington North'));
    expect(find.text('1 REPRESENTATIVE'), findsOneWidget);

    // Five answers about the House of Commons, then a match.
    const answers = ['Strongly agree', 'Agree', 'Neutral', 'Disagree', 'Strongly disagree'];
    Future<void> answerFive() async {
      for (final answer in answers) {
        await press(tester, find.text(answer));
        await tester.pump(const Duration(milliseconds: 500)); // it moves on by itself
        await tester.pumpAndSettle();
      }
    }

    await tab(tester, 'Quiz');
    await press(tester, find.widgetWithText(FilledButton, 'Start')); // the first part: the Commons
    expect(find.textContaining('STATEMENT 1 OF'), findsOneWidget);
    await answerFive();
    expect(find.textContaining('5 answered'), findsOneWidget);
    await press(tester, find.text('See my match'));
    await appears(tester, find.text('YOUR MP'));
    expect(find.textContaining('%'), findsWidgets);

    // A devolved parliament has questions of its own, and they match its
    // members: several of them for one place, not only an MP.
    await tab(tester, 'Reps');
    await search(tester, 'Belfast South');
    await press(tester, find.widgetWithText(InkWell, 'Belfast South'));
    expect(find.byType(MemberCard), findsAtLeastNWidgets(3));
    await press(tester, find.text('Answer the Northern Ireland Assembly questions'));
    expect(find.textContaining('VOTE 1 OF'), findsOneWidget);
    await answerFive();
    await press(tester, find.text('See my match'));
    await appears(tester, find.text('YOUR MLA'));
    expect(find.text('MLAS WHO VOTED MOST LIKE YOU'), findsOneWidget);

    // Close the app and open it again: the phone's own storage must have
    // kept the place, the answers, and where each part of the quiz had got to.
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    await tester.pumpWidget(GlasshouseApp(key: UniqueKey()));
    await appears(tester, find.text('Who represents you?'));
    expect(find.text('Belfast South'), findsWidgets);
    await tab(tester, 'Quiz');
    expect(find.textContaining('5 answered'), findsOneWidget);
    expect(find.textContaining('VOTE 6 OF'), findsOneWidget);
    await press(tester, find.widgetWithText(TextButton, 'Northern Ireland Assembly'));
    // Back at the list of parts: five answered in each of the two taken.
    expect(find.textContaining(RegExp(r'^5 of \d+ answered$')), findsNWidgets(2));
  });
}
