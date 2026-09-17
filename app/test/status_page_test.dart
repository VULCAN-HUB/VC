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
    final api = VcApi(
      Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
      client: MockClient(
        (req) async => http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'trail': ['2026-09-16 10:00:00  서버 열었다'],
              'deaths': 0,
              'death_tail': [],
              'uptime_s': 125,
            }),
          ),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    final b = await box(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: StatusPage(api: api, outbox: b),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.textContaining('대기 글 · 시도 0'), findsOneWidget);
    expect(find.text('켠 지 2분'), findsOneWidget);
    expect(find.textContaining('서버 열었다'), findsOneWidget);
  });

  testWidgets('못 닿으면 까닭을 말한다', (tester) async {
    final api = VcApi(
      Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
      client: MockClient((_) async => throw http.ClientException('Connection refused')),
    );
    final b = await box(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: StatusPage(api: api, outbox: b),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.textContaining('(VC 가 꺼져 있다)'), findsOneWidget);
    expect(find.textContaining('대기 글'), findsOneWidget, reason: '못 닿아도 폰에 있는 보낼 글은 보여야 한다');
  });

  // 확장 플러그인(편의 기능 31번 · 결정 23) — 폰은 **보기만** 한다.
  MockClient routed({required int pluginStatus, Object? plugins}) => MockClient((req) async {
    if (req.url.path == '/eb/v1/plugins') {
      return http.Response.bytes(
        utf8.encode(jsonEncode(pluginStatus >= 300 ? {'error': 'not found'} : {'plugins': plugins})),
        pluginStatus,
        headers: {'content-type': 'application/json'},
      );
    }
    return http.Response.bytes(
      utf8.encode(jsonEncode({'trail': [], 'deaths': 0, 'death_tail': [], 'uptime_s': 60})),
      200,
      headers: {'content-type': 'application/json'},
    );
  });

  testWidgets('확장 — 켜진 것과 못 실은 것을 보여 주고, 켜는 길은 폰에 없다', (tester) async {
    final api = VcApi(
      Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
      client: routed(
        pluginStatus: 200,
        plugins: [
          {'name': '글자수', 'version': '1', 'note': '세어 준다', 'on': true, 'error': ''},
          {'name': '깨진것', 'version': '', 'note': '', 'on': false, 'error': 'plugin.json 를 못 읽었다'},
        ],
      ),
    );
    final b = await box(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: StatusPage(api: api, outbox: b),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.text('1개 켜짐'), findsOneWidget);
    expect(find.textContaining('● 글자수'), findsOneWidget);
    expect(find.textContaining('○ 깨진것 — 못 실었어'), findsOneWidget);
    expect(find.textContaining('컴퓨터 VC 설정'), findsOneWidget);
    // 폰에서 켜고 끄는 단추는 없다(코드가 도는 곳은 컴퓨터다)
    expect(find.byType(Switch), findsNothing);
    expect(find.byType(Checkbox), findsNothing);
  });

  testWidgets('확장 길이 없는 옛 VC 라도 상태 화면은 그대로 뜬다', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: routed(pluginStatus: 404));
    final b = await box(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: StatusPage(api: api, outbox: b),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.text('켠 지 1분'), findsOneWidget, reason: '확장 길이 없다고 상태까지 안 보이면 안 된다');
    expect(find.textContaining('확장'), findsNothing);
  });
}
