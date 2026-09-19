import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vc_app/attach.dart';
import 'package:vc_app/cache.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/vc_api.dart';

// 오너 지시 2026-09-18(결정 27): 「pc 가 오프라인이더라도 전에 연결되었을 때 혹은 폰으로 작성한 것은
// 폰에서 볼 수 있게. 단 모든 이미지가 매번 pc 연결될 때마다 폰에 다운받으면 안 된다.」
//
// ※ 폰 창고는 **진짜 파일**을 쓴다. flutter_test 의 가짜 시간 속에서는 위젯 안에서 시작한 파일 일이
//   끝나지 않으므로, 캐시는 `runAsync` 로 미리 채워 두고 **화면이 그것을 쓰는지**를 본다.
void main() {
  late Directory dir;
  late Cache cache;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('vc_offline');
    cache = Cache(dir);
  });
  tearDown(() => dir.deleteSync(recursive: true));

  VcApi offline() => VcApi(
    Pairing.parse('http://100.1.2.3:8765/app#t=tok')!,
    client: MockClient((_) async => throw http.ClientException('Connection refused')),
  );

  /// 진짜 파일 읽기·쓰기가 끝날 짬을 주고 다시 그린다. 한 번으로는 모자라다 —
  /// 폰 창고를 읽는 길이 여러 번 기다린다(목록 → 언제 본 것인지 → 다시 그리기) — 넉넉히 돈다.
  Future<void> settle(WidgetTester tester) async {
    for (var i = 0; i < 12; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 60)));
      await tester.pump();
    }
  }

  testWidgets('컴퓨터가 꺼져 있어도 지난번에 본 목록이 보인다', (tester) async {
    await tester.runAsync(() async {
      await cache.saveList([
        {'title': '정수기 받음', 'preview': '종류: 정수기', 'updated': '2026-09-18'},
      ]);
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: BrowseTab(api: offline(), cache: cache, onFail: (_) {}),
        ),
      ),
    );
    await settle(tester);

    expect(find.text('정수기 받음'), findsOneWidget, reason: '컴퓨터가 꺼지자 폰이 빈 화면이 됐다');
    expect(find.textContaining('컴퓨터 꺼짐'), findsOneWidget, reason: '지금 보는 것이 언제 것인지 안 말해 준다');
    expect(find.textContaining('1장 · 폰에 남은 것'), findsOneWidget);
  });

  testWidgets('폰에 아무것도 없으면 그렇다고 말한다 — 창고가 빈 것처럼 말하지 않는다', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: BrowseTab(api: offline(), cache: cache, onFail: (_) {}),
        ),
      ),
    );
    await settle(tester);

    expect(find.textContaining('컴퓨터에 못 닿았고, 폰에 남은 것도 없어'), findsOneWidget);
  });

  testWidgets('컴퓨터가 꺼져 있어도 지난번에 연 글이 읽힌다', (tester) async {
    await tester.runAsync(() async {
      await cache.saveNote('정수기 받음', {'title': '정수기 받음', 'text': '- 종류 : 정수기\n- 받은날 : 2026-10-01'});
    });

    await tester.pumpWidget(
      MaterialApp(
        home: NotePage(api: offline(), title: '정수기 받음', cache: cache, onFail: (_) {}),
      ),
    );
    await settle(tester);

    expect(find.textContaining('정수기'), findsWidgets, reason: '지난번에 본 글이 안 나온다');
    expect(find.textContaining('폰에 남아 있던 판'), findsOneWidget, reason: '지금 보는 것이 옛 판임을 안 말해 준다');
  });

  test('폰에서 쓴 글은 보내기 전에도 폰에서 읽힌다 · 덧붙이면 앞의 것이 안 사라진다', () async {
    await cache.addMine('장 볼 것', '- [ ] 우유');
    expect((await cache.list()).first['title'], '장 볼 것');
    expect('${(await cache.note('장 볼 것'))!['text']}', contains('우유'));

    await cache.addMine('장 볼 것', '- [ ] 필터');
    final body = '${(await cache.note('장 볼 것'))!['text']}';
    expect(body, contains('우유'), reason: '이어 쓰기가 앞의 것을 덮었다');
    expect(body, contains('필터'));
    expect((await cache.list()).where((c) => c['title'] == '장 볼 것').length, 1, reason: '같은 글이 목록에 두 번 뜬다');
  });

  testWidgets('폰에 있는 사진은 다시 안 받는다', (tester) async {
    var fetched = 0;
    final api = VcApi(
      Pairing.parse('http://100.1.2.3:8765/app#t=tok')!,
      client: MockClient((_) async {
        fetched++;
        return http.Response.bytes(List.filled(40, 3), 200, headers: {'content-type': 'image/jpeg'});
      }),
    );
    await tester.runAsync(() => cache.putAttach('정수기.jpg', List.filled(40, 3), width: 320));

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AttachImage(api: api, name: '정수기.jpg', cache: cache, width: 320),
        ),
      ),
    );
    await settle(tester);

    expect(fetched, 0, reason: '폰에 있는 사진을 또 받았다 — 연결될 때마다 다시 받으면 안 된다');
  });

  testWidgets('폰에 없으면 한 번 받되, 목록 카드는 작은 사진만 받는다', (tester) async {
    var asked = <String, String>{};
    var fetched = 0;
    final api = VcApi(
      Pairing.parse('http://100.1.2.3:8765/app#t=tok')!,
      client: MockClient((req) async {
        fetched++;
        asked = req.url.queryParameters;
        return http.Response.bytes(List.filled(40, 3), 200, headers: {'content-type': 'image/jpeg'});
      }),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AttachImage(api: api, name: '정수기.jpg', cache: cache, width: 320),
        ),
      ),
    );
    await settle(tester);

    expect(fetched, 1);
    expect(asked['w'], '320', reason: '목록 카드가 원본을 통째로 받는다');
    expect(asked['name'], '정수기.jpg');
  });

  testWidgets('컴퓨터가 꺼졌고 폰에도 없으면 빈칸 대신 까닭을 보인다', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AttachImage(api: offline(), name: '없던사진.jpg', cache: cache),
        ),
      ),
    );
    await settle(tester);

    expect(find.textContaining('컴퓨터가 켜지면 보임'), findsOneWidget);
  });
}
