/// The four screens and the bar that moves between them.
library;

import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../theme.dart';
import 'about_page.dart';
import 'match_page.dart';
import 'quiz_page.dart';
import 'reps_page.dart';
import 'scope.dart';
import 'widgets.dart';

class Shell extends StatelessWidget {
  const Shell({super.key});

  static const List<Widget> _pages = [RepsPage(), QuizPage(), MatchPage(), AboutPage()];

  @override
  Widget build(BuildContext context) {
    final c = context.glass;
    final state = AppScope.of(context);
    // On a tablet the name lines up with the column of content below it.
    final width = MediaQuery.sizeOf(context).width;
    final side = math.max(kGutter, (width - kMaxContentWidth) / 2);
    return Scaffold(
      appBar: AppBar(titleSpacing: side, title: const Text('Glasshouse')),
      body: SafeArea(
        top: false,
        bottom: false,
        child: _KeptPages(index: state.tab, children: _pages),
      ),
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line))),
        child: NavigationBar(
          selectedIndex: state.tab,
          onDestinationSelected: (index) {
            // Leaving a screen puts its keyboard away.
            FocusManager.instance.primaryFocus?.unfocus();
            state.go(index);
          },
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.account_balance_outlined),
              selectedIcon: Icon(Icons.account_balance),
              label: 'Reps',
              tooltip: 'Your representatives',
            ),
            NavigationDestination(
              icon: Icon(Icons.fact_check_outlined),
              selectedIcon: Icon(Icons.fact_check),
              label: 'Quiz',
            ),
            NavigationDestination(
              icon: Icon(Icons.explore_outlined),
              selectedIcon: Icon(Icons.explore),
              label: 'Match',
              tooltip: 'Your match',
            ),
            NavigationDestination(
              icon: Icon(Icons.info_outline),
              selectedIcon: Icon(Icons.info),
              label: 'About',
              tooltip: 'How it works',
            ),
          ],
        ),
      ),
    );
  }
}

/// Shows one screen at a time. A screen is first built when it is first
/// visited, and then kept, so that coming back finds it where you left it.
class _KeptPages extends StatefulWidget {
  const _KeptPages({required this.index, required this.children});

  final int index;
  final List<Widget> children;

  @override
  State<_KeptPages> createState() => _KeptPagesState();
}

class _KeptPagesState extends State<_KeptPages> {
  late final List<bool> _visited = List<bool>.filled(widget.children.length, false);

  @override
  Widget build(BuildContext context) {
    _visited[widget.index] = true;
    return IndexedStack(
      index: widget.index,
      children: [
        for (var i = 0; i < widget.children.length; i++)
          _visited[i] ? widget.children[i] : const SizedBox.shrink(),
      ],
    );
  }
}
