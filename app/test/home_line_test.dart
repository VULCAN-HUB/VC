import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/vc_api.dart';

// 늘 보이는 한 줄(결정 17): 연결 · 보낼 것 · 오류.
// ★ 2026-09-15 아이폰 실기 — VC 를 끄고 보내니 까닭 없이 「못 닿았어」만 떴고, 대기 글이 몇 개인지는 줄에 없었다.
void main() {
  testWidgets('못 닿으면 한 줄에 까닭과 「보낼 것」 수가 보인다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_home_line');
    addTearDown(() => dir.deleteSync(recursive: true));

    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((_) async => throw http.ClientException('Connection refused')));
    final box = (await tester.runAsync(() async {
      final b = await Outbox.open(File('${dir.path}/vc_outbox.json'));
      await b.add('제목', '본문');
      return b;
    }))!;

    await tester.pumpWidget(MaterialApp(
      home: Home(api: api, outbox: box, onUnauthorized: () {}, onUnpair: () {}),
    ));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 300)));
    await tester.pump();

    expect(find.textContaining('(VC 가 꺼져 있다)'), findsOneWidget);
    expect(find.text('보낼 것 1'), findsOneWidget);
  });
}
