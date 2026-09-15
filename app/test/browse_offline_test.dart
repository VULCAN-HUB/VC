import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/vc_api.dart';

// ★ 2026-09-15 아이폰 실기 — 못 닿았는데 「창고 앞머리 0장」이 떠 창고가 빈 것처럼 보였다. 못 센 것은 0 이 아니다.
void main() {
  testWidgets('못 닿으면 「0장」 대신 못 불렀다고 말한다', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((_) async => throw http.ClientException('Connection refused')));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: BrowseTab(api: api, onFail: (_) {}))));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pump();

    expect(find.text('0장'), findsNothing, reason: '못 닿았는데 창고가 빈 것처럼 보인다');
    expect(find.textContaining('못 불렀어'), findsOneWidget);
  });
}
