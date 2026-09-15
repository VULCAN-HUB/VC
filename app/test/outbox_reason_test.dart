import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/vc_api.dart';

// ★ 대기함을 보내다 못 닿으면 까닭을 들고 있어야 한다. 전에는 여기서 버려,
//   VC 를 끄고 보냈을 때 폰 알림 줄에 「컴퓨터에 못 닿았어」만 떴다(2026-09-15 아이폰 실기).
void main() {
  test('대기함이 못 닿은 까닭을 들고 있다', () async {
    final dir = await Directory.systemTemp.createTemp('vc_reason');
    addTearDown(() => dir.delete(recursive: true));
    final box = await Outbox.open(File('${dir.path}/vc_outbox.json'));
    await box.add('제목', '본문');
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!,
        client: MockClient((_) async => throw http.ClientException('Connection refused')));
    expect(await box.flush(api), FlushResult.offline);
    expect(box.offlineReason, 'VC 가 꺼져 있다');
    expect(box.pending, 1);
  });
}
