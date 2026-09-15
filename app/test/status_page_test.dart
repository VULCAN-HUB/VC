import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/vc_api.dart';

// 눌러야 펴지는 「상태·기록」(결정 17 ③): 보낼 글 · 컴퓨터 켠 지 · 최근 기록. 못 닿으면 까닭.
void main() {
  Future<Outbox> box(WidgetTester tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_status');
    addTearDown(() => dir.deleteSync(recursive: true));
    return (await tester.runAsync(() async {
      final b = await Outbox.open(File('${dir.path}/vc_outbox.json'));
      await b.add('대기 글', '본문');
      return b;
    }))!;
  }

  testWidgets('컴퓨터 상태와 보낼 글이 보인다', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((req) async => http.Response.bytes(
            utf8.encode(jsonEncode({
              'trail': ['2026-09-16 10:00:00  서버 열었다'],
              'deaths': 0,
              'death_tail': [],
              'uptime_s': 125,
            })),
            200,
            headers: {'content-type': 'application/json'})));
    final b = await box(tester);
    await tester.pumpWidget(MaterialApp(home: StatusPage(api: api, outbox: b)));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.textContaining('대기 글 · 시도 0'), findsOneWidget);
    expect(find.text('켠 지 2분'), findsOneWidget);
    expect(find.textContaining('서버 열었다'), findsOneWidget);
  });

  testWidgets('못 닿으면 까닭을 말한다', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((_) async => throw http.ClientException('Connection refused')));
    final b = await box(tester);
    await tester.pumpWidget(MaterialApp(home: StatusPage(api: api, outbox: b)));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.textContaining('(VC 가 꺼져 있다)'), findsOneWidget);
    expect(find.textContaining('대기 글'), findsOneWidget, reason: '못 닿아도 폰에 있는 보낼 글은 보여야 한다');
  });
}
