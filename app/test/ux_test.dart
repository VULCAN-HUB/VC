import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/prefs.dart';
import 'package:vc_app/shortcuts.dart';
import 'package:vc_app/vc_api.dart';

// 편의성 손질(2026-09-18 · 오너: 번잡하고 찾기 힘들다) — 노션·에버노트 기준.
http.Response _json(Object body) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), 200, headers: {'content-type': 'application/json'});

void main() {
  test('날짜를 사람 말로', () {
    final now = DateTime(2026, 9, 18, 10);
    expect(whenLabel('2026-09-18', now: now), '오늘');
    expect(whenLabel('2026-09-17', now: now), '어제');
    expect(whenLabel('2026-03-02', now: now), '3월 2일');
    expect(whenLabel('2025-12-31', now: now), '2025.12.31');
  });

  testWidgets('목록 — 태그 칩이 생기고, 누르면 그 태그로 좁혀 찾는다 · 사진 칩은 사진 붙은 글만', (tester) async {
    final asked = <String>[];
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient((req) async {
      final q = req.url.queryParameters['q'] ?? '';
      asked.add(q);
      expect(req.url.queryParameters['card'], '1', reason: '목록 카드 칸을 안 달라고 했다');
      return _json({
        'results': [
          if (q.isEmpty || q.contains('tag:제품'))
            {'title': '정수기', 'preview': '종류: 정수기', 'tags': ['제품'], 'image': '정수기.jpg', 'updated': '2026-09-18'},
          if (q.isEmpty) {'title': '장보기', 'preview': '우유 · 달걀', 'tags': ['일상']},
        ]
      });
    }));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: BrowseTab(api: api, onFail: (_) {}))));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pump();

    expect(find.text('#제품'), findsWidgets, reason: '태그 칩이 안 생겼다');
    expect(find.text('장보기'), findsOneWidget);
    expect(find.bySemanticsLabel('정수기.jpg'), findsOneWidget, reason: '카드에 사진 미리보기가 없다');

    await tester.tap(find.widgetWithText(ChoiceChip, '#제품'));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pump();
    expect(asked.last, 'tag:제품');
    expect(find.text('장보기'), findsNothing);

    await tester.tap(find.widgetWithText(ChoiceChip, '📷 사진'));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pump();
    expect(asked.last, '', reason: '사진 칩은 전체에서 사진 붙은 것만 고른다');
    expect(find.text('정수기'), findsOneWidget);
    expect(find.text('장보기'), findsNothing, reason: '사진 없는 글이 사진 칩에 섞였다');
  });

  testWidgets('글 보기 — 「- 키 : 값」 줄은 항목표로, 태그 줄은 칩으로', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: NoteBody(api: api, text: '- 제품명 : vcis-689\n- 보낸날 : \n\n#제품 #정수기\n\n메모 한 줄'),
        ),
      ),
    ));
    expect(find.text('제품명'), findsOneWidget, reason: '항목 이름이 따로 안 보인다');
    expect(find.text('vcis-689'), findsOneWidget);
    expect(find.text('—'), findsOneWidget, reason: '빈 항목은 — 로');
    expect(find.text('#정수기'), findsOneWidget, reason: '태그가 칩으로 안 갈렸다');
    expect(find.textContaining('- 제품명'), findsNothing);
    expect(find.text('메모 한 줄'), findsOneWidget);
  });

  testWidgets('편집기 — 적은 채로 닫으면 버릴지 묻고, 저장하면 닫힌다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_editor');
    addTearDown(() => dir.deleteSync(recursive: true));
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    OutboxItem? got;
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (c) => Scaffold(
          body: TextButton(
            child: const Text('열기'),
            onPressed: () async {
              got = await Navigator.push<OutboxItem>(
                  c, MaterialPageRoute(builder: (_) => EditorPage(outbox: box, onSend: () async {})));
            },
          ),
        ),
      ),
    ));
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(1), '급히 적은 것');
    await tester.pump();

    await tester.tap(find.byTooltip('닫기'));
    await tester.pumpAndSettle();
    expect(find.text('적은 것을 버릴까?'), findsOneWidget, reason: '적은 글이 말없이 사라진다');
    await tester.tap(find.text('계속 쓰기'));
    await tester.pumpAndSettle();

    await tester.runAsync(() async {
      await tester.tap(find.text('저장'));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pumpAndSettle();
    expect(find.text('열기'), findsOneWidget, reason: '저장했는데 편집기가 안 닫힌다');
    expect(got?.text, '급히 적은 것');
  });

  testWidgets('정리 글 — 표 · 소제목 · 링크는 보일 말만', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: NoteBody(api: api, text: '> VC 가 다시 쓰는 글\n\n## 보유중 (1)\n\n| 제품 | 종류 |\n|---|---|\n| [[제품 · vcis-689\\|vcis-689]] | 정수기 |\n\n근거 [[정수기 받음]] 참고'),
        ),
      ),
    ));
    expect(find.byType(Table), findsOneWidget, reason: '표를 안 그린다');
    expect(find.text('vcis-689'), findsOneWidget, reason: '표 안 링크가 보일 말로 안 바뀐다');
    expect(find.text('보유중 (1)'), findsOneWidget);
    expect(find.textContaining('[['), findsNothing, reason: '링크 기호가 그대로 보인다');
    expect(find.textContaining('|---|'), findsNothing);
    expect(find.text('근거 정수기 받음 참고'), findsOneWidget);
  });

  testWidgets('새 메모를 길게 누르면 서식으로 새 글 — 채운 틀로 편집기가 열린다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_tpl_new');
    addTearDown(() => dir.deleteSync(recursive: true));
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient((req) async {
      if (req.url.path == '/eb/v1/templates') {
        return _json({
          'templates': [
            {'name': '제품', 'body': '- 제품명 : \n- 받은날 : {{날짜}}'}
          ]
        });
      }
      if (req.url.path == '/eb/v1/hello') return _json({'store': {'notes': 0}});
      return _json({'results': []});
    }));
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    await tester.pumpWidget(MaterialApp(home: Home(api: api, outbox: box, onUnauthorized: () {}, onUnpair: () {})));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pump();

    await tester.longPress(find.text('새 메모'));
    for (var i = 0; i < 5; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 60)));
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.pumpAndSettle();
    await tester.tap(find.text('제품'));
    await tester.pumpAndSettle();

    final body = tester.widget<TextField>(find.byType(TextField).at(1)).controller!.text;
    expect(body, contains('- 제품명 : '));
    expect(body, contains('받은날 : ${DateTime.now().year}-'), reason: '서식 자리를 안 채웠다');
    expect(find.text('새 메모'), findsWidgets);
  });

  testWidgets('글 보기 칸 누르기 — 상태를 골라 글 끝에 한 줄로 덧붙인다', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient((req) async {
      return _json({'title': '정수기', 'text': '- 제품명 : vcis-689\n- 상태 : 보유중'});
    }));
    final saved = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: NotePage(
        api: api,
        onFail: (_) {},
        title: '정수기',
        onSaveLine: (t, line) async => saved.add('$t|$line'),
      ),
    ));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('보유중'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('보냄'));
    await tester.pumpAndSettle();
    expect(saved, ['정수기|- 상태 : 보냄'], reason: '고른 상태가 글 끝에 안 적혔다');

    // 그대로 고르면 안 적는다
    await tester.tap(find.text('보유중'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('보유중').last);
    await tester.pumpAndSettle();
    expect(saved.length, 1, reason: '안 바꿨는데 적었다');
  });

  testWidgets('글 보기 ⋮ — AI 요약 결과를 보이고 글 끝에 붙인다 · 모델 없으면 까닭', (tester) async {
    var hasModel = true;
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient((req) async {
      if (req.url.path == '/eb/v1/assist') {
        if (!hasModel) {
          return http.Response.bytes(utf8.encode(jsonEncode({'error': '대화 모델이 없다'})), 503,
              headers: {'content-type': 'application/json'});
        }
        return _json({'text': '- 정수기 받음'});
      }
      return _json({'title': '정수기', 'text': '긴 메모'});
    }));
    final saved = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: NotePage(api: api, onFail: (_) {}, title: '정수기', onSaveLine: (t, l) async => saved.add(l)),
    ));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pumpAndSettle();

    Future<void> ask() async {
      await tester.tap(find.byIcon(Icons.more_vert));
      await tester.pumpAndSettle();
      await tester.tap(find.text('AI 요약'));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
      await tester.pumpAndSettle();
    }

    await ask();
    expect(find.text('- 정수기 받음'), findsOneWidget);
    await tester.tap(find.text('글 끝에 붙이기'));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pumpAndSettle();
    expect(saved.single, startsWith('## AI 요약'));

    hasModel = false;
    await ask();
    expect(find.text('대화 모델이 없다'), findsOneWidget, reason: '모델이 없는 까닭을 안 알린다');
  });

  testWidgets('설정 「열면 바로 새 메모」 — 켜면 앱이 편집기로 열리고, 설정은 남는다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_prefs');
    addTearDown(() => dir.deleteSync(recursive: true));
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((req) async => _json({'results': [], 'store': {'notes': 0}})));
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    final prefs = (await tester.runAsync(() => AppPrefs.open(File('${dir.path}/vc_settings.json'))))!;
    expect(prefs.openNew, isFalse);
    await tester.runAsync(() => prefs.setOpenNew(true));
    final again = (await tester.runAsync(() => AppPrefs.open(File('${dir.path}/vc_settings.json'))))!;
    expect(again.openNew, isTrue, reason: '설정이 안 남는다');

    await tester.pumpWidget(MaterialApp(
        home: Home(api: api, outbox: box, onUnauthorized: () {}, onUnpair: () {}, prefs: again)));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pumpAndSettle();
    expect(find.byType(EditorPage), findsOneWidget, reason: '켰는데 바로 새 메모로 안 열린다');
  });

  testWidgets('홈 아이콘 길게 누르기 「새 메모」 — 편집기로 연다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_qa');
    addTearDown(() => dir.deleteSync(recursive: true));
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((req) async => _json({'results': [], 'store': {'notes': 0}})));
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    final fake = _FakeShortcuts();
    await tester.pumpWidget(MaterialApp(
        home: Home(api: api, outbox: box, onUnauthorized: () {}, onUnpair: () {}, shortcuts: fake)));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pumpAndSettle();
    expect(find.byType(EditorPage), findsNothing);
    fake.on!(HomeShortcuts.newMemo);
    await tester.pumpAndSettle();
    expect(find.byType(EditorPage), findsOneWidget, reason: '아이콘 「새 메모」로 편집기가 안 열린다');
  });

  testWidgets('사진 속 글자 — 저장 때 숨은 주석으로 붙고, 글 보기에는 안 보인다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_ocr');
    addTearDown(() => dir.deleteSync(recursive: true));
    final pic = File('${dir.path}/IMG_9.jpg')..writeAsBytesSync([1]);
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: WriteTab(
          outbox: box,
          onSend: () async {},
          pick: (_) async => [pic],
          readText: (f) async => '운송장 55667788',
        ),
      ),
    ));
    await tester.tap(find.byTooltip('사진첩에서 고르기'));
    await tester.pump();
    await tester.enterText(find.byType(TextField).at(1), '택배 보냄');
    await tester.runAsync(() async {
      await tester.tap(find.text('저장'));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pump();
    final text = box.items.single.text;
    expect(text, startsWith('택배 보냄'));
    expect(text, contains('%%'));
    expect(text, contains('운송장 55667788'), reason: '사진 글자가 안 붙었다');

    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: NoteBody(api: api, text: text))));
    expect(find.textContaining('55667788'), findsNothing, reason: '숨은 글자가 보인다');
    expect(find.text('택배 보냄'), findsOneWidget);
  });
}

class _FakeShortcuts implements AppShortcuts {
  ShortcutHandler? on;

  @override
  void start(ShortcutHandler on) => this.on = on;
}
