import 'dart:async';
// VC PC 서버에 붙는 길 — 화면과 떼어 두어 테스트로 잰다.
//
// 짝짓기 QR 은 PC 설정 「폰 연결」이 띄우는 `http://내부주소:8765/app#t=열쇠` 그대로다(웹앱과 같은 QR).
// 열쇠는 `#` 뒤에만 있으므로 여기서 떼어 기기 보안 저장소에 두고, 요청 머리에만 싣는다.
// 첫 판은 AI 없이 보기(찾기·펼치기)와 적기만 한다(오너 2026-09-14).

import 'dart:convert';

import 'package:http/http.dart' as http;

class Pairing {
  const Pairing(this.base, this.token);

  final Uri base;
  final String token;

  static Pairing? parse(String text) {
    final u = Uri.tryParse(text.trim());
    if (u == null || (u.scheme != 'http' && u.scheme != 'https') || u.host.isEmpty) return null;
    if (!u.fragment.startsWith('t=')) return null;
    final String token;
    try {
      token = Uri.decodeComponent(u.fragment.substring(2));
    } on FormatException {
      return null; // 깨진 %인코딩 — 찍힌 QR 이 망가졌다
    }
    if (token.isEmpty) return null;
    return Pairing(Uri(scheme: u.scheme, host: u.host, port: u.hasPort ? u.port : 8765), token);
  }

  String get label => '${base.host}:${base.port}';
}

/// 컴퓨터에 못 닿았다. **왜 못 닿았는지**를 싣는다.
///
/// ★ 전에는 무슨 오류든 한 문구로 뭉쳐, 폰이 다른 와이파이였는지 · VC 가 꺼졌는지 · 느린지를 가를 수 없었다
///   (2026-09-15 아이폰 실기에서 원인 찾는 데 오래 걸렸다). 비어 있으면 까닭을 모르는 것이다.
class VcOffline implements Exception {
  VcOffline([this.reason = '']);

  final String reason;
}

/// 연결 오류 글을 사람 말 까닭으로. 모르면 빈 글.
String offlineReason(Object e) {
  final m = e.toString().toLowerCase();
  if (e is TimeoutException) return '시간 초과';
  if (m.contains('connection refused')) return 'VC 가 꺼져 있다';
  if (m.contains('no route') || m.contains('network is unreachable') || m.contains('host is down') ||
      m.contains('failed host lookup')) {
    return '망이 달라 닿지 않는다';
  }
  if (m.contains('connection reset') || m.contains('connection abort') || m.contains('connection closed')) {
    return '연결이 끊겼다';
  }
  return '';
}

/// 열쇠가 안 맞는다 — 다시 짝지어야 한다.
class VcUnauthorized implements Exception {}

/// 서버가 거절했다. 서버가 준 까닭을 그대로 보인다.
class VcError implements Exception {
  VcError(this.status, this.message);

  final int status;
  final String message;

  @override
  String toString() => message;
}

class VcApi {
  VcApi(this.pairing, {http.Client? client, this.timeout = const Duration(seconds: 10)})
      : _client = client ?? http.Client();

  final Pairing pairing;
  final Duration timeout;
  final http.Client _client;

  Future<Map<String, dynamic>> _call(String method, String path,
      {Map<String, String>? query, Object? body}) async {
    final uri = pairing.base.replace(path: path, queryParameters: query);
    final headers = {'Authorization': 'Bearer ${pairing.token}', 'Content-Type': 'application/json'};
    final http.Response r;
    try {
      r = await (method == 'POST'
              ? _client.post(uri, headers: headers, body: jsonEncode(body))
              : _client.get(uri, headers: headers))
          .timeout(timeout);
    } on Exception catch (e) {
      throw VcOffline(offlineReason(e));
    }
    if (r.statusCode == 401) throw VcUnauthorized();
    var j = <String, dynamic>{};
    try {
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      if (d is Map<String, dynamic>) j = d;
    } on FormatException {
      // 몸이 JSON 이 아니면 빈 것으로 본다
    }
    // 새 글은 201, 덧붙기는 200 — 둘 다 성공이다
    if (r.statusCode >= 300) throw VcError(r.statusCode, '${j['error'] ?? 'HTTP ${r.statusCode}'}');
    return j;
  }

  /// 창고 글 수. 인사에 판이 빠졌으면 null.
  Future<int?> notes() async {
    final store = (await _call('GET', '/eb/v1/hello'))['store'];
    return store is Map ? store['notes'] as int? : null;
  }

  /// 첨부 받아 보기(글 보기의 사진). 열쇠는 **머리에만** 싣는다 — 주소에 넣으면 기록·캐시에 남는다.
  Uri attachmentUri(String name) => pairing.base.replace(path: '/eb/v1/attach', queryParameters: {'name': name});

  Map<String, String> get authHeaders => {'Authorization': 'Bearer ${pairing.token}'};

  /// 서식(5단계) — 창고 `_서식/` 의 틀. 자리(`{{날짜}}`)는 안 채운 채로 온다.
  Future<List<({String name, String body})>> templates() async {
    final list = (await _call('GET', '/eb/v1/templates'))['templates'];
    return [
      if (list is List)
        for (final e in list)
          if (e is Map && e['name'] is String && e['body'] is String)
            (name: e['name'] as String, body: e['body'] as String),
    ];
  }

  /// 첨부 올리기(4단계) — 사진·영상·녹음을 바이트 그대로. 서버가 **본문에 쓸 이름**을 준다.
  /// 같은 `clientId` 로 다시 보내면 서버는 몸을 안 받고 같은 이름을 준다(대기함 재전송).
  Future<String> attach(String name, List<int> bytes, {String title = '', String? clientId}) async {
    final uri = pairing.base.replace(path: '/eb/v1/attach', queryParameters: {
      'name': name,
      if (title.isNotEmpty) 'title': title,
      'client_id': ?clientId,
    });
    final http.Response r;
    try {
      // 영상은 크다 — 글보다 넉넉히 기다린다.
      r = await _client
          .post(uri,
              headers: {'Authorization': 'Bearer ${pairing.token}', 'Content-Type': 'application/octet-stream'},
              body: bytes)
          .timeout(timeout * 12);
    } on Exception catch (e) {
      throw VcOffline(offlineReason(e));
    }
    if (r.statusCode == 401) throw VcUnauthorized();
    var j = <String, dynamic>{};
    try {
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      if (d is Map<String, dynamic>) j = d;
    } on FormatException {
      // 몸이 JSON 이 아니면 빈 것으로 본다
    }
    if (r.statusCode >= 300) throw VcError(r.statusCode, '${j['error'] ?? 'HTTP ${r.statusCode}'}');
    final saved = j['name'];
    if (saved is! String || saved.isEmpty) throw VcError(r.statusCode, '서버가 첨부 이름을 안 줬다');
    return saved;
  }

  /// 「상태·기록」(결정 17 ③) — 자국 끝줄 · 죽음 줄 수 · 켠 지(초). 글 이름·집 경로는 서버가 가린다.
  Future<Map<String, dynamic>> status() => _call('GET', '/eb/v1/status');

  /// 찾기 1단 — 몸은 안 온다. 빈 말이면 창고 앞머리.
  Future<List<Map<String, dynamic>>> search(String q, {int k = 20}) async {
    final results = (await _call('GET', '/eb/v1/memory/search', query: {'q': q, 'k': '$k'}))['results'];
    return results is List ? results.whereType<Map<String, dynamic>>().toList() : [];
  }

  /// 찾기 2단 — 고른 글을 펼친다. q 를 주면 걸린 자리 둘레만.
  Future<Map<String, dynamic>> note(String title, {String q = '', String? folder}) => _call(
      'GET', '/eb/v1/memory/note',
      query: {'title': title, if (q.isNotEmpty) 'q': q, 'folder': ?folder});

  /// 적기 — 같은 제목이 있으면 뒤에 덧붙는다. 실제로 저장된 제목을 준다.
  /// `clientId` 가 같으면 서버는 한 번만 받는다(다시 보내도 안 겹친다).
  Future<String> write(String title, String text, {String? clientId}) async {
    final j = await _call('POST', '/eb/v1/memory',
        body: {'title': title, 'text': text, 'client_id': ?clientId});
    return '${j['saved_as'] ?? j['title'] ?? title}';
  }
}
