// 전송 대기함 — 폰에서 쓴 새 글을 **먼저 폰에 저장**하고, PC·맥에 닿으면 보낸다.
//
// 첫 판 범위(오너 2026-09-14): 새 글 작성만. 양쪽에서 같은 글을 고치는 동기화(충돌 처리)는 다음 단계.
// 보내기는 앱을 열었을 때 · 앞으로 돌아왔을 때 · 쓰고 난 직후 · 「지금 보내기」.
//
// ★ 막이:
// - 글마다 `id`(client_id)가 하나다. 서버는 같은 id 를 한 번만 받는다 — 서버엔 써졌는데 응답이 끊겨 다시 보내도 안 겹친다.
// - 파일은 **임시 파일에 쓰고 이름을 바꿔** 갈아 끼운다. 쓰다 꺼져도 옛 파일이 온전하다.
// - 보냈다고 서버가 답한 뒤에만 「서버 저장 완료」. 그 전에는 지우지 않는다.

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';

import 'vc_api.dart';

enum SendState { saved, waiting, sent }

extension SendStateLabel on SendState {
  String get label => switch (this) {
        SendState.saved => '폰에 저장됨',
        SendState.waiting => '전송 대기',
        SendState.sent => '서버 저장 완료',
      };
}

/// 글에 딸린 사진·영상·녹음 하나(4단계). 폰 안 대기함 자리에 복사해 둔 사본을 가리킨다.
class OutboxFile {
  OutboxFile({required this.path, required this.name, this.uploaded});

  final String path; // 폰 안 사본
  final String name; // 원래 이름 — 꼴(.heic·.mov)을 서버가 이걸로 가린다
  String? uploaded; // 서버가 준 이름. 있으면 다시 안 올린다

  Map<String, dynamic> toJson() => {'path': path, 'name': name, 'uploaded': ?uploaded};

  static OutboxFile? fromJson(Object? j) {
    if (j is! Map) return null;
    final p = j['path'], n = j['name'];
    if (p is! String || n is! String) return null;
    return OutboxFile(path: p, name: n, uploaded: j['uploaded'] as String?);
  }
}

class OutboxItem {
  OutboxItem({
    required this.id,
    required this.title,
    required this.text,
    required this.created,
    this.attempts = 0,
    this.sent = false,
    this.savedAs,
    this.error,
    List<OutboxFile>? files,
  }) : files = files ?? [];

  final String id;
  final String title;
  final String text;
  final int created; // 밀리초
  int attempts;
  bool sent;
  String? savedAs;
  String? error;
  final List<OutboxFile> files;

  SendState get state => sent ? SendState.sent : (attempts == 0 ? SendState.saved : SendState.waiting);

  /// 보낼 몸 — 올린 첨부를 `![[이름]]` 으로 뒤에 붙인다.
  String get bodyToSend => [
        text,
        for (final f in files)
          if (f.uploaded != null) '![[${f.uploaded}]]',
      ].where((s) => s.trim().isNotEmpty).join('\n\n');

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'text': text,
        'created': created,
        'attempts': attempts,
        'sent': sent,
        'savedAs': ?savedAs,
        'error': ?error,
        if (files.isNotEmpty) 'files': files.map((f) => f.toJson()).toList(),
      };

  static OutboxItem? fromJson(Object? j) {
    if (j is! Map) return null;
    final id = j['id'], title = j['title'], text = j['text'], created = j['created'];
    if (id is! String || title is! String || text is! String || created is! int) return null;
    return OutboxItem(
      id: id,
      title: title,
      text: text,
      created: created,
      attempts: j['attempts'] is int ? j['attempts'] as int : 0,
      sent: j['sent'] == true,
      savedAs: j['savedAs'] as String?,
      error: j['error'] as String?,
      files: j['files'] is List
          ? (j['files'] as List).map(OutboxFile.fromJson).whereType<OutboxFile>().toList()
          : null,
    );
  }
}

/// 보내기 한 바퀴의 결과.
enum FlushResult { done, offline, unauthorized }

class Outbox extends ChangeNotifier {
  Outbox._(this.file, this.items);

  final File file;
  final List<OutboxItem> items; // 새것이 앞
  bool _flushing = false;

  /// 마지막으로 못 닿았을 때의 까닭(`VcOffline.reason`). 모르면 빈 글.
  /// ★ 전에는 여기서 까닭을 버려, 폰 알림 줄이 「못 닿았어」만 보였다(2026-09-15 아이폰 실기).
  String offlineReason = '';

  /// 보낸 것은 최근 이만큼만 남긴다(안 보낸 것은 몇 개든 다 남긴다).
  static const keepSent = 30;

  static Future<Outbox> open(File file) async {
    final items = <OutboxItem>[];
    try {
      final j = jsonDecode(await file.readAsString());
      if (j is List) items.addAll(j.map(OutboxItem.fromJson).whereType<OutboxItem>());
    } on FileSystemException {
      // 처음 켰다 — 빈 대기함
    } on FormatException {
      // ★ 깨졌으면 지우지 않고 옆에 치운다 — 안 보낸 글이 들어 있을 수 있다
      try {
        await file.rename('${file.path}.broken-${DateTime.now().millisecondsSinceEpoch}');
      } on FileSystemException {
        // 못 치워도 켜져야 한다
      }
    }
    return Outbox._(file, items);
  }

  int get pending => items.where((i) => !i.sent).length;

  static String newId() {
    final r = Random.secure();
    return List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }

  Future<void> _save() async {
    final sent = items.where((i) => i.sent).skip(keepSent).toSet();
    items.removeWhere(sent.contains);
    await file.parent.create(recursive: true);
    final tmp = File('${file.path}.tmp');
    await tmp.writeAsString(jsonEncode(items.map((i) => i.toJson()).toList()), flush: true);
    await tmp.rename(file.path);
    notifyListeners();
  }

  /// 새 글을 폰에 저장한다. 이것이 끝나면 앱이 꺼져도 글은 남는다.
  Future<OutboxItem> add(String title, String text, {List<File> files = const []}) async {
    final id = newId();
    // ★ 고른 사진은 **폰 안 대기함 자리로 복사**해 둔다 — 사진첩·임시 폴더의 원본은 앱 밖에서 사라질 수 있다.
    final keep = <OutboxFile>[];
    if (files.isNotEmpty) {
      final dir = Directory('${file.parent.path}/vc_outbox_files');
      await dir.create(recursive: true);
      for (var i = 0; i < files.length; i++) {
        final name = files[i].uri.pathSegments.last;
        final copy = await files[i].copy('${dir.path}/$id-$i-$name');
        keep.add(OutboxFile(path: copy.path, name: name));
      }
    }
    final item = OutboxItem(
        id: id, title: title, text: text, created: DateTime.now().millisecondsSinceEpoch, files: keep);
    items.insert(0, item);
    await _save();
    return item;
  }

  /// 안 보낸 것을 오래된 것부터 보낸다. 못 닿으면 거기서 멈춘다(나머지는 다음에).
  Future<FlushResult> flush(VcApi api) async {
    if (_flushing) return FlushResult.done;
    _flushing = true;
    try {
      next:
      for (final item in items.where((i) => !i.sent).toList().reversed) {
        item.attempts++;
        try {
          // 첨부부터 올린다. 받은 이름을 글에 `![[이름]]` 으로 붙인다 — 같은 id 로 다시 보내도 서버는 한 번만 받는다.
          for (var i = 0; i < item.files.length; i++) {
            final f = item.files[i];
            if (f.uploaded != null) continue;
            final List<int> bytes;
            try {
              bytes = await File(f.path).readAsBytes();
            } on FileSystemException {
              // 사진 없이 글만 보내면 「사진 붙인 기록」이 조용히 반쪽이 된다 — 보내지 않고 까닭을 보인다
              item.error = '첨부가 폰에서 사라졌다 — ${f.name}';
              await _save();
              continue next;
            }
            f.uploaded = await api.attach(f.name, bytes, title: item.title, clientId: '${item.id}-f$i');
            await _save();
          }
          item.savedAs = await api.write(item.title, item.bodyToSend, clientId: item.id);
          item.sent = true;
          item.error = null;
          // 서버에 다 들어간 뒤에만 폰 사본을 지운다
          for (final f in item.files) {
            try {
              await File(f.path).delete();
            } on FileSystemException {
              // 이미 없으면 그만
            }
          }
        } on VcOffline catch (e) {
          item.error = null;
          offlineReason = e.reason;
          await _save();
          return FlushResult.offline;
        } on VcUnauthorized {
          await _save();
          return FlushResult.unauthorized;
        } on VcError catch (e) {
          item.error = e.message; // 서버가 거절 — 글은 남기고 까닭을 보인다
        }
        await _save();
      }
      return FlushResult.done;
    } finally {
      _flushing = false;
    }
  }
}
