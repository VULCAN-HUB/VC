// 앱 설정 — 폰 안 작은 파일(대기함 옆). 편의 기능 8번부터.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

class AppPrefs extends ChangeNotifier {
  AppPrefs(this.file);

  final File file;
  bool openNew = false; // 앱을 열면 바로 새 메모(킵·애플 노트 빠른 메모)

  static Future<AppPrefs> open(File file) async {
    final p = AppPrefs(file);
    try {
      final j = jsonDecode(await file.readAsString());
      if (j is Map) p.openNew = j['openNew'] == true;
    } on FileSystemException {
      // 처음
    } on FormatException {
      // 깨졌으면 기본값 — 설정 하나로 앱이 안 뜨면 안 된다
    }
    return p;
  }

  Future<void> setOpenNew(bool v) async {
    openNew = v;
    notifyListeners();
    try {
      await file.writeAsString(jsonEncode({'openNew': openNew}));
    } on FileSystemException {
      // 못 남겨도 이번엔 먹는다
    }
  }
}
