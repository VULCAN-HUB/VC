// VC 폰 앱 — 아이폰·안드로이드 한 코드(Flutter). PC 창고를 보고, 폰에서 적은 것을 PC 에 저장한다.

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'vc_api.dart';

const _bg = Color(0xFF05080F);
const _accent = Color(0xFF00D9FF);
const _text = Color(0xFFCCF7FF);
const _dim = Color(0xFF78899F);

const _store = FlutterSecureStorage();
const _pairKey = 'vc_pair';

void main() => runApp(const VcApp());

class VcApp extends StatelessWidget {
  const VcApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'VC',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          scaffoldBackgroundColor: _bg,
          colorScheme: const ColorScheme.dark(primary: _accent, surface: _bg, onSurface: _text),
          appBarTheme: const AppBarTheme(backgroundColor: _bg, foregroundColor: _accent),
        ),
        home: const Root(),
      );
}

class Root extends StatefulWidget {
  const Root({super.key});

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  Pairing? _pairing;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final saved = await _store.read(key: _pairKey);
    if (!mounted) return;
    setState(() {
      _pairing = saved == null ? null : Pairing.parse(saved);
      _loading = false;
    });
  }

  Future<void> _pair(String text) async {
    final p = Pairing.parse(text);
    if (p == null) {
      _snack('VC 설정 → 폰 연결의 QR 이 아니야');
      return;
    }
    // 남이 띄운 QR 로 엉뚱한 곳에 붙지 않게 — 붙을 PC 주소를 사람이 보고 고른다
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('이 PC 에 연결할까?'),
        content: Text(p.label),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('아니')),
          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('연결')),
        ],
      ),
    );
    if (ok != true) return;
    await _store.write(key: _pairKey, value: text.trim());
    if (mounted) setState(() => _pairing = p);
  }

  Future<void> _unpair(String why) async {
    await _store.delete(key: _pairKey);
    if (!mounted) return;
    setState(() => _pairing = null);
    _snack(why);
  }

  void _snack(String s) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final p = _pairing;
    if (p == null) return PairPage(onCode: _pair);
    return Home(
      api: VcApi(p),
      onUnauthorized: () => _unpair('열쇠가 안 맞아 — QR 을 다시 찍어 줘'),
      onUnpair: () => _unpair('연결을 지웠어'),
    );
  }
}

class PairPage extends StatefulWidget {
  const PairPage({super.key, required this.onCode});

  final void Function(String) onCode;

  @override
  State<PairPage> createState() => _PairPageState();
}

class _PairPageState extends State<PairPage> {
  final _typed = TextEditingController();

  @override
  void dispose() {
    _typed.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('VC')),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text('PC 에서 VC 를 켜고 설정 → 폰 연결 의 「QR 보이기」를 눌러 줘.',
                style: TextStyle(fontSize: 16, color: _text)),
            const SizedBox(height: 6),
            const Text('PC 와 같은 와이파이여야 한다.', style: TextStyle(color: _dim)),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: () async {
                final code = await Navigator.push<String>(
                    context, MaterialPageRoute(builder: (_) => const ScanPage()));
                if (code != null) widget.onCode(code);
              },
              icon: const Icon(Icons.qr_code_scanner),
              label: const Text('QR 찍기'),
            ),
            const SizedBox(height: 28),
            TextField(
              controller: _typed,
              decoration: const InputDecoration(labelText: '또는 QR 주소를 붙여 넣기'),
            ),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: () => widget.onCode(_typed.text), child: const Text('연결')),
          ],
        ),
      );
}

class ScanPage extends StatefulWidget {
  const ScanPage({super.key});

  @override
  State<ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends State<ScanPage> {
  bool _done = false;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('QR 찍기')),
        body: MobileScanner(
          onDetect: (capture) {
            final codes = capture.barcodes;
            final value = codes.isEmpty ? null : codes.first.rawValue;
            if (_done || value == null) return;
            _done = true; // 한 번 찍히면 여러 번 돌아가지 않게
            Navigator.pop(context, value);
          },
        ),
      );
}

typedef OnFail = void Function(Object error);

class Home extends StatefulWidget {
  const Home({super.key, required this.api, required this.onUnauthorized, required this.onUnpair});

  final VcApi api;
  final VoidCallback onUnauthorized;
  final VoidCallback onUnpair;

  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> {
  int _tab = 0;
  String _state = '잇는 중…';

  @override
  void initState() {
    super.initState();
    _hello();
  }

  Future<void> _hello() async {
    try {
      final n = await widget.api.notes();
      _setState(n == null ? 'PC 에 이어짐' : 'PC 에 이어짐 · 창고 $n장');
    } catch (e) {
      _fail(e);
    }
  }

  void _setState(String s) {
    if (mounted) setState(() => _state = s);
  }

  void _fail(Object e) {
    if (e is VcUnauthorized) {
      widget.onUnauthorized();
    } else if (e is VcOffline) {
      _setState('PC 에 못 닿았어 — 같은 와이파이인지, VC 가 켜져 있는지 봐 줘');
    } else if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('VC'),
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(22),
            child: Padding(
              padding: const EdgeInsets.only(left: 16, bottom: 6),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(_state, style: const TextStyle(fontSize: 12, color: _dim)),
              ),
            ),
          ),
          actions: [
            PopupMenuButton<String>(
              onSelected: (_) => widget.onUnpair(),
              itemBuilder: (_) => const [PopupMenuItem(value: 'unpair', child: Text('연결 지우기'))],
            ),
          ],
        ),
        body: IndexedStack(index: _tab, children: [
          BrowseTab(api: widget.api, onFail: _fail),
          WriteTab(api: widget.api, onFail: _fail),
        ]),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _tab,
          onDestinationSelected: (i) => setState(() => _tab = i),
          destinations: const [
            NavigationDestination(icon: Icon(Icons.search), label: '보기'),
            NavigationDestination(icon: Icon(Icons.edit_note), label: '적기'),
          ],
        ),
      );
}

class BrowseTab extends StatefulWidget {
  const BrowseTab({super.key, required this.api, required this.onFail});

  final VcApi api;
  final OnFail onFail;

  @override
  State<BrowseTab> createState() => _BrowseTabState();
}

class _BrowseTabState extends State<BrowseTab> {
  final _q = TextEditingController();
  List<Map<String, dynamic>> _hits = [];
  String? _empty;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _find();
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _find() async {
    setState(() => _busy = true);
    try {
      final r = await widget.api.search(_q.text.trim());
      if (!mounted) return;
      setState(() {
        _hits = r;
        _empty = r.isEmpty ? '안 나왔어 — 말을 바꿔 봐' : null;
      });
    } catch (e) {
      widget.onFail(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 4, 0),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: _q,
                textInputAction: TextInputAction.search,
                onSubmitted: (_) => _find(),
                decoration: const InputDecoration(hintText: '찾을 말 (비우면 창고 앞머리)'),
              ),
            ),
            IconButton(onPressed: _find, icon: const Icon(Icons.search)),
          ]),
        ),
        if (_busy) const LinearProgressIndicator(),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _find,
            child: ListView(children: [
              if (_empty != null) ListTile(title: Text(_empty!, style: const TextStyle(color: _dim))),
              for (final h in _hits)
                ListTile(
                  title: Text('${h['title']}', style: const TextStyle(color: Colors.white)),
                  subtitle: Text(
                    [
                      '${h['summary'] ?? ''}',
                      [h['created'], h['kind'], h['folder']].whereType<String>().join(' · '),
                    ].where((s) => s.isNotEmpty).join('\n'),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => NotePage(
                        api: widget.api,
                        onFail: widget.onFail,
                        title: '${h['title']}',
                        q: _q.text.trim(),
                        folder: h['folder'] as String?,
                      ),
                    ),
                  ),
                ),
            ]),
          ),
        ),
      ]);
}

class NotePage extends StatefulWidget {
  const NotePage(
      {super.key, required this.api, required this.onFail, required this.title, this.q = '', this.folder});

  final VcApi api;
  final OnFail onFail;
  final String title;
  final String q;
  final String? folder;

  @override
  State<NotePage> createState() => _NotePageState();
}

class _NotePageState extends State<NotePage> {
  late final Future<Map<String, dynamic>> _note =
      widget.api.note(widget.title, q: widget.q, folder: widget.folder)..catchError((Object e) {
        widget.onFail(e);
        return <String, dynamic>{};
      });

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: FutureBuilder<Map<String, dynamic>>(
          future: _note,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) return const Center(child: Text('못 열었어', style: TextStyle(color: _dim)));
            final j = snap.data ?? {};
            return ListView(padding: const EdgeInsets.all(16), children: [
              SelectableText('${j['text'] ?? ''}', style: const TextStyle(fontSize: 15, height: 1.6)),
              if (j['cut'] == true)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text('(일부만 보였어 — 전체 ${j['full_chars']}자)', style: const TextStyle(color: _dim)),
                ),
            ]);
          },
        ),
      );
}

class WriteTab extends StatefulWidget {
  const WriteTab({super.key, required this.api, required this.onFail});

  final VcApi api;
  final OnFail onFail;

  @override
  State<WriteTab> createState() => _WriteTabState();
}

class _WriteTabState extends State<WriteTab> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  String _say = '';
  bool _busy = false;

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  static String _today() {
    final n = DateTime.now();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${n.year}-${two(n.month)}-${two(n.day)}';
  }

  Future<void> _save() async {
    final text = _body.text.trim();
    if (text.isEmpty || _busy) return;
    final title = _title.text.trim().isEmpty ? _today() : _title.text.trim();
    setState(() => _busy = true);
    try {
      final saved = await widget.api.write(title, text);
      _body.clear(); // 저장된 뒤에만 비운다
      if (mounted) setState(() => _say = 'PC 의 「$saved」에 적었어');
    } on VcOffline {
      if (mounted) setState(() => _say = 'PC 에 못 닿아서 못 적었어 — 적은 글은 칸에 그대로 있어');
    } catch (e) {
      if (mounted) setState(() => _say = '못 적었어 — $e');
      widget.onFail(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: Column(children: [
          TextField(controller: _title, decoration: const InputDecoration(hintText: '제목 (비우면 오늘 날짜)')),
          const SizedBox(height: 8),
          Expanded(
            child: TextField(
              controller: _body,
              maxLines: null,
              expands: true,
              textAlignVertical: TextAlignVertical.top,
              decoration: const InputDecoration(
                  hintText: '적을 것 — 같은 제목이 있으면 뒤에 덧붙는다', border: OutlineInputBorder()),
            ),
          ),
          const SizedBox(height: 8),
          Row(children: [
            FilledButton(onPressed: _busy ? null : _save, child: const Text('PC 에 적기')),
            const SizedBox(width: 12),
            Expanded(child: Text(_say, style: const TextStyle(color: _dim))),
          ]),
        ]),
      );
}
