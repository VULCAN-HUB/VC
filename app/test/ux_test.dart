import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';
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
}
