// 사진 속 글자 — 기기 안에서 읽는다(아이폰 Apple Vision · 편의 기능 13번). 못 읽으면 빈 글.
import 'dart:io';

import 'package:flutter/services.dart';

typedef TextReader = Future<String> Function(File image);

const _channel = MethodChannel('vc/text');
const imageExts = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'};

Future<String> readImageText(File image) async {
  final name = image.path.toLowerCase();
  if (!imageExts.any(name.endsWith)) return '';
  try {
    return (await _channel.invokeMethod<String>('read', image.path))?.trim() ?? '';
  } catch (_) {
    return ''; // 안드로이드·시험 — 글자 없이 저장한다
  }
}

/// 메모 끝에 붙일 숨은 글자 — 옵시디언 주석(`%% … %%`)이라 보이지 않고 찾기에만 걸린다.
String hiddenText(Map<String, String> byName) {
  final parts = [
    for (final e in byName.entries)
      if (e.value.trim().isNotEmpty) '사진 글자 (${e.key}):\n${e.value.trim().replaceAll('%%', '％％')}',
  ];
  return parts.isEmpty ? '' : '%%\n${parts.join('\n\n')}\n%%';
}
