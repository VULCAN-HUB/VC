// 사진 그리기 — **한 번 받은 것은 다시 안 받는다**(오너 결정 27).
//
// 규칙(오너 지시 2026-09-18: 「모든 이미지가 매번 pc 연결될 때마다 폰에 다운받으면 안 된다」)
//   ① 폰에 있으면 파일에서 그린다 — 망을 안 탄다
//   ② 없으면 한 번 받아서 **폰에 남긴다**
//   ③ 목록 카드는 `width: 320` — 서버가 줄여 준 작은 사진(보통 30~60KB)
//   ④ 원본은 글을 열었을 때만
//   ⑤ 컴퓨터가 꺼져 있고 폰에도 없으면 **빈칸 대신** 「컴퓨터가 켜지면 보임」
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'cache.dart';
import 'vc_api.dart';

class AttachImage extends StatefulWidget {
  const AttachImage({
    super.key,
    required this.api,
    required this.name,
    this.cache,
    this.width = 0,
    this.fit = BoxFit.cover,
    this.missing,
  });

  final VcApi api;
  final String name;
  final Cache? cache;

  /// 0 이면 원본, 320 이면 목록 카드용 작은 사진.
  final int width;
  final BoxFit fit;

  /// 못 보일 때 대신 그릴 것(까닭을 받는다).
  final Widget Function(String why)? missing;

  @override
  State<AttachImage> createState() => _AttachImageState();
}

class _AttachImageState extends State<AttachImage> {
  File? _file;
  List<int>? _bytes; // 캐시를 못 쓸 때(자리가 없거나 시험) 한 번만 메모리에
  String? _why;

  @override
  void initState() {
    super.initState();
    _get();
  }

  @override
  void didUpdateWidget(AttachImage old) {
    super.didUpdateWidget(old);
    if (old.name != widget.name || old.width != widget.width) _get();
  }

  Future<void> _get() async {
    final cache = widget.cache;
    final kept = await cache?.attach(widget.name, width: widget.width);
    if (kept != null) {
      if (mounted) setState(() => _file = kept); // ① 폰에 있다 — 안 받는다
      return;
    }
    try {
      final got = await widget.api.fetchAttach(widget.name, width: widget.width);
      final saved = await cache?.putAttach(widget.name, got, width: widget.width);
      if (!mounted) return;
      setState(() {
        _file = saved;
        _bytes = saved == null ? got : null;
      });
    } on VcOffline {
      if (mounted) setState(() => _why = '컴퓨터가 켜지면 보임');
    } catch (_) {
      if (mounted) setState(() => _why = '사진을 못 불러왔어');
    }
  }

  // ★ 받는 중이든 못 받았든 **사진 자리에는 늘 이름이 붙어 있다** — 소리로 읽는 사람에게도,
  //   시험에서도 「여기가 그 사진 자리」임이 보여야 한다.
  @override
  Widget build(BuildContext context) => Semantics(label: widget.name, image: true, container: true, child: _inner());

  Widget _inner() {
    final f = _file;
    if (f != null) return Image.file(f, fit: widget.fit, semanticLabel: widget.name, errorBuilder: _broken);
    final b = _bytes;
    if (b != null) {
      return Image.memory(asBytes(b), fit: widget.fit, semanticLabel: widget.name, errorBuilder: _broken);
    }
    if (_why != null) return widget.missing?.call(_why!) ?? _hint(_why!);
    return const Center(child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 1.6)));
  }

  Widget _broken(BuildContext _, Object _, StackTrace? _) => widget.missing?.call('사진이 깨졌어') ?? _hint('사진이 깨졌어');

  static Widget _hint(String why) => Container(
    alignment: Alignment.center,
    color: const Color(0xFF15171A),
    padding: const EdgeInsets.all(8),
    child: Text(
      why,
      textAlign: TextAlign.center,
      style: const TextStyle(color: Color(0xFF6B7280), fontSize: 10.5),
    ),
  );
}

/// `List<int>` 를 `Uint8List` 로 — 시험에서 가짜 바이트를 그대로 넘길 수 있게.
Uint8List asBytes(List<int> b) => b is Uint8List ? b : Uint8List.fromList(b);
