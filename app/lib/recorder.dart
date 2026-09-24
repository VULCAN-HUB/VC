// 녹음 — 폰 마이크로 m4a 를 만든다(편의 기능 14번). 받아쓰기·요약은 컴퓨터가 뒤에서 한다.
import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

typedef RecordMemo = Future<File?> Function(BuildContext context);

Future<File?> recordMemo(BuildContext context) =>
    showModalBottomSheet<File>(context: context, isDismissible: false, builder: (_) => const _RecordSheet());

class _RecordSheet extends StatefulWidget {
  const _RecordSheet();

  @override
  State<_RecordSheet> createState() => _RecordSheetState();
}

class _RecordSheetState extends State<_RecordSheet> {
  final _rec = AudioRecorder();
  final _watch = Stopwatch();
  Timer? _tick;
  String? _why;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    try {
      if (!await _rec.hasPermission()) {
        setState(() => _why = '마이크를 못 쓴다 — 아이폰 설정 › VC › 마이크를 켜 줘');
        return;
      }
      final dir = await getTemporaryDirectory();
      final n = DateTime.now();
      String two(int v) => v.toString().padLeft(2, '0');
      final name = '녹음 ${n.year}-${two(n.month)}-${two(n.day)} ${two(n.hour)}${two(n.minute)}.m4a';
      await _rec.start(const RecordConfig(encoder: AudioEncoder.aacLc), path: '${dir.path}/$name');
      _watch.start();
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    } catch (e) {
      if (mounted) setState(() => _why = '녹음을 못 시작했어 ($e)');
    }
  }

  Future<void> _stop({required bool keep}) async {
    _tick?.cancel();
    String? path;
    try {
      path = await _rec.stop();
    } catch (_) {}
    await _rec.dispose();
    if (!mounted) return;
    Navigator.pop(context, keep && path != null ? File(path) : null);
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = _watch.elapsed.inSeconds;
    final t = '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 20, 24, 16),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.mic, size: 40, color: _why == null ? const Color(0xFFFF3D1F) : Colors.grey),
          const SizedBox(height: 8),
          Text(_why ?? '녹음 중  $t', textAlign: TextAlign.center, style: const TextStyle(fontSize: 18)),
          const SizedBox(height: 6),
          const Text('멈추면 메모에 붙는다. 컴퓨터가 받아쓰고 요약한다.',
              textAlign: TextAlign.center, style: TextStyle(color: Colors.grey, fontSize: 12.5)),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: TextButton(onPressed: () => _stop(keep: false), child: const Text('버리기'))),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton.icon(
                onPressed: _why == null ? () => _stop(keep: true) : null,
                icon: const Icon(Icons.stop),
                label: const Text('멈추고 붙이기'),
              ),
            ),
          ]),
        ]),
      ),
    );
  }
}
