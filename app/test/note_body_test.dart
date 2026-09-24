import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vc_app/attach.dart';
import 'package:vc_app/main.dart';
import 'package:vc_app/vc_api.dart';

// ★ 오너 실기(2026-09-16): 사진은 맥에 붙었는데 앱 글 보기에는 `![[…]]` 글자만 보였다.
void main() {
  testWidgets('사진은 그림으로, 영상은 📎 칸으로, 글 끼움은 글자 그대로', (tester) async {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=tok')!);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: NoteBody(api: api, text: '받은 제품\n\n![[받은 제품.heic]]\n\n![[IMG_0001.mov]]\n\n![[보고서#8월]]'),
          ),
        ),
      ),
    );
    await tester.pump();

    // 사진 자리는 AttachImage 가 맡는다 — 폰에 있으면 파일에서, 없으면 한 번만 받는다(결정 27)
    expect(find.byType(AttachImage), findsOneWidget, reason: '사진이 그림으로 안 뜬다');
    expect(tester.widget<AttachImage>(find.byType(AttachImage)).name, '받은 제품.heic');
    expect(tester.widget<AttachImage>(find.byType(AttachImage)).width, 0, reason: '글 보기는 원본을 보여야 한다');
    expect(find.text('IMG_0001.mov'), findsOneWidget, reason: '영상이 📎 칸으로 안 뜬다');
    expect(find.textContaining('![[받은 제품.heic]]'), findsNothing, reason: '사진 자리에 글자가 그대로 보인다');
    expect(find.textContaining('받은 제품'), findsWidgets);
    expect(find.textContaining('![[보고서#8월]]'), findsOneWidget, reason: '글 끼움까지 지웠다');
  });

  test('첨부 주소에는 열쇠를 안 넣는다', () {
    final api = VcApi(Pairing.parse('http://100.101.2.3:8765/app#t=secret-tok')!);
    expect(api.attachmentUri('사진.heic').toString(), isNot(contains('secret-tok')));
    expect(api.authHeaders['Authorization'], 'Bearer secret-tok');
  });
}
