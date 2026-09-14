// VC 폰 앱 — 아이폰·안드로이드 한 코드(Flutter). PC 창고를 보고, 폰에서 적은 것을 PC 에 저장한다.
//
// 얼굴은 PC VC 의 기본 테마 「불칸」(검정 바탕 · 달아오른 붉은빛 · `// 구역` 이름표)과 같게 둔다 —
// 같은 물건으로 읽혀야 한다. 표식 그림은 PC 의 logo.VulcanMark 를 구운 것(app/tools/make_assets.py).

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'vc_api.dart';

// 불칸 테마(pc/theme.py "vulcan")
const _bg = Color(0xFF0A0A0B);
const _deep = Color(0xFF050505);
const _glow = Color(0xFF2A0D06);
const _panel = Color(0xFF0E0D0E);
const _card = Color(0xFF151314);
const _text = Color(0xFFF2E6E0);
const _dim = Color(0xFFCFC4BE);
const _accent = Color(0xFFFF3D1F);
const _muted = Color(0xFF8B7F7A);
const _warn = Color(0xFFFFB454);
const _markAsset = 'assets/vc_mark.png';
const _markSolid = 'assets/vc_mark_solid.png'; // 불티 링 없이 표식만 — 작은 자리용

const _store = FlutterSecureStorage();
const _pairKey = 'vc_pair';

// 계기판 글씨. ★ 'monospace' 글꼴은 한글을 한 칸씩 벌려 「창 고 앞 머 리」가 됐다(에뮬레이터로 봄) —
//   기본 글꼴 + 숫자 폭 고정으로 같은 느낌만 낸다.
TextStyle _mono(double size, Color color, {FontWeight weight = FontWeight.w500}) => TextStyle(
    fontSize: size,
    color: color,
    letterSpacing: .6,
    fontWeight: weight,
    fontFeatures: const [FontFeature.tabularFigures()]);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    statusBarBrightness: Brightness.dark,
    systemNavigationBarColor: _panel,
    systemNavigationBarIconBrightness: Brightness.light,
  ));
  runApp(const VcApp());
}

ThemeData _theme() {
  OutlineInputBorder edge(Color c, [double w = 1]) => OutlineInputBorder(
      borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: c, width: w));
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: _bg,
    colorScheme: const ColorScheme.dark(
        primary: _accent, onPrimary: Colors.black, secondary: _accent, surface: _panel, onSurface: _text, error: _warn),
    textSelectionTheme: TextSelectionThemeData(
        cursorColor: _accent, selectionColor: _accent.withValues(alpha: .3), selectionHandleColor: _accent),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: _card.withValues(alpha: .92),
      hintStyle: const TextStyle(color: _muted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: edge(_accent.withValues(alpha: .12)),
      enabledBorder: edge(_accent.withValues(alpha: .12)),
      focusedBorder: edge(_accent, 1.2),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
          backgroundColor: _accent,
          foregroundColor: Colors.black,
          disabledBackgroundColor: _accent.withValues(alpha: .35),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
          foregroundColor: _accent,
          side: BorderSide(color: _accent.withValues(alpha: .5)),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: _panel,
      indicatorColor: _accent.withValues(alpha: .16),
      height: 66,
      iconTheme: WidgetStateProperty.resolveWith(
          (s) => IconThemeData(color: s.contains(WidgetState.selected) ? _accent : _muted)),
      labelTextStyle: WidgetStateProperty.resolveWith(
          (s) => TextStyle(fontSize: 12, color: s.contains(WidgetState.selected) ? _text : _muted)),
    ),
    appBarTheme: const AppBarTheme(backgroundColor: Colors.transparent, foregroundColor: _text, elevation: 0),
    snackBarTheme: const SnackBarThemeData(
        backgroundColor: _card, contentTextStyle: TextStyle(color: _text), behavior: SnackBarBehavior.floating),
    dialogTheme: DialogThemeData(
        backgroundColor: _card, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18))),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: _accent),
    popupMenuTheme: const PopupMenuThemeData(color: _card),
  );
}

class VcApp extends StatelessWidget {
  const VcApp({super.key});

  @override
  Widget build(BuildContext context) =>
      MaterialApp(title: 'VC', debugShowCheckedModeBanner: false, theme: _theme(), home: const Root());
}

// ── 공용 조각 ────────────────────────────────────────────────────────────────

/// 가운데 위가 은은하게 달아오른 검정 바탕 — PC 창의 GLOW_CENTER 와 같은 느낌.
class Backdrop extends StatelessWidget {
  const Backdrop({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
              center: Alignment(0, -0.6), radius: 1.15, colors: [_glow, _bg, _deep], stops: [0, .55, 1]),
        ),
        child: child,
      );
}

/// 숨 쉬듯 달아오르는 VC 표식.
class VcMark extends StatefulWidget {
  const VcMark({super.key, this.size = 160, this.breathe = true});

  final double size;
  final bool breathe;

  @override
  State<VcMark> createState() => _VcMarkState();
}

class _VcMarkState extends State<VcMark> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 2600));

  @override
  void initState() {
    super.initState();
    if (widget.breathe) _c.repeat(reverse: true);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (_, child) {
          final t = Curves.easeInOut.transform(_c.value);
          return Opacity(opacity: .8 + .2 * t, child: Transform.scale(scale: .97 + .05 * t, child: child));
        },
        child: Image.asset(_markAsset,
            width: widget.size, height: widget.size, filterQuality: FilterQuality.medium),
      );
}

/// `// 이름 ─────  꼬리` — PC 의 구역 이름표.
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.trailing});

  final String text;
  final String? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 18, 2, 10),
        child: Row(children: [
          Text('// $text', style: _mono(11, _accent.withValues(alpha: .8), weight: FontWeight.w700)),
          const SizedBox(width: 10),
          Expanded(
            child: Container(
              height: 1,
              decoration: BoxDecoration(
                  gradient: LinearGradient(colors: [_accent.withValues(alpha: .35), Colors.transparent])),
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 10), Text(trailing!, style: _mono(11, _muted))],
        ]),
      );
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: _card.withValues(alpha: .88),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: _accent.withValues(alpha: .14)),
        ),
        child: child,
      );
}

// ── 뿌리: 시작 화면 → 짝짓기 / 본 화면 ───────────────────────────────────────

class Root extends StatefulWidget {
  const Root({super.key});

  @override
  State<Root> createState() => _RootState();
}

class _RootState extends State<Root> {
  Pairing? _pairing;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    // 시작 화면을 한 호흡은 보인다 — 저장소가 너무 빨리 답하면 번쩍 하고 사라져 고장처럼 보인다
    final atLeast = Future<void>.delayed(const Duration(milliseconds: 1400));
    String? saved;
    try {
      saved = await _store.read(key: _pairKey);
    } catch (_) {
      saved = null; // 보안 저장소를 못 읽으면 다시 짝짓게 한다
    }
    await atLeast;
    if (!mounted) return;
    setState(() {
      _pairing = saved == null ? null : Pairing.parse(saved);
      _ready = true;
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
        title: const Text('이 PC 에 연결할까?', style: TextStyle(color: _text, fontSize: 19)),
        content: Text(p.label, style: _mono(15, _accent)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false), child: const Text('아니', style: TextStyle(color: _muted))),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('연결')),
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
    final p = _pairing;
    final Widget page = !_ready
        ? const IntroPage(key: ValueKey('intro'))
        : p == null
            ? PairPage(key: const ValueKey('pair'), onCode: _pair)
            : Home(
                key: ValueKey(p.label),
                api: VcApi(p),
                onUnauthorized: () => _unpair('열쇠가 안 맞아 — QR 을 다시 찍어 줘'),
                onUnpair: () => _unpair('연결을 지웠어'),
              );
    return AnimatedSwitcher(duration: const Duration(milliseconds: 600), child: page);
  }
}

class IntroPage extends StatelessWidget {
  const IntroPage({super.key});

  @override
  Widget build(BuildContext context) => Backdrop(
        child: Scaffold(
          backgroundColor: Colors.transparent,
          body: SafeArea(
            child: SizedBox(
              width: double.infinity,
              child: Column(children: [
                const Spacer(flex: 3),
                const VcMark(size: 230),
                const Padding(
                  padding: EdgeInsets.only(left: 16), // 글자 사이를 벌리면 뒤에 한 칸이 붙는다 — 가운데를 맞춘다
                  child: Text('VC',
                      style: TextStyle(fontSize: 46, fontWeight: FontWeight.w300, letterSpacing: 16, color: _text)),
                ),
                const SizedBox(height: 6),
                Text('VULCAN · 내 기억 창고', style: _mono(12, _muted)),
                const Spacer(flex: 4),
                Text('// PC 를 찾는 중', style: _mono(11, _accent.withValues(alpha: .75))),
                const SizedBox(height: 12),
                SizedBox(
                  width: 120,
                  child: LinearProgressIndicator(
                      minHeight: 2, color: _accent, backgroundColor: _accent.withValues(alpha: .12)),
                ),
                const SizedBox(height: 52),
              ]),
            ),
          ),
        ),
      );
}

// ── 짝짓기 ───────────────────────────────────────────────────────────────────

class PairPage extends StatefulWidget {
  const PairPage({super.key, required this.onCode});

  final void Function(String) onCode;

  @override
  State<PairPage> createState() => _PairPageState();
}

class _PairPageState extends State<PairPage> {
  final _typed = TextEditingController();
  bool _manual = false;

  @override
  void dispose() {
    _typed.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final code = await Navigator.push<String>(context, MaterialPageRoute(builder: (_) => const ScanPage()));
    if (code != null) widget.onCode(code);
  }

  @override
  Widget build(BuildContext context) => Backdrop(
        child: Scaffold(
          backgroundColor: Colors.transparent,
          body: SafeArea(
            child: ListView(padding: const EdgeInsets.fromLTRB(22, 18, 22, 32), children: [
              const Center(child: VcMark(size: 150)),
              const Text('PC 와 잇기',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 27, fontWeight: FontWeight.w600, color: _text)),
              const SizedBox(height: 8),
              Text('집 PC 의 VC 창고를 폰에서 보고,\n폰에서 적은 것을 PC 에 남긴다.',
                  textAlign: TextAlign.center, style: TextStyle(color: _dim.withValues(alpha: .7), height: 1.55)),
              const SectionLabel('순서'),
              const _Panel(
                child: Column(children: [
                  _Step('01', 'PC 에서 VC 를 켠다', '폰과 같은 와이파이여야 한다'),
                  _Step('02', '설정 → 폰 연결 → 「QR 보이기」', 'QR 은 2분 뒤 사라진다'),
                  _Step('03', '아래 「QR 찍기」로 찍는다', '붙을 PC 주소를 한 번 확인한다', last: true),
                ]),
              ),
              const SizedBox(height: 24),
              SizedBox(
                height: 58,
                child: FilledButton.icon(
                  onPressed: _scan,
                  icon: const Icon(Icons.qr_code_scanner, size: 24),
                  label: const Text('QR 찍기', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                ),
              ),
              const SizedBox(height: 6),
              TextButton(
                onPressed: () => setState(() => _manual = !_manual),
                child: Text(_manual ? '닫기' : '주소로 직접 연결', style: _mono(12, _muted)),
              ),
              AnimatedCrossFade(
                duration: const Duration(milliseconds: 250),
                crossFadeState: _manual ? CrossFadeState.showSecond : CrossFadeState.showFirst,
                firstChild: const SizedBox(width: double.infinity),
                secondChild: Column(children: [
                  TextField(
                    controller: _typed,
                    style: _mono(13, _text),
                    decoration: const InputDecoration(hintText: 'http://PC주소:8765/app#t=…'),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    height: 50,
                    child: OutlinedButton(onPressed: () => widget.onCode(_typed.text), child: const Text('연결')),
                  ),
                ]),
              ),
            ]),
          ),
        ),
      );
}

class _Step extends StatelessWidget {
  const _Step(this.no, this.title, this.sub, {this.last = false});

  final String no;
  final String title;
  final String sub;
  final bool last;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: last ? 0 : 16),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 36,
            height: 36,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: _accent.withValues(alpha: .08),
              border: Border.all(color: _accent.withValues(alpha: .55)),
            ),
            child: Text(no, style: _mono(11, _accent, weight: FontWeight.w700)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const SizedBox(height: 1),
              Text(title, style: const TextStyle(color: _text, fontSize: 15.5, fontWeight: FontWeight.w500)),
              const SizedBox(height: 3),
              Text(sub, style: const TextStyle(color: _muted, fontSize: 12.5)),
            ]),
          ),
        ]),
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
        backgroundColor: Colors.black,
        extendBodyBehindAppBar: true,
        appBar: AppBar(title: Text('// QR 찍기', style: _mono(14, _text))),
        body: Stack(fit: StackFit.expand, children: [
          MobileScanner(
            onDetect: (capture) {
              final codes = capture.barcodes;
              final value = codes.isEmpty ? null : codes.first.rawValue;
              if (_done || value == null) return;
              _done = true; // 한 번 찍히면 여러 번 돌아가지 않게
              Navigator.pop(context, value);
            },
          ),
          const IgnorePointer(child: CustomPaint(painter: _FramePainter())),
          const Positioned(
            left: 0,
            right: 0,
            bottom: 56,
            child: Text('PC 화면의 QR 을 네모 안에 맞춰 줘',
                textAlign: TextAlign.center, style: TextStyle(color: _text, fontSize: 15)),
          ),
        ]),
      );
}

class _FramePainter extends CustomPainter {
  const _FramePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final side = size.shortestSide * .66;
    final r = Rect.fromCenter(center: size.center(Offset.zero), width: side, height: side);
    final outside = Path()
      ..fillType = PathFillType.evenOdd
      ..addRect(Offset.zero & size)
      ..addRRect(RRect.fromRectAndRadius(r, const Radius.circular(20)));
    canvas.drawPath(outside, Paint()..color = Colors.black.withValues(alpha: .55));
    final line = Paint()
      ..color = _accent
      ..strokeWidth = 4
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    const arm = 34.0;
    for (final c in [r.topLeft, r.topRight, r.bottomLeft, r.bottomRight]) {
      final dx = c.dx == r.left ? arm : -arm;
      final dy = c.dy == r.top ? arm : -arm;
      canvas.drawLine(c, c + Offset(dx, 0), line);
      canvas.drawLine(c, c + Offset(0, dy), line);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

// ── 본 화면 ─────────────────────────────────────────────────────────────────

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
  String _state = 'PC 에 잇는 중…';
  Color _dot = _muted;

  @override
  void initState() {
    super.initState();
    _hello();
  }

  Future<void> _hello() async {
    try {
      final n = await widget.api.notes();
      _show(n == null ? '${widget.api.pairing.label} 에 이어짐' : '이어짐 · 창고 $n장', _accent);
    } catch (e) {
      _fail(e);
    }
  }

  void _show(String s, Color dot) {
    if (mounted) {
      setState(() {
        _state = s;
        _dot = dot;
      });
    }
  }

  void _fail(Object e) {
    if (e is VcUnauthorized) {
      widget.onUnauthorized();
    } else if (e is VcOffline) {
      _show('PC 에 못 닿았어 — 같은 와이파이·VC 켜짐을 봐 줘', _warn);
    } else if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) => Backdrop(
        child: Scaffold(
          backgroundColor: Colors.transparent,
          body: SafeArea(
            bottom: false,
            child: Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(10, 8, 4, 2),
                child: Row(children: [
                  const Padding(
                    padding: EdgeInsets.all(6),
                    child: Image(image: AssetImage(_markSolid), width: 34, height: 34),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      const Text('VC',
                          style: TextStyle(fontSize: 21, letterSpacing: 3, fontWeight: FontWeight.w600, color: _text)),
                      const SizedBox(height: 2),
                      Row(children: [
                        Container(
                          width: 7,
                          height: 7,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: _dot,
                            boxShadow: [BoxShadow(color: _dot.withValues(alpha: .7), blurRadius: 6)],
                          ),
                        ),
                        const SizedBox(width: 7),
                        Flexible(
                          child: Text(_state, style: _mono(11, _muted), overflow: TextOverflow.ellipsis),
                        ),
                      ]),
                    ]),
                  ),
                  PopupMenuButton<String>(
                    icon: const Icon(Icons.more_vert, color: _muted),
                    onSelected: (_) => widget.onUnpair(),
                    itemBuilder: (_) => const [PopupMenuItem(value: 'unpair', child: Text('연결 지우기'))],
                  ),
                ]),
              ),
              Expanded(
                child: IndexedStack(index: _tab, children: [
                  BrowseTab(api: widget.api, onFail: _fail),
                  WriteTab(api: widget.api, onFail: _fail),
                ]),
              ),
            ]),
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: const [
              NavigationDestination(icon: Icon(Icons.search), label: '보기'),
              NavigationDestination(icon: Icon(Icons.edit_note), label: '적기'),
            ],
          ),
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
  String _asked = '';
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
    final q = _q.text.trim();
    setState(() => _busy = true);
    try {
      final r = await widget.api.search(q);
      if (!mounted) return;
      setState(() {
        _hits = r;
        _asked = q;
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
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: TextField(
            controller: _q,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _find(),
            decoration: InputDecoration(
              hintText: '창고에서 찾기',
              prefixIcon: const Icon(Icons.search, color: _muted),
              suffixIcon: IconButton(icon: const Icon(Icons.arrow_forward, color: _accent), onPressed: _find),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: SectionLabel(_asked.isEmpty ? '창고 앞머리' : '찾은 것', trailing: _busy ? '…' : '${_hits.length}장'),
        ),
        Expanded(
          child: RefreshIndicator(
            color: _accent,
            backgroundColor: _card,
            onRefresh: _find,
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 24), children: [
              if (_empty != null)
                Padding(
                  padding: const EdgeInsets.only(top: 40),
                  child: Column(children: [
                    const Opacity(opacity: .3, child: Image(image: AssetImage(_markSolid), width: 72, height: 72)),
                    const SizedBox(height: 8),
                    Text(_empty!, style: const TextStyle(color: _muted)),
                  ]),
                ),
              for (final h in _hits)
                NoteCard(
                  hit: h,
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => NotePage(
                        api: widget.api,
                        onFail: widget.onFail,
                        title: '${h['title']}',
                        q: _asked,
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

class NoteCard extends StatelessWidget {
  const NoteCard({super.key, required this.hit, required this.onTap});

  final Map<String, dynamic> hit;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final summary = '${hit['summary'] ?? ''}'.trim();
    final meta = [hit['created'], hit['kind'], hit['folder']].whereType<String>().join('  ·  ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: _card.withValues(alpha: .9),
        borderRadius: BorderRadius.circular(14),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          splashColor: _accent.withValues(alpha: .12),
          child: IntrinsicHeight(
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(width: 3, color: _accent.withValues(alpha: .85)),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 12, 6, 12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${hit['title']}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: _text, fontSize: 16, fontWeight: FontWeight.w600)),
                    if (summary.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(summary,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: _dim.withValues(alpha: .72), fontSize: 13.5, height: 1.45)),
                    ],
                    if (meta.isNotEmpty) ...[const SizedBox(height: 8), Text(meta, style: _mono(10.5, _muted))],
                  ]),
                ),
              ),
              const Padding(
                padding: EdgeInsets.only(right: 8),
                child: Icon(Icons.chevron_right, color: _muted, size: 20),
              ),
            ]),
          ),
        ),
      ),
    );
  }
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
  Widget build(BuildContext context) => Backdrop(
        child: Scaffold(
          backgroundColor: Colors.transparent,
          appBar: AppBar(title: Text(widget.title, overflow: TextOverflow.ellipsis)),
          body: FutureBuilder<Map<String, dynamic>>(
            future: _note,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snap.hasError) return const Center(child: Text('못 열었어', style: TextStyle(color: _muted)));
              final j = snap.data ?? {};
              return ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
                if (widget.folder != null) Text('// ${widget.folder}', style: _mono(11, _muted)),
                const SizedBox(height: 8),
                _Panel(
                  child: SelectableText('${j['text'] ?? ''}',
                      style: const TextStyle(color: _text, fontSize: 15.5, height: 1.7)),
                ),
                if (j['cut'] == true)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text('(일부만 보였어 — 전체 ${j['full_chars']}자)', style: _mono(11, _muted)),
                  ),
              ]);
            },
          ),
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
  bool _sayOk = true;
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

  void _tell(String s, bool ok) {
    if (mounted) {
      setState(() {
        _say = s;
        _sayOk = ok;
      });
    }
  }

  Future<void> _save() async {
    final text = _body.text.trim();
    if (text.isEmpty || _busy) return;
    final title = _title.text.trim().isEmpty ? _today() : _title.text.trim();
    setState(() => _busy = true);
    try {
      final saved = await widget.api.write(title, text);
      _body.clear(); // 저장된 뒤에만 비운다
      _tell('PC 의 「$saved」에 적었어', true);
    } on VcOffline {
      _tell('PC 에 못 닿아서 못 적었어 — 적은 글은 칸에 그대로 있어', false);
    } catch (e) {
      _tell('못 적었어 — $e', false);
      widget.onFail(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
        child: Column(children: [
          const SectionLabel('PC 에 남기기'),
          TextField(
            controller: _title,
            decoration: const InputDecoration(
                hintText: '제목 — 비우면 오늘 날짜', prefixIcon: Icon(Icons.title, color: _muted)),
          ),
          const SizedBox(height: 10),
          Expanded(
            child: TextField(
              controller: _body,
              maxLines: null,
              expands: true,
              textAlignVertical: TextAlignVertical.top,
              style: const TextStyle(fontSize: 15.5, height: 1.6),
              decoration: const InputDecoration(hintText: '적을 것 — 같은 제목이 있으면 뒤에 덧붙는다'),
            ),
          ),
          const SizedBox(height: 12),
          if (_say.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(children: [
                Icon(_sayOk ? Icons.check_circle_outline : Icons.error_outline,
                    size: 16, color: _sayOk ? _accent : _warn),
                const SizedBox(width: 8),
                Expanded(child: Text(_say, style: TextStyle(color: _dim.withValues(alpha: .85), fontSize: 13))),
              ]),
            ),
          SizedBox(
            width: double.infinity,
            height: 54,
            child: FilledButton.icon(
              onPressed: _busy ? null : _save,
              icon: _busy
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                  : const Icon(Icons.north_east),
              label: const Text('PC 에 적기', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            ),
          ),
        ]),
      );
}
