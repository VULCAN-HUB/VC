import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/vc_api.dart';

// ★ 못 닿은 까닭을 가른다. 전에는 무슨 오류든 「못 닿았어」 한 문구라,
//   폰이 다른 와이파이였는지 · VC 가 꺼졌는지 · 느린지를 가를 수 없었다(2026-09-15 아이폰 실기).
VcApi _api(MockClientHandler h, {Duration timeout = const Duration(seconds: 10)}) =>
    VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient(h), timeout: timeout);

Future<String> _why(VcApi api) async {
  try {
    await api.notes();
  } on VcOffline catch (e) {
    return e.reason;
  }
  return '(닿았다)';
}

void main() {
  test('연결 거절이면 「VC 가 꺼져 있다」', () async {
    expect(await _why(_api((_) async => throw http.ClientException('Connection refused'))), 'VC 가 꺼져 있다');
  });

  test('경로가 없으면 「망이 달라 닿지 않는다」', () async {
    expect(await _why(_api((_) async => throw http.ClientException('No route to host'))), '망이 달라 닿지 않는다');
  });

  test('시간이 넘으면 「시간 초과」', () async {
    final slow = _api((_) => Completer<http.Response>().future, timeout: const Duration(milliseconds: 20));
    expect(await _why(slow), '시간 초과');
  });

  test('모르는 오류는 빈 까닭 — 지어내지 않는다', () async {
    expect(offlineReason(Exception('뭔지 모름')), '');
  });
}
