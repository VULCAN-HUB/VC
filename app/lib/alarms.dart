// 시간 알림(편의 기능 24번 · 구글 킵) — 폰 안에서만 뜬다. 보낸날·반납일에 챙긴다.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// 한 건 — 어느 글에 언제.
class Alarm {
  const Alarm({required this.id, required this.title, required this.when});

  final int id;
  final String title;
  final DateTime when;

  Map<String, dynamic> toJson() => {'id': id, 'title': title, 'when': when.toIso8601String()};

  static Alarm? fromJson(Object? j) {
    if (j is! Map) return null;
    final id = j['id'], title = j['title'], when = DateTime.tryParse('${j['when']}');
    if (id is! int || title is! String || when == null) return null;
    return Alarm(id: id, title: title, when: when);
  }
}

/// 폰 알림을 거는 쪽 — 시험은 가짜를 끼운다.
abstract class Notifier {
  Future<bool> schedule(Alarm a);

  Future<void> cancel(int id);
}

class PhoneNotifier implements Notifier {
  PhoneNotifier([FlutterLocalNotificationsPlugin? plugin])
      : _p = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _p;
  bool _ready = false;

  Future<void> _init() async {
    if (_ready) return;
    tzdata.initializeTimeZones();
    await _p.initialize(
      settings: const InitializationSettings(
        iOS: DarwinInitializationSettings(),
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      ),
    );
    await _p
        .resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>()
        ?.requestPermissions(alert: true, sound: true);
    _ready = true;
  }

  @override
  Future<bool> schedule(Alarm a) async {
    try {
      await _init();
      await _p.zonedSchedule(
        id: a.id,
        title: 'VC',
        body: a.title,
        scheduledDate: tz.TZDateTime.from(a.when, tz.local),
        notificationDetails: const NotificationDetails(
          iOS: DarwinNotificationDetails(),
          android: AndroidNotificationDetails('vc_alarm', '기억할 때', importance: Importance.high),
        ),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      );
      return true;
    } catch (_) {
      return false; // 허락을 안 줬거나 안 되는 기기 — 앱은 그대로 돈다
    }
  }

  @override
  Future<void> cancel(int id) async {
    try {
      await _init();
      await _p.cancel(id: id);
    } catch (_) {}
  }
}

/// 건 알림들을 폰 안 파일에 적어 둔다 — 설정에서 보고 지운다.
class AlarmBook extends ChangeNotifier {
  AlarmBook(this.file, this.notifier);

  final File file;
  final Notifier notifier;
  final List<Alarm> items = [];

  static Future<AlarmBook> open(File file, Notifier notifier) async {
    final b = AlarmBook(file, notifier);
    try {
      final j = jsonDecode(await file.readAsString());
      if (j is List) b.items.addAll(j.map(Alarm.fromJson).whereType<Alarm>());
    } on FileSystemException {
      // 처음
    } on FormatException {
      // 깨졌으면 비운다 — 알림 하나로 앱이 안 뜨면 안 된다
    }
    b._prune();
    return b;
  }

  void _prune() {
    final now = DateTime.now();
    items.removeWhere((a) => a.when.isBefore(now.subtract(const Duration(days: 1))));
    items.sort((a, b) => a.when.compareTo(b.when));
  }

  Future<bool> add(String title, DateTime when) async {
    final a = Alarm(id: DateTime.now().microsecondsSinceEpoch % 0x7fffffff, title: title, when: when);
    if (!await notifier.schedule(a)) return false;
    items.add(a);
    _prune();
    notifyListeners();
    await _save();
    return true;
  }

  Future<void> remove(Alarm a) async {
    await notifier.cancel(a.id);
    items.remove(a);
    notifyListeners();
    await _save();
  }

  Future<void> _save() async {
    try {
      await file.writeAsString(jsonEncode(items.map((a) => a.toJson()).toList()));
    } on FileSystemException {
      // 못 남겨도 이번 판은 걸려 있다
    }
  }
}
