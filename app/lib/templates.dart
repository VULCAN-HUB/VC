// 서식을 폰까지(5단계 · 결정 19). 컴퓨터 창고 `_서식/` 의 틀을 받아 두고, 못 닿아도 지난번 받은 틀로 적는다.
import 'dart:convert';
import 'dart:io';

import 'vc_api.dart';

typedef Tpl = ({String name, String body});

/// `{{날짜}}` 같은 자리를 **적는 순간** 채운다. 모르는 이름은 그대로 둔다 — 지우면 오타가 흔적도 없이 사라진다(PC 와 같은 규칙).
String fillSlots(String text, {String title = '', DateTime? now}) {
  final n = now ?? DateTime.now();
  String two(int v) => v.toString().padLeft(2, '0');
  final date = '${n.year}-${two(n.month)}-${two(n.day)}';
  final time = '${two(n.hour)}:${two(n.minute)}';
  final table = {'날짜': date, 'date': date, '시각': time, 'time': time, '제목': title, 'title': title};
  return text.replaceAllMapped(
      RegExp(r'\{\{\s*([^{}]+?)\s*\}\}'), (m) => table[m.group(1)!.toLowerCase()] ?? m.group(0)!);
}

class TemplateBook {
  TemplateBook(this.cache);

  final File cache;

  /// 컴퓨터에서 받아 두고 돌려준다. 못 닿으면 지난번 받은 것(없으면 빈 목록)과 `true`(못 닿음).
  Future<(List<Tpl>, bool)> load(VcApi api) async {
    try {
      final got = await api.templates();
      try {
        await cache.writeAsString(jsonEncode([
          for (final t in got) {'name': t.name, 'body': t.body}
        ]));
      } on FileSystemException {
        // 받아 두기만 못 했다 — 이번에는 쓸 수 있다
      }
      return (got, false);
    } on VcOffline {
      return (await _cached(), true);
    }
  }

  Future<List<Tpl>> _cached() async {
    try {
      final j = jsonDecode(await cache.readAsString());
      if (j is List) {
        return [
          for (final e in j)
            if (e is Map && e['name'] is String && e['body'] is String)
              (name: e['name'] as String, body: e['body'] as String),
        ];
      }
    } on FileSystemException {
      // 한 번도 못 받았다
    } on FormatException {
      // 깨졌다 — 다음에 받으면 새로 쓴다
    }
    return [];
  }
}
