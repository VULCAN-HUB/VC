import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/vc_api.dart';

// 4단계 — 사진을 붙인 글도 **폰에 먼저** 남고, 연결되면 사진부터 올린 뒤 받은 이름으로 글을 쓴다.
http.Response _json(Object body, int status) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

void main() {
  test('사진은 폰에 복사해 두고, 올린 이름으로 글을 쓰고, 보낸 뒤 사본을 지운다', () async {
    final dir = await Directory.systemTemp.createTemp('vc_attach');
    addTearDown(() => dir.delete(recursive: true));
    final album = await Directory('${dir.path}/album').create();
    final pic = File('${album.path}/IMG_0001.HEIC')..writeAsBytesSync([1, 2, 3]);

    final boxFile = File('${dir.path}/vc_outbox.json');
    final box = await Outbox.open(boxFile);
    final item = await box.add('받은 제품', '정수기', files: [pic]);
    await pic.delete(); // 사진첩 원본이 사라져도 보낼 수 있어야 한다

    // 앱을 껐다 켜도 첨부 목록이 남는다
    final again = await Outbox.open(boxFile);
    expect(again.items.single.files.single.name, 'IMG_0001.HEIC');

    var online = false;
    final ids = <String>[];
    String? wrote;
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!, client: MockClient((req) async {
      if (!online) throw http.ClientException('Connection refused');
      if (req.url.path == '/eb/v1/attach') {
        ids.add(req.url.queryParameters['client_id']!);
        expect(req.bodyBytes, [1, 2, 3]);
        return _json({'name': '받은 제품.heic'}, 201);
      }
      wrote = (jsonDecode(req.body) as Map)['text'] as String;
      return _json({'title': '받은 제품'}, 201);
    }));

    expect(await box.flush(api), FlushResult.offline);
    expect(box.pending, 1);

    online = true;
    expect(await box.flush(api), FlushResult.done);
    expect(ids, ['${item.id}-f0']);
    expect(wrote, contains('정수기'));
    expect(wrote, contains('![[받은 제품.heic]]'), reason: '올린 사진을 글이 안 가리킨다');
    expect(File(item.files.single.path).existsSync(), isFalse, reason: '보낸 뒤 폰 사본이 남는다');
  });
}
