import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';

// ★ 오너 실기(2026-09-16): 글을 쓰다 자판을 내리려면 제목을 눌러 ✓ 를 눌러야 했다. 노트앱은 밖을 누르면 내려간다.
void main() {
  testWidgets('글칸 밖을 누르면 자판이 내려간다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_kb');
    addTearDown(() => dir.deleteSync(recursive: true));
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: WriteTab(outbox: box, onSend: () async {}))));

    await tester.tap(find.byType(TextField).at(1));
    await tester.pump();
    final body = tester.widget<EditableText>(find.byType(EditableText).at(1));
    expect(body.focusNode.hasFocus, isTrue);

    await tester.tapAt(const Offset(5, 5));
    await tester.pump();
    expect(body.focusNode.hasFocus, isFalse, reason: '밖을 눌러도 자판이 안 내려간다');
  });
}
