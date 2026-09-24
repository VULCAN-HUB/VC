import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/vc_api.dart';

VcApi _api(MockClientHandler h) => VcApi(Pairing.parse('http://192.168.0.5:8765/app#t=tok')!, client: MockClient(h));

http.Response _json(Object body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

void main() {
  late Directory dir;
  late File file;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('vc_outbox');
    file = File('${dir.path}/vc_outbox.json');
  });
  tearDown(() => dir.deleteSync(recursive: true));

  test('폰에 저장한 글은 앱을 다시 켜도 남는다 · 처음은 「폰에 저장됨」', () async {
    final a = await Outbox.open(file);
    final it = await a.add('장보기', '우유 2');
    expect(it.state.label, '폰에 저장됨');
    final b = await Outbox.open(file); // 앱을 완전히 껐다 켠 것
    expect(b.items.single.id, it.id);
    expect(b.items.single.text, '우유 2');
    expect(b.pending, 1);
  });

  test('못 닿으면 「전송 대기」로 남고, 다시 켜도 그대로다', () async {
    final a = await Outbox.open(file);
    await a.add('메모', '맥 꺼짐');
    expect(await a.flush(_api((_) async => throw http.ClientException('끊김'))), FlushResult.offline);
    final b = await Outbox.open(file);
    expect(b.items.single.state.label, '전송 대기');
    expect(b.pending, 1);
  });

  test('서버엔 써졌는데 응답이 끊겨도 — 다시 보내면 같은 id 라 한 번만 저장된다', () async {
    final written = <String, String>{}; // client_id → text (가짜 서버의 창고)
    final sentIds = <String>[];
    var dropReply = true;
    Future<http.Response> server(http.Request req) async {
      final j = jsonDecode(req.body) as Map<String, dynamic>;
      final id = j['client_id'] as String;
      sentIds.add(id);
      final dup = written.containsKey(id);
      written.putIfAbsent(id, () => j['text'] as String);
      if (dropReply) {
        dropReply = false;
        throw http.ClientException('응답 유실'); // 서버엔 저장됐다
      }
      return _json({'title': j['title'], 'duplicate': dup}, dup ? 200 : 201);
    }

    final a = await Outbox.open(file);
    await a.add('회의', '결론 A');
    expect(await a.flush(_api(server)), FlushResult.offline);
    expect(a.items.single.state.label, '전송 대기');
    final b = await Outbox.open(file); // 그 사이 앱도 다시 켰다
    expect(await b.flush(_api(server)), FlushResult.done);
    expect(b.items.single.state.label, '서버 저장 완료');
    expect(sentIds.length, 2);
    expect(sentIds.toSet().length, 1, reason: '다시 보낼 때 id 가 바뀌면 서버가 중복을 못 가른다');
    expect(written.length, 1);
    expect((await Outbox.open(file)).pending, 0, reason: '보낸 표시가 파일에 안 남았다');
  });

  test('열쇠가 틀리면 글은 안 지우고 멈춘다 · 서버가 거절하면 까닭을 남기고 둔다', () async {
    final a = await Outbox.open(file);
    await a.add('글', '본문');
    expect(await a.flush(_api((_) async => _json({'error': 'unauthorized'}, 401))), FlushResult.unauthorized);
    expect(a.pending, 1);
    await a.flush(_api((_) async => _json({'error': 'client_id 는 영문·숫자·-_ 8~80자다'}, 400)));
    expect(a.items.single.sent, isFalse);
    expect(a.items.single.error, contains('client_id'));
  });

  test('보내면 알린다 — 보기 목록이 다시 불러올 수 있게', () async {
    final a = await Outbox.open(file);
    await a.add('글', '본문');
    var told = 0;
    a.addListener(() => told++);
    await a.flush(_api((_) async => _json({'title': '글'}, 201)));
    expect(a.items.single.sent, isTrue);
    expect(told, greaterThan(0), reason: '보낸 뒤 알리지 않으면 보기 목록이 옛것으로 남는다');
  });

  test('대기함 파일이 깨졌으면 지우지 않고 옆에 치운다', () async {
    file.writeAsStringSync('{깨짐');
    final a = await Outbox.open(file);
    expect(a.items, isEmpty);
    expect(dir.listSync().any((f) => f.path.contains('.broken-')), isTrue, reason: '깨진 대기함을 지웠다 — 안 보낸 글이 있었을 수 있다');
  });

  test('보낸 것은 최근 것만 남기고, 안 보낸 것은 다 남긴다', () async {
    final a = await Outbox.open(file);
    for (var i = 0; i < Outbox.keepSent + 5; i++) {
      await a.add('글$i', '본문$i');
    }
    await a.add('안 보냄', '남아야 한다');
    var n = 0;
    await a.flush(_api((req) async {
      n++;
      if (n > Outbox.keepSent + 5) throw http.ClientException('끊김');
      return _json({'title': 't'}, 201);
    }));
    final b = await Outbox.open(file);
    expect(b.pending, 1);
    expect(b.items.where((i) => i.sent).length, Outbox.keepSent);
  });
}
