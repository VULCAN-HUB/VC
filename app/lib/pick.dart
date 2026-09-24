// 사진·영상 고르기(4단계). 화면과 떼어 두어 시험에서는 가짜로 갈아 끼운다.
import 'dart:io';

import 'package:image_picker/image_picker.dart';

enum PickHow { photo, video, library }

typedef Picker = Future<List<File>> Function(PickHow how);

/// 폰 카메라로 찍거나 사진첩에서 고른다. 안 고르고 닫으면 빈 목록.
Future<List<File>> pickMedia(PickHow how) async {
  final p = ImagePicker();
  switch (how) {
    case PickHow.photo:
      final x = await p.pickImage(source: ImageSource.camera);
      return [if (x != null) File(x.path)];
    case PickHow.video:
      final x = await p.pickVideo(source: ImageSource.camera);
      return [if (x != null) File(x.path)];
    case PickHow.library:
      return (await p.pickMultipleMedia()).map((x) => File(x.path)).toList();
  }
}
