import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vc_app/cache.dart';
import 'package:vc_app/outbox.dart';
import 'package:vc_app/shared_inbox.dart';

// 공유 시트로 들어온 것(결정 29 · 편의 기능 11번) — 확장은 파일만 떨어뜨리고, 앱이 대기함으로 옮긴다.
void main() {
  late Directory dir;
  late Directory inbox;
  late Outbox outbox;
  late Cache cache;

  setUp(() async {
    dir = Directory.systemTemp.createTempSync('vc_share');
    inbox = Directory('${dir.path}/공유함')..createSync();
    outbox = await Outbox.open(File('${dir.path}/vc_outbox.json'));
    cache = Cache(Directory('${dir.path}/cache'));
  });
  tearDown(() => dir.deleteSync(recursive: true));

  SharedInbox box() => SharedInbox(where: () async => inbox.path);

  void note(String id, Map<String, dynamic> j) => File('${inbox.path}/$id.json').writeAsStringSync(jsonEncode(j));

  test('글 하나가 대기함으로 옮겨지고, 쪽지는 사라진다', () async {
    note('a', {'id': 'share-a', 'title': '사파리에서', 'text': 'https://example.com/기사', 'files': []});

    expect(await box().drain(outbox, cache: cache), 1);
    expect(outbox.items.single.title, '사파리에서');
    expect(outbox.items.single.text, contains('example.com'));
    expect(
      inbox.listSync().whereType<File>().where((f) => f.path.endsWith('.json')),
      isEmpty,
      reason: '꺼낸 쪽지가 남아 다음에 또 들어온다',
    );

    // 두 번째로 훑을 때는 아무것도 없다 — 같은 것이 두 번 안 들어간다
    expect(await box().drain(outbox, cache: cache), 0);
    expect(outbox.items.length, 1);
  });

  test('제목이 없으면 본문 첫 줄이 제목이 된다', () async {
    note('b', {'id': 'share-b', 'title': '', 'text': '이것부터 보기\n그리고 나머지', 'files': []});
    await box().drain(outbox, cache: cache);
    expect(outbox.items.single.title, '이것부터 보기');
  });

  test('사진은 대기함에 첨부로 붙고, 그 파일은 안 지운다', () async {
    File('${inbox.path}/공유 1.jpg').writeAsBytesSync(List.filled(20, 7));
    note('c', {
      'id': 'share-c',
      'title': '사진',
      'text': '',
      'files': ['공유 1.jpg'],
    });

    expect(await box().drain(outbox, cache: cache), 1);
    expect(outbox.items.single.files.single.name, '공유 1.jpg');
    expect(File('${inbox.path}/공유 1.jpg').existsSync(), isTrue, reason: '보내기도 전에 사진을 지웠다');
  });

  test('폰 창고에도 바로 들어간다 — 컴퓨터가 꺼져 있어도 보인다', () async {
    note('d', {'id': 'share-d', 'title': '메모', 'text': '적어 둘 것', 'files': []});
    await box().drain(outbox, cache: cache);
    expect('${(await cache.note('메모'))!['text']}', contains('적어 둘 것'));
    expect((await cache.list()).first['title'], '메모');
  });

  test('빈 쪽지·깨진 쪽지는 버리고 앱은 멀쩡하다', () async {
    note('e', {'id': 'share-e', 'title': '', 'text': '   ', 'files': []});
    File('${inbox.path}/f.json').writeAsStringSync('{깨졌다');

    expect(await box().drain(outbox, cache: cache), 0);
    expect(outbox.items, isEmpty);
    expect(inbox.listSync().whereType<File>().where((f) => f.path.endsWith('.json')), isEmpty);
  });

  test('공유 시트가 없는 자리(안드로이드·시험)에서는 아무 일도 안 한다', () async {
    expect(await const SharedInboxNone().drain(outbox), 0);
    expect(await SharedInbox(where: () async => null).drain(outbox), 0);
  });
}
