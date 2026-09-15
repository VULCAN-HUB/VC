import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/templates.dart';
import 'package:vc_app/vc_api.dart';

// 5단계 — 서식을 폰까지. 컴퓨터에서 받아 두고, 못 닿아도 지난번 받은 틀로 적는다. 자리는 적는 순간 채운다.
void main() {
  test('자리는 적는 순간 채우고, 모르는 이름은 그대로 둔다', () {
    final got = fillSlots('받은날 : {{날짜}} · {{제목}} · {{모르는것}}',
        title: '정수기', now: DateTime(2026, 10, 1, 9, 5));
    expect(got, '받은날 : 2026-10-01 · 정수기 · {{모르는것}}');
  });

  test('받아 두고, 못 닿으면 받아 둔 서식을 준다', () async {
    final dir = await Directory.systemTemp.createTemp('vc_tpl');
    addTearDown(() => dir.delete(recursive: true));
    var online = true;
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient((_) async {
      if (!online) throw http.ClientException('Connection refused');
      return http.Response.bytes(
          utf8.encode(jsonEncode({
            'templates': [
              {'name': '제품', 'body': '- 받은날 : {{날짜}}'}
            ]
          })),
          200,
          headers: {'content-type': 'application/json'});
    }));
    final book = TemplateBook(File('${dir.path}/vc_templates.json'));
    final (first, off1) = await book.load(api);
    expect(first.single.name, '제품');
    expect(off1, isFalse);
    online = false;
    final (again, off2) = await book.load(api);
    expect(again.single.body, '- 받은날 : {{날짜}}', reason: '못 닿으면 서식을 못 쓴다');
    expect(off2, isTrue);
  });

  testWidgets('서식을 고르면 채워서 쓰던 글 끝에 붙인다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_tpl_ui');
    addTearDown(() => dir.deleteSync(recursive: true));
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: WriteTab(
          outbox: box,
          onSend: () async {},
          templates: () async => (
            <Tpl>[(name: '제품', body: '- 받은날 : {{날짜}}\n- 이름 : {{모르는것}}')],
            false,
          ),
        ),
      ),
    ));
    await tester.enterText(find.byType(TextField).at(1), '김매니저가 보냄');
    await tester.tap(find.byTooltip('서식 넣기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('제품'));
    await tester.pumpAndSettle();

    final body = tester.widget<TextField>(find.byType(TextField).at(1)).controller!.text;
    expect(body, startsWith('김매니저가 보냄'), reason: '쓰던 글을 지웠다');
    expect(body, contains('받은날 : ${DateTime.now().year}-'));
    expect(body, contains('{{모르는것}}'));
  });
}
