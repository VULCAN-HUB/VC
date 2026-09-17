// 앱 설정 — 폰 안 작은 파일(대기함 옆). 편의 기능 8번부터.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

class AppPrefs extends ChangeNotifier {
  AppPrefs(this.file);

  final File file;
  bool openNew = false; // 앱을 열면 바로 새 메모(킵·애플 노트 빠른 메모)
  // 스마트 폴더(편의 기능 25번 · 애플 노트) — 찾는 말 + 칩을 이름 붙여 둔다
  final List<SmartFolder> smart = [];

  static Future<AppPrefs> open(File file) async {
    final p = AppPrefs(file);
    try {
      final j = jsonDecode(await file.readAsString());
      if (j is Map) {
        p.openNew = j['openNew'] == true;
        if (j['smart'] is List) {
          p.smart.addAll((j['smart'] as List).map(SmartFolder.fromJson).whereType<SmartFolder>());
        }
      }
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
    await _save();
  }

  Future<void> addSmart(SmartFolder f) async {
    smart.removeWhere((x) => x.name == f.name);
    smart.add(f);
    notifyListeners();
    await _save();
  }

  Future<void> removeSmart(String name) async {
    smart.removeWhere((x) => x.name == name);
    notifyListeners();
    await _save();
  }

  Future<void> _save() async {
    try {
      await file.writeAsString(jsonEncode({
        'openNew': openNew,
        'smart': smart.map((f) => f.toJson()).toList(),
      }));
    } on FileSystemException {
      // 못 남겨도 이번엔 먹는다
    }
  }
}

/// 저장해 둔 보기 — 찾는 말과 칩을 같이 담는다.
class SmartFolder {
  const SmartFolder({required this.name, required this.q, required this.filter});

  final String name;
  final String q;
  final String filter; // '' 전체 · '@photo' 사진 · 그 밖은 태그

  Map<String, dynamic> toJson() => {'name': name, 'q': q, 'filter': filter};

  static SmartFolder? fromJson(Object? j) {
    if (j is! Map) return null;
    final n = j['name'];
    if (n is! String || n.isEmpty) return null;
    return SmartFolder(name: n, q: '${j['q'] ?? ''}', filter: '${j['filter'] ?? ''}');
  }
}
