// 폰 안 작은 창고 — 컴퓨터가 꺼져 있어도 지난번에 본 것과 내가 쓴 것을 본다(오너 결정 27).
//
// ★★ **왜 필요한가.** 전에는 폰에 남는 것이 대기함(보낼 것)뿐이라, 컴퓨터 VC 가 꺼지면
//   폰은 **아무것도 못 읽었다.** 밖에서 「그거 뭐였지」 하고 열었을 때 빈 화면인 노트 앱은
//   노트 앱이 아니다.
//
// 무엇을 남기나
//   • 목록 카드(제목·미리보기·태그·날짜·첫 사진 이름) — `list.json`
//   • 열어 본 글의 본문 — `notes/<이름>.json` (되돌려 보낼 때 쓸 **지문**과 함께)
//   • 받아 본 사진 — `attach/<첨부 이름>` · 작은 사진은 `attach/320-<이름>`
//
// 사진 규칙(오너 지시 2026-09-18): **매번 다시 받지 않는다.**
//   ① 목록 카드는 **작은 사진**(서버가 320px 로 줄여 준다 · 보통 30~60KB)
//   ② 원본은 **글을 열었을 때만**
//   ③ 받은 것은 파일로 남는다 — 첨부 이름은 서버가 정하고 안 바뀌니 **이름이 곧 열쇠**다
//   ④ 폰에서 올린 사진은 **받지 않는다** — 올릴 때 그 파일을 그대로 넣어 둔다
//   ⑤ 미리 받기는 없다. 상한을 넘으면 **오래 안 본 것부터** 지운다
import 'dart:convert';
import 'dart:io';

/// 폰에 남기는 것들. 파일 하나가 깨져도 앱은 살아야 하므로 읽기는 전부 실패를 삼킨다.
class Cache {
  Cache(this.root, {this.limitBytes = 500 * 1024 * 1024});

  final Directory root;

  /// 사진 보관 상한. 넘으면 오래 안 본 것부터 지운다. 설정에서 바꾼다.
  int limitBytes;

  Directory get _notes => Directory('${root.path}/notes');
  Directory get _attach => Directory('${root.path}/attach');
  File get _listFile => File('${root.path}/list.json');

  /// 파일 이름으로 쓸 수 있게. 제목에 `/`·`:` 가 들어가도 안전하고, 길어도 잘리지 않는다.
  static String key(String title) => base64Url.encode(utf8.encode(title));

  // --- 목록 ---------------------------------------------------------------

  Future<void> saveList(List<Map<String, dynamic>> cards) async {
    try {
      await root.create(recursive: true);
      await _listFile.writeAsString(jsonEncode({'when': DateTime.now().toIso8601String(), 'cards': cards}));
    } on FileSystemException {
      // 못 남겨도 화면은 돈다
    }
  }

  Future<List<Map<String, dynamic>>> list() async {
    try {
      final j = jsonDecode(await _listFile.readAsString());
      if (j is Map && j['cards'] is List) {
        return (j['cards'] as List).whereType<Map<String, dynamic>>().toList();
      }
    } on FileSystemException {
      // 아직 없다
    } on FormatException {
      // 깨졌다 — 없는 셈 친다
    }
    return const [];
  }

  /// 목록을 마지막으로 받은 때. 「지난번에 본 것」 띠에 쓴다.
  Future<DateTime?> listWhen() async {
    try {
      final j = jsonDecode(await _listFile.readAsString());
      if (j is Map && j['when'] is String) return DateTime.tryParse(j['when'] as String);
    } on FileSystemException {
      // 아직 없다
    } on FormatException {
      // 깨졌다
    }
    return null;
  }

  // --- 글 -----------------------------------------------------------------

  Future<void> saveNote(String title, Map<String, dynamic> note) async {
    try {
      await _notes.create(recursive: true);
      await File('${_notes.path}/${key(title)}.json').writeAsString(jsonEncode(note));
    } on FileSystemException {
      // 못 남겨도 화면은 돈다
    }
  }

  Future<Map<String, dynamic>?> note(String title) async {
    try {
      final j = jsonDecode(await File('${_notes.path}/${key(title)}.json').readAsString());
      if (j is Map<String, dynamic>) return j;
    } on FileSystemException {
      // 본 적 없는 글
    } on FormatException {
      // 깨졌다
    }
    return null;
  }

  Future<void> dropNote(String title) async {
    try {
      await File('${_notes.path}/${key(title)}.json').delete();
    } on FileSystemException {
      // 원래 없었다
    }
  }

  /// 폰에서 쓴 글을 **보내기 전에** 폰 창고에 넣는다 — 컴퓨터가 꺼져 있어도 바로 읽힌다.
  ///
  /// 이미 있는 글이면 서버가 할 것과 같게 **뒤에 덧붙인다**(덮지 않는다). 목록 맨 위에도 올린다.
  Future<void> addMine(String title, String body) async {
    final old = await note(title);
    final was = '${old?['text'] ?? ''}'.trimRight();
    await saveNote(title, {
      ...?old,
      'title': title,
      'text': was.isEmpty ? body : '$was\n\n$body',
      'mine': true, // 폰에서 쓴 것 — 아직 컴퓨터에 없을 수 있다
    });
    final cards = [...await list()];
    final today = DateTime.now().toIso8601String().substring(0, 10);
    final first = body.trim().split('\n').firstWhere((l) => l.trim().isNotEmpty, orElse: () => '');
    cards.removeWhere((c) => c['title'] == title);
    cards.insert(0, {'title': title, 'preview': first, 'updated': today, 'mine': true});
    await saveList(cards);
  }

  // --- 사진 ---------------------------------------------------------------

  /// 첨부 하나가 폰에 있는 자리. [width] 를 주면 작은 사진 자리.
  File attachFile(String name, {int width = 0}) => File('${_attach.path}/${width > 0 ? '$width-' : ''}${key(name)}');

  /// 이미 받아 둔 사진. 없으면 null. **있으면 다시 받지 않는다.**
  Future<File?> attach(String name, {int width = 0}) async {
    final f = attachFile(name, width: width);
    if (!await f.exists()) return null;
    try {
      await f.setLastAccessed(DateTime.now()); // 오래 안 본 것부터 지우려고 손댄 때를 적는다
    } on FileSystemException {
      // 못 적어도 그림은 보인다
    }
    return f;
  }

  /// 받은(또는 폰에서 올린) 사진을 넣어 둔다.
  Future<File?> putAttach(String name, List<int> bytes, {int width = 0}) async {
    try {
      await _attach.create(recursive: true);
      final f = attachFile(name, width: width);
      await f.writeAsBytes(bytes);
      await sweep();
      return f;
    } on FileSystemException {
      return null;
    }
  }

  /// 폰에서 올린 사진을 **받지 않고** 그대로 넣는다 — 방금 올린 것을 되받는 왕복이 없다.
  Future<File?> adoptUpload(String savedName, File local) async {
    try {
      return await putAttach(savedName, await local.readAsBytes());
    } on FileSystemException {
      return null;
    }
  }

  // --- 크기 ---------------------------------------------------------------

  Future<List<FileSystemEntity>> _attachFiles() async {
    if (!await _attach.exists()) return const [];
    return _attach.listSync().whereType<File>().toList();
  }

  Future<int> bytes() async {
    var sum = 0;
    for (final f in await _attachFiles()) {
      try {
        sum += (f as File).lengthSync();
      } on FileSystemException {
        // 그 사이 사라졌다
      }
    }
    return sum;
  }

  /// 상한을 넘으면 **오래 안 본 것부터** 지운다. 글자(글·목록)는 건드리지 않는다 — 싸다.
  Future<int> sweep() async {
    final files = <File>[];
    var sum = 0;
    for (final e in await _attachFiles()) {
      final f = e as File;
      try {
        sum += f.lengthSync();
        files.add(f);
      } on FileSystemException {
        // 그 사이 사라졌다
      }
    }
    if (sum <= limitBytes) return 0;
    files.sort((a, b) => a.statSync().accessed.compareTo(b.statSync().accessed));
    var dropped = 0;
    for (final f in files) {
      if (sum <= limitBytes) break;
      try {
        sum -= f.lengthSync();
        f.deleteSync();
        dropped++;
      } on FileSystemException {
        // 못 지워도 다음 것으로
      }
    }
    return dropped;
  }

  /// 사진만 전부 비운다(설정 › 「지금 비우기」). 글과 목록은 남는다 — 오프라인에서 읽어야 하니까.
  Future<void> clearAttachments() async {
    try {
      if (await _attach.exists()) await _attach.delete(recursive: true);
    } on FileSystemException {
      // 못 지워도 상관없다
    }
  }
}
