// 홈 화면 아이콘 길게 누르기 — 「새 메모」·「서식으로 새 메모」(편의 기능 8번 · 애플 노트 빠른 메모).
import 'package:quick_actions/quick_actions.dart';

typedef ShortcutHandler = void Function(String type);

/// 바꿔 끼울 수 있게 — 시험은 가짜를 넣는다.
abstract class AppShortcuts {
  void start(ShortcutHandler on);
}

class HomeShortcuts implements AppShortcuts {
  const HomeShortcuts();

  static const newMemo = 'new_memo';
  static const fromTemplate = 'template_memo';

  @override
  void start(ShortcutHandler on) {
    // 지원 안 하는 기기(시험 등)에서는 비동기로 실패한다 — 삼킨다. 없어도 앱은 돈다.
    Future<void> quiet(Future<void> Function() f) async {
      try {
        await f();
      } catch (_) {}
    }

    const qa = QuickActions();
    quiet(() => qa.initialize(on));
    quiet(() => qa.setShortcutItems(const [
          ShortcutItem(type: newMemo, localizedTitle: '새 메모'),
          ShortcutItem(type: fromTemplate, localizedTitle: '서식으로 새 메모'),
        ]));
  }
}
