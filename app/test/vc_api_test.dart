import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/vc_api.dart';

http.Response _json(Object body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

VcApi _api(MockClientHandler h) => VcApi(Pairing.parse('http://192.168.0.5:8765/app#t=tok')!, client: MockClient(h));

void main() {
  test('QR 주소를 읽는다 — 열쇠는 # 뒤에서만', () {
    final p = Pairing.parse('http://192.168.0.5:8765/app#t=a%2Fb%2Bc')!;
    expect(p.base.toString(), 'http://192.168.0.5:8765');
    expect(p.token, 'a/b+c');
    expect(p.label, '192.168.0.5:8765');
    expect(Pairing.parse('http://192.168.0.5:8765/app'), isNull, reason: '열쇠 없는 주소로 짝지었다');
    expect(Pairing.parse('VC 아님'), isNull);
    expect(Pairing.parse('ftp://x/app#t=1'), isNull);
    expect(Pairing.parse('http://x/app#t=%E0%A4%A'), isNull, reason: '깨진 열쇠에 터졌다');
  });

  test('찾기 · 펼치기 · 적기 — 열쇠는 머리에, 새 글 201 도 성공', () async {
    final seen = <http.Request>[];
    final api = _api((req) async {
      seen.add(req);
      switch (req.url.path) {
        case '/eb/v1/hello':
          return _json({'store': {'notes': 2794}});
        case '/eb/v1/memory/search':
          return _json({'results': [{'title': '폰메모', 'summary': '주차 B2'}]});
        case '/eb/v1/memory/note':
          return _json({'title': '폰메모', 'text': '주차 B2 기둥 17'});
        case '/eb/v1/memory':
          return _json({'title': '폰메모', 'mode': 'append'}, 201);
      }
      return _json({'error': 'not found'}, 404);
    });
    expect(await api.notes(), 2794);
    expect((await api.search('주차')).single['title'], '폰메모');
    expect(seen.last.url.queryParameters['q'], '주차');
    expect(seen.last.headers['Authorization'], 'Bearer tok');
    expect(seen.last.url.fragment, isEmpty, reason: '열쇠를 주소에 실었다');
    expect((await api.note('폰메모', q: '주차'))['text'], contains('B2'));
    expect(await api.write('폰메모', '출구 3번'), '폰메모');
    expect(jsonDecode(seen.last.body), {'title': '폰메모', 'text': '출구 3번'});
    expect(seen.last.method, 'POST');
  });

  test('401 은 짝 풀기 · 못 닿으면 offline · 거절은 서버 말 그대로', () async {
    expect(_api((_) async => _json({'error': 'unauthorized'}, 401)).notes(), throwsA(isA<VcUnauthorized>()));
    expect(_api((_) async => throw http.ClientException('끊김')).search(''), throwsA(isA<VcOffline>()));
    await expectLater(
      _api((_) async => _json({'error': 'title and text required'}, 400)).write('', ''),
      throwsA(isA<VcError>().having((e) => e.message, 'message', 'title and text required')),
    );
  });

  testWidgets('못 닿아 못 적으면 적은 글이 칸에 남는다', (tester) async {
    Object? failed;
    final api = _api((_) async => throw http.ClientException('끊김'));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: WriteTab(api: api, onFail: (e) => failed = e))));
    await tester.enterText(find.byType(TextField).last, '잃으면 안 되는 글');
    await tester.tap(find.text('PC 에 적기'));
    await tester.pumpAndSettle();
    expect(find.text('잃으면 안 되는 글'), findsOneWidget);
    expect(find.textContaining('못 닿아서'), findsOneWidget);
    expect(failed, isNull, reason: '못 닿은 것은 짝 풀기로 넘기지 않는다');
  });
}
