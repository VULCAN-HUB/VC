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
  });

  final String id;
  final String title;
  final String text;
  final int created; // 밀리초
  int attempts;
  bool sent;
  String? savedAs;
  String? error;

  SendState get state => sent ? SendState.sent : (attempts == 0 ? SendState.saved : SendState.waiting);

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'text': text,
        'created': created,
        'attempts': attempts,
        'sent': sent,
        'savedAs': ?savedAs,
        'error': ?error,
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
  Future<OutboxItem> add(String title, String text) async {
    final item = OutboxItem(
        id: newId(), title: title, text: text, created: DateTime.now().millisecondsSinceEpoch);
    items.insert(0, item);
    await _save();
    return item;
  }

  /// 안 보낸 것을 오래된 것부터 보낸다. 못 닿으면 거기서 멈춘다(나머지는 다음에).
  Future<FlushResult> flush(VcApi api) async {
    if (_flushing) return FlushResult.done;
    _flushing = true;
    try {
      for (final item in items.where((i) => !i.sent).toList().reversed) {
        item.attempts++;
        try {
          item.savedAs = await api.write(item.title, item.text, clientId: item.id);
          item.sent = true;
          item.error = null;
        } on VcOffline {
          item.error = null;
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
