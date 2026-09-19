import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/vc_api.dart';

// 첫 연결(결정 18·21) — 막히면 **무엇을 고쳐야 하는지** 말해야 한다.
// 전에는 QR 이 아니든 · 열쇠가 없든 · 글자가 깨졌든 「VC 설정 → 폰 연결의 QR 이 아니야」 한 마디였다.
void main() {
  test('제대로 된 QR 은 주소와 열쇠로 갈린다', () {
    final (p, why) = Pairing.parseOrWhy('http://100.101.2.3:8765/app#t=abc%20def');
    expect(why, '');
    expect(p!.label, '100.101.2.3:8765');
    expect(p.token, 'abc def');
    expect(p.viaTailscale, isTrue, reason: '100.x 는 테일스케일 주소다');
  });

  test('포트를 안 적어도 8765 로 본다 · 집 주소는 테일스케일이 아니다', () {
    final (p, _) = Pairing.parseOrWhy('http://192.168.0.10/app#t=k');
    expect(p!.label, '192.168.0.10:8765');
    expect(p.viaTailscale, isFalse);
  });

  test('안 되는 까닭이 저마다 다르게 나온다', () {
    expect(Pairing.parseOrWhy('').$2, contains('안 적혔어'));
    expect(Pairing.parseOrWhy('그냥 글자').$2, contains('QR 이 아니야'));
    expect(Pairing.parseOrWhy('http://100.101.2.3:8765/app').$2, contains('열쇠가 없는'));
    expect(Pairing.parseOrWhy('http://100.101.2.3:8765/app#t=').$2, contains('열쇠가 비었어'));
    // 이상한 %인코딩은 Uri 가 글자 그대로로 바꾼다 — 터지지 않고 그 열쇠로 붙어 본다(아니면 401 이 온다)
    expect(Pairing.parseOrWhy('http://100.101.2.3:8765/app#t=%zz').$1, isNotNull);
    // 까닭은 저마다 달라야 한다 — 같은 말이면 고칠 것을 모른다
    final whys = [
      Pairing.parseOrWhy('').$2,
      Pairing.parseOrWhy('그냥 글자').$2,
      Pairing.parseOrWhy('http://100.101.2.3:8765/app').$2,
      Pairing.parseOrWhy('http://100.101.2.3:8765/app#t=').$2,
    ];
    expect(whys.toSet().length, whys.length, reason: '까닭이 뭉뚱그려져 있다');
  });

  test('짝짓기 전에 한 번 불러 본다 — 열쇠가 틀리면 401, 컴퓨터가 꺼졌으면 까닭', () async {
    final (p, _) = Pairing.parseOrWhy('http://100.101.2.3:8765/app#t=k');

    final badKey = VcApi(p!, client: MockClient((_) async => http.Response('{}', 401)));
    await expectLater(badKey.notes(), throwsA(isA<VcUnauthorized>()));

    final off = VcApi(p, client: MockClient((_) async => throw http.ClientException('Connection refused')));
    await expectLater(off.notes(), throwsA(isA<VcOffline>().having((e) => e.reason, '까닭', 'VC 가 꺼져 있다')));

    final ok = VcApi(
      p,
      client: MockClient(
        (_) async => http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'store': {'notes': 12},
            }),
          ),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    expect(await ok.notes(), 12);
  });

  test('망이 달라 못 닿는 것과 VC 가 꺼진 것을 가른다', () {
    expect(offlineReason(http.ClientException('No route to host')), '망이 달라 닿지 않는다');
    expect(offlineReason(http.ClientException('Connection refused')), 'VC 가 꺼져 있다');
    expect(offlineReason(http.ClientException('Failed host lookup: vc.ts.net')), '망이 달라 닿지 않는다');
  });
}
