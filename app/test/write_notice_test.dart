import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/vc_api.dart';

// ★ 윈도우 실기(2026-09-15): 오프라인에서 저장하면 알림 줄이 「폰에 저장됨 · 전송 대기」가 되는데,
//   나중에 보내져도 그 줄이 그대로 남고 아래 목록만 「서버 저장 완료」로 바뀌었다.
//   알림 줄은 저장할 때만 바뀌었기 때문이다 — 대기함이 그 글을 보내면 줄도 따라 바뀌어야 한다.
void main() {
  testWidgets('오프라인에 저장한 글이 나중에 보내지면 알림 줄도 「서버 저장 완료」로 바뀐다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_write_notice');
    addTearDown(() => dir.deleteSync(recursive: true));

    var online = false;
    final api = VcApi(
      Pairing.parse('http://192.168.0.5:8765/app#t=tok')!,
      client: MockClient((req) async {
        if (!online) throw http.ClientException('끊김');
        final b = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response.bytes(utf8.encode(jsonEncode({'title': b['title']})), 201,
            headers: {'content-type': 'application/json'});
      }),
    );

    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: WriteTab(outbox: box, onSend: () async => box.flush(api)),
      ),
    ));

    await tester.enterText(find.byType(TextField).at(1), '받은 제품 메모');
    await tester.runAsync(() async {
      await tester.tap(find.text('저장'));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pump();
    expect(find.textContaining('전송 대기 — 연결되면 보낸다'), findsOneWidget);

    online = true;
    await tester.runAsync(() => box.flush(api));
    await tester.pump();

    expect(find.textContaining('전송 대기 — 연결되면 보낸다'), findsNothing, reason: '보내졌는데 알림 줄에 옛 말이 남았다');
    expect(find.textContaining('서버 저장 완료 — 「'), findsOneWidget);
  });
}
