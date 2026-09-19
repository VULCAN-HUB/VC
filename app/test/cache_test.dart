import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vc_app/cache.dart';

// 폰 안 작은 창고(오너 결정 27) — 컴퓨터가 꺼져도 지난번에 본 것이 남고, 사진은 두 번 안 받는다.
void main() {
  late Directory dir;
  late Cache cache;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('vc_cache');
    cache = Cache(dir, limitBytes: 1000);
  });
  tearDown(() => dir.deleteSync(recursive: true));

  test('목록과 글이 남아 컴퓨터가 꺼져도 읽힌다', () async {
    await cache.saveList([
      {'title': '장 볼 것', 'preview': '우유'},
    ]);
    await cache.saveNote('장 볼 것', {'title': '장 볼 것', 'body': '- [ ] 우유'});

    final again = Cache(dir);
    expect((await again.list()).first['title'], '장 볼 것');
    expect((await again.note('장 볼 것'))!['body'], '- [ ] 우유');
    expect(await again.listWhen(), isNotNull, reason: '언제 본 것인지 모르면 「지난번에 본 것」이라 못 쓴다');
  });

  test('제목에 / 나 : 가 있어도 남는다', () async {
    await cache.saveNote('2026/09/메모: 하나', {'body': '괜찮다'});
    expect((await cache.note('2026/09/메모: 하나'))!['body'], '괜찮다');
  });

  test('없는 것을 물으면 null · 깨진 파일도 앱을 안 죽인다', () async {
    expect(await cache.note('본 적 없는 글'), isNull);
    expect(await cache.list(), isEmpty);
    await Directory('${dir.path}/notes').create(recursive: true);
    await File('${dir.path}/notes/${Cache.key('깨진 글')}.json').writeAsString('{깨졌다');
    expect(await cache.note('깨진 글'), isNull);
  });

  test('받은 사진은 파일로 남아 두 번 안 받는다 · 작은 사진은 따로 둔다', () async {
    expect(await cache.attach('사진.jpg'), isNull);
    await cache.putAttach('사진.jpg', List.filled(50, 7));
    expect(await cache.attach('사진.jpg'), isNotNull, reason: '받아 뒀는데 또 받으라고 한다');
    expect(await cache.attach('사진.jpg', width: 320), isNull, reason: '작은 사진과 원본을 같은 것으로 본다');
    await cache.putAttach('사진.jpg', List.filled(10, 1), width: 320);
    expect(await (await cache.attach('사진.jpg', width: 320))!.length(), 10);
    expect(await (await cache.attach('사진.jpg'))!.length(), 50, reason: '작은 사진이 원본을 덮었다');
  });

  test('폰에서 올린 사진은 받지 않고 그대로 넣는다', () async {
    final shot = File('${dir.path}/찍은것.jpg')..writeAsBytesSync(List.filled(30, 9));
    await cache.adoptUpload('붙임 2026-09-18.jpg', shot);
    expect(await cache.attach('붙임 2026-09-18.jpg'), isNotNull, reason: '방금 올린 사진을 되받아야 한다');
  });

  test('상한을 넘으면 오래 안 본 것부터 지운다 — 글은 안 지운다', () async {
    await cache.saveNote('남을 글', {'body': '글자는 싸다'});
    await cache.putAttach('옛날.jpg', List.filled(600, 1));
    await Future<void>.delayed(const Duration(milliseconds: 1100)); // 손댄 때가 갈리게
    await cache.putAttach('요즘.jpg', List.filled(600, 2));

    expect(await cache.bytes(), lessThanOrEqualTo(1000), reason: '상한을 넘겼는데 안 지운다');
    expect(await cache.attach('요즘.jpg'), isNotNull, reason: '방금 본 것을 지웠다');
    expect(await cache.attach('옛날.jpg'), isNull, reason: '오래된 것이 안 지워졌다');
    expect(await cache.note('남을 글'), isNotNull, reason: '사진 치우다 글까지 지웠다');
  });

  test('「지금 비우기」는 사진만 지운다', () async {
    await cache.saveNote('남을 글', {'body': '읽어야 한다'});
    await cache.putAttach('사진.jpg', List.filled(10, 1));
    await cache.clearAttachments();
    expect(await cache.attach('사진.jpg'), isNull);
    expect(await cache.note('남을 글'), isNotNull, reason: '사진을 비웠는데 오프라인에서 읽을 글까지 사라졌다');
    expect(await cache.bytes(), 0);
  });
}
