import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/outbox.dart';

// 4단계 — 적기 탭에서 고른 사진이 칩으로 보이고, 글 없이 사진만으로도 폰에 먼저 저장된다(에버노트처럼).
void main() {
  testWidgets('고른 사진이 칩으로 보이고, 사진만으로도 저장되고, 저장 뒤 칩이 빈다', (tester) async {
    final dir = Directory.systemTemp.createTempSync('vc_write_attach');
    addTearDown(() => dir.deleteSync(recursive: true));
    final album = Directory('${dir.path}/album')..createSync();
    final pic = File('${album.path}/IMG_0002.HEIC')..writeAsBytesSync([9]);
    final box = (await tester.runAsync(() => Outbox.open(File('${dir.path}/vc_outbox.json'))))!;

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: WriteTab(outbox: box, onSend: () async {}, pick: (_) async => [pic])),
    ));

    await tester.tap(find.byTooltip('사진첩에서 고르기'));
    await tester.pump();
    expect(find.text('IMG_0002.HEIC'), findsOneWidget);

    await tester.runAsync(() async {
      await tester.tap(find.text('저장'));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pump();

    expect(box.items.single.files.single.name, 'IMG_0002.HEIC', reason: '글 없이 사진만 붙인 기록이 저장이 안 된다');
    expect(find.text('IMG_0002.HEIC'), findsNothing, reason: '저장한 뒤에도 칩이 남는다');
  });
}
