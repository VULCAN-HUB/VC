import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/vc_api.dart';

// ★ 2026-09-15 아이폰 실기 — 못 닿았는데 「창고 앞머리 0장」이 떠 창고가 빈 것처럼 보였다. 못 센 것은 0 이 아니다.
void main() {
  testWidgets('못 닿으면 「0장」 대신 못 불렀다고 말한다', (tester) async {
    final api = VcApi(
      Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
      client: MockClient((_) async => throw http.ClientException('Connection refused')),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: BrowseTab(api: api, onFail: (_) {}),
        ),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.text('0장'), findsNothing, reason: '못 닿았는데 창고가 빈 것처럼 보인다');
    expect(find.textContaining('컴퓨터에 못 닿았고, 폰에 남은 것도 없어'), findsOneWidget, reason: '못 닿았는데 까닭도 다음에 할 일도 안 알려 준다');
  });

  // ★ 2026-09-18 시뮬레이터 — 보관함이 비었는데 「아직 창고가 비었어 — 아래 「새 메모」로 시작」 이라고 했다.
  //   창고에는 글이 있었고, 그 화면에는 「새 메모」 단추도 없다. 빈 까닭은 화면마다 다르다.
  testWidgets('보관함이 비면 창고가 빈 것처럼 말하지 않는다', (tester) async {
    final api = VcApi(
      Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
      client: MockClient(
        (_) async => http.Response.bytes(
          utf8.encode(jsonEncode({'results': []})),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: BrowseTab(api: api, archived: true, onFail: (_) {}),
        ),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.textContaining('창고가 비었어'), findsNothing, reason: '보관함이 빈 것을 창고가 빈 것으로 말한다');
    expect(find.textContaining('새 메모'), findsNothing, reason: '이 화면에는 없는 단추를 가리킨다');
    expect(find.textContaining('보관한 글이 없어'), findsOneWidget);
  });

  testWidgets('그냥 목록이 비면 창고가 비었다고 말한다', (tester) async {
    final api = VcApi(
      Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
      client: MockClient(
        (_) async => http.Response.bytes(
          utf8.encode(jsonEncode({'results': []})),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: BrowseTab(api: api, onFail: (_) {}),
        ),
      ),
    );
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.textContaining('아직 창고가 비었어'), findsOneWidget);
  });
}
