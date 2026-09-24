// 공유 시트로 들어온 것 받기 (오너 결정 29 · 편의 기능 11번).
//
// 아이폰 공유 확장(`ios/Share/`)은 **망을 안 탄다** — 받은 글·주소·사진을 앱 그룹 자리
// `공유함/` 에 파일로 떨어뜨리고 닫는다(열쇠를 확장에 안 주고, 확장이 죽어도 안 잃는다).
// 여기서는 앱이 켜질 때 그 자리를 훑어 **대기함(Outbox)** 으로 옮긴다 — 그다음은 늘 가던 길이다.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

import 'cache.dart';
import 'outbox.dart';

const _channel = MethodChannel('vc/share');

/// 공유함에서 꺼낸 한 덩이.
class SharedItem {
  const SharedItem({required this.id, required this.title, required this.text, required this.files});

  final String id;
  final String title;
  final String text;
  final List<File> files;

  static SharedItem? fromJson(Map<String, dynamic> j, Directory dir) {
    final id = '${j['id'] ?? ''}';
    if (id.isEmpty) return null;
    final files = [
      for (final n in (j['files'] as List?)?.whereType<String>() ?? const <String>[])
        if (File('${dir.path}/$n').existsSync()) File('${dir.path}/$n'),
    ];
    final text = '${j['text'] ?? ''}'.trim();
    if (text.isEmpty && files.isEmpty) return null; // 빈 것은 안 만든다
    return SharedItem(id: id, title: '${j['title'] ?? ''}'.trim(), text: text, files: files);
  }
}

/// 화면이 쓰는 문. 시험에서는 가짜로 갈아 낀다.
abstract class SharedInboxLike {
  Future<int> drain(Outbox outbox, {Cache? cache});
}

/// 공유 시트가 없는 자리(안드로이드·시험 기본) — 아무 일도 안 한다.
class SharedInboxNone implements SharedInboxLike {
  const SharedInboxNone();

  @override
  Future<int> drain(Outbox outbox, {Cache? cache}) async => 0;
}

/// 앱 그룹 안 `공유함/` 을 읽고 비운다. 아이폰이 아니면 빈 목록.
class SharedInbox implements SharedInboxLike {
  SharedInbox({Future<String?> Function()? where}) : _where = where ?? _askIos;

  final Future<String?> Function() _where;

  static Future<String?> _askIos() async {
    try {
      return await _channel.invokeMethod<String>('dir');
    } on PlatformException {
      return null; // 앱 그룹 권한이 없다
    } on MissingPluginException {
      return null; // 안드로이드·시험
    }
  }

  /// 들어온 것들. 읽은 쪽지(json)는 지우고, **사진은 남긴다** — 대기함이 보낼 때까지 그 파일을 쓴다.
  Future<List<SharedItem>> take() async {
    final path = await _where();
    if (path == null) return const [];
    final dir = Directory(path);
    if (!await dir.exists()) return const [];
    final out = <SharedItem>[];
    for (final f in dir.listSync().whereType<File>()) {
      if (!f.path.endsWith('.json')) continue;
      try {
        final j = jsonDecode(await f.readAsString());
        if (j is Map<String, dynamic>) {
          final got = SharedItem.fromJson(j, dir);
          if (got != null) out.add(got);
        }
        await f.delete(); // 한 번 꺼낸 쪽지는 다시 안 꺼낸다
      } on FormatException {
        await f.delete(); // 깨진 쪽지는 버린다 — 매번 걸리면 안 된다
      } on FileSystemException {
        // 그 사이 사라졌다
      }
    }
    return out;
  }

  /// 들어온 것을 대기함에 넣고, 폰 창고에도 바로 남긴다(컴퓨터가 꺼져 있어도 보이게).
  ///
  /// 제목이 없으면 **본문 첫 줄**을 제목으로 쓴다 — 서버 기본(비면 오늘 날짜)보다 찾기 쉽다.
  @override
  Future<int> drain(Outbox outbox, {Cache? cache}) async {
    final items = await take();
    for (final s in items) {
      final title = s.title.isNotEmpty
          ? s.title
          : (s.text.split('\n').firstWhere((l) => l.trim().isNotEmpty, orElse: () => '').trim());
      final body = s.files.isEmpty ? s.text : '${s.text}\n\n${s.files.map((f) => '![[${_name(f)}]]').join('\n')}';
      await outbox.add(title.length > 40 ? title.substring(0, 40) : title, s.text, files: s.files);
      await cache?.addMine(title.isEmpty ? '(제목 없음)' : title, body);
    }
    return items.length;
  }

  static String _name(File f) => f.path.split('/').last;
}
