// VC 폰 앱 — 아이폰·안드로이드 한 코드(Flutter). PC 창고를 보고, 폰에서 적은 것을 PC 에 저장한다.
//
// 얼굴은 PC VC 의 기본 테마 「불칸」(검정 바탕 · 달아오른 붉은빛 · `// 구역` 이름표)과 같게 둔다 —
// 같은 물건으로 읽혀야 한다. 표식 그림은 PC 의 logo.VulcanMark 를 구운 것(app/tools/make_assets.py).

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'dart:io';

import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:path_provider/path_provider.dart';

import 'outbox.dart';
import 'vc_api.dart';
import 'pick.dart';
import 'templates.dart';
import 'prefs.dart';
import 'alarms.dart';
import 'shortcuts.dart';
import 'ocr.dart';
import 'recorder.dart';

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

// 카드 색(편의 기능 30번 · 킵) — 서버 Notes.COLORS 와 같은 이름
const cardColors = {
  '빨강': Color(0xFFE5484D),
  '주황': Color(0xFFF76B15),
  '노랑': Color(0xFFFFC53D),
  '초록': Color(0xFF30A46C),
  '파랑': Color(0xFF3E63DD),
  '보라': Color(0xFF8E4EC6),
  '회색': Color(0xFF8B8D98),
};

const _store = FlutterSecureStorage();
const _pairKey = 'vc_pair';

// 계기판 글씨. ★ 'monospace' 글꼴은 한글을 한 칸씩 벌려 「창 고 앞 머 리」가 됐다(에뮬레이터로 봄) —
//   기본 글꼴 + 숫자 폭 고정으로 같은 느낌만 낸다.
TextStyle _mono(double size, Color color, {FontWeight weight = FontWeight.w500}) => TextStyle(
  fontSize: size,
  color: color,
  letterSpacing: .6,
  fontWeight: weight,
  fontFeatures: const [FontFeature.tabularFigures()],
);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      statusBarBrightness: Brightness.dark,
      systemNavigationBarColor: _panel,
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );
  runApp(const VcApp());
}

ThemeData _theme() {
  OutlineInputBorder edge(Color c, [double w = 1]) => OutlineInputBorder(
    borderRadius: BorderRadius.circular(14),
    borderSide: BorderSide(color: c, width: w),
  );
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: _bg,
    colorScheme: const ColorScheme.dark(
      primary: _accent,
      onPrimary: Colors.black,
      secondary: _accent,
      surface: _panel,
      onSurface: _text,
      error: _warn,
    ),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: _accent,
      selectionColor: _accent.withValues(alpha: .3),
      selectionHandleColor: _accent,
    ),
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
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: _accent,
        side: BorderSide(color: _accent.withValues(alpha: .5)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: _panel,
      indicatorColor: _accent.withValues(alpha: .16),
      height: 66,
      iconTheme: WidgetStateProperty.resolveWith(
        (s) => IconThemeData(color: s.contains(WidgetState.selected) ? _accent : _muted),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (s) => TextStyle(fontSize: 12, color: s.contains(WidgetState.selected) ? _text : _muted),
      ),
    ),
    appBarTheme: const AppBarTheme(backgroundColor: Colors.transparent, foregroundColor: _text, elevation: 0),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: _card,
      contentTextStyle: TextStyle(color: _text),
      behavior: SnackBarBehavior.floating,
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: _card,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: _accent),
    popupMenuTheme: const PopupMenuThemeData(color: _card),
  );
}

class VcApp extends StatelessWidget {
  const VcApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'VC',
    debugShowCheckedModeBanner: false,
    theme: _theme(),
    // 날짜·때 고르개 단추가 영어(OK·Cancel)로 떴다 — 한국어로
    locale: const Locale('ko'),
    supportedLocales: const [Locale('ko'), Locale('en')],
    localizationsDelegates: const [
      GlobalMaterialLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
    ],
    home: const Root(),
  );
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
        center: Alignment(0, -0.6),
        radius: 1.15,
        colors: [_glow, _bg, _deep],
        stops: [0, .55, 1],
      ),
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
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2600));

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
      return Opacity(
        opacity: .8 + .2 * t,
        child: Transform.scale(scale: .97 + .05 * t, child: child),
      );
    },
    child: Image.asset(_markAsset, width: widget.size, height: widget.size, filterQuality: FilterQuality.medium),
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
    child: Row(
      children: [
        Text('// $text', style: _mono(11, _accent.withValues(alpha: .8), weight: FontWeight.w700)),
        const SizedBox(width: 10),
        Expanded(
          child: Container(
            height: 1,
            decoration: BoxDecoration(
              gradient: LinearGradient(colors: [_accent.withValues(alpha: .35), Colors.transparent]),
            ),
          ),
        ),
        if (trailing != null) ...[const SizedBox(width: 10), Text(trailing!, style: _mono(11, _muted))],
      ],
    ),
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
  Outbox? _outbox;
  AppPrefs? _prefs;
  AlarmBook? _alarms;
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
    // 전송 대기함은 짝과 따로 산다 — 연결을 지워도 안 보낸 글은 남는다
    Directory where;
    try {
      where = await getApplicationSupportDirectory();
    } catch (_) {
      where = await getApplicationDocumentsDirectory();
    }
    final outbox = await Outbox.open(File('${where.path}/vc_outbox.json'));
    final prefs = await AppPrefs.open(File('${where.path}/vc_settings.json'));
    final alarms = await AlarmBook.open(File('${where.path}/vc_alarms.json'), PhoneNotifier());
    await atLeast;
    if (!mounted) return;
    setState(() {
      _pairing = saved == null ? null : Pairing.parse(saved);
      _outbox = outbox;
      _prefs = prefs;
      _alarms = alarms;
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
        title: const Text('이 컴퓨터에 연결할까?', style: TextStyle(color: _text, fontSize: 19)),
        content: Text(p.label, style: _mono(15, _accent)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('아니', style: TextStyle(color: _muted)),
          ),
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
            outbox: _outbox!,
            prefs: _prefs,
            alarms: _alarms,
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
          child: Column(
            children: [
              const Spacer(flex: 3),
              const VcMark(size: 230),
              const Padding(
                padding: EdgeInsets.only(left: 16), // 글자 사이를 벌리면 뒤에 한 칸이 붙는다 — 가운데를 맞춘다
                child: Text(
                  'VC',
                  style: TextStyle(fontSize: 46, fontWeight: FontWeight.w300, letterSpacing: 16, color: _text),
                ),
              ),
              const SizedBox(height: 6),
              Text('VULCAN · 내 기억 창고', style: _mono(12, _muted)),
              const Spacer(flex: 4),
              Text('// 컴퓨터를 찾는 중', style: _mono(11, _accent.withValues(alpha: .75))),
              const SizedBox(height: 12),
              SizedBox(
                width: 120,
                child: LinearProgressIndicator(
                  minHeight: 2,
                  color: _accent,
                  backgroundColor: _accent.withValues(alpha: .12),
                ),
              ),
              const SizedBox(height: 52),
            ],
          ),
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
        child: ListView(
          padding: const EdgeInsets.fromLTRB(22, 18, 22, 32),
          children: [
            const Center(child: VcMark(size: 150)),
            const Text(
              'PC·맥과 잇기',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 27, fontWeight: FontWeight.w600, color: _text),
            ),
            const SizedBox(height: 8),
            Text(
              '집 PC·맥의 VC 창고를 폰에서 보고,\n폰에서 적은 것을 거기에 남긴다.',
              textAlign: TextAlign.center,
              style: TextStyle(color: _dim.withValues(alpha: .7), height: 1.55),
            ),
            const SectionLabel('순서'),
            const _Panel(
              child: Column(
                children: [
                  _Step('01', 'PC·맥에서 VC 를 켠다', '폰과 컴퓨터 둘 다 테일스케일을 켠다'),
                  _Step('02', '설정 → 폰 연결 → 「QR 보이기」', 'QR 은 2분 뒤 사라진다'),
                  _Step('03', '아래 「QR 찍기」로 찍는다', '붙을 컴퓨터 주소를 한 번 확인한다', last: true),
                ],
              ),
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
              secondChild: Column(
                children: [
                  TextField(
                    controller: _typed,
                    style: _mono(13, _text),
                    // ★ 한글 자판으로 뜨면 영문 주소가 「세://…」로 깨졌다(시뮬레이터 점검 2026-09-18).
                    //   주소 자판 · 자동고침·추천 끔.
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    enableSuggestions: false,
                    textInputAction: TextInputAction.go,
                    onSubmitted: (v) => widget.onCode(v),
                    // ★ 키보드가 올라오면 아래 「연결」 단추가 깔려 안 보였다(아이폰 실기 2026-09-15).
                    //   칸 아래로 단추 높이만큼 더 보이게 끌어올린다.
                    scrollPadding: const EdgeInsets.only(bottom: 160),
                    decoration: InputDecoration(
                      hintText: 'http://컴퓨터주소:8765/app#t=…',
                      // 주소는 대개 복사해서 온다 — 한 번에 붙인다
                      suffixIcon: IconButton(
                        tooltip: '붙여넣기',
                        icon: const Icon(Icons.content_paste, color: _muted),
                        onPressed: () async {
                          final got = (await Clipboard.getData(Clipboard.kTextPlain))?.text;
                          if (got != null) _typed.text = got.trim();
                        },
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    height: 50,
                    child: OutlinedButton(onPressed: () => widget.onCode(_typed.text), child: const Text('연결')),
                  ),
                ],
              ),
            ),
          ],
        ),
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
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
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
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 1),
              Text(
                title,
                style: const TextStyle(color: _text, fontSize: 15.5, fontWeight: FontWeight.w500),
              ),
              const SizedBox(height: 3),
              Text(sub, style: const TextStyle(color: _muted, fontSize: 12.5)),
            ],
          ),
        ),
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
    backgroundColor: Colors.black,
    extendBodyBehindAppBar: true,
    appBar: AppBar(title: Text('// QR 찍기', style: _mono(14, _text))),
    body: Stack(
      fit: StackFit.expand,
      children: [
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
          child: Text(
            'PC·맥 화면의 QR 을 네모 안에 맞춰 줘',
            textAlign: TextAlign.center,
            style: TextStyle(color: _text, fontSize: 15),
          ),
        ),
      ],
    ),
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
  const Home({
    super.key,
    required this.api,
    required this.outbox,
    required this.onUnauthorized,
    required this.onUnpair,
    this.prefs,
    this.alarms,
    this.shortcuts = const HomeShortcuts(),
  });

  final VcApi api;
  final Outbox outbox;
  final VoidCallback onUnauthorized;
  final VoidCallback onUnpair;
  final AppPrefs? prefs;
  final AlarmBook? alarms; // 시간 알림(편의 기능 24번)
  final AppShortcuts shortcuts; // 홈 아이콘 길게 누르기

  @override
  State<Home> createState() => _HomeState();
}

// ★ 첫 화면은 목록 하나(노션·에버노트처럼) — 새 메모는 오른쪽 아래 단추로 **전체 화면**에서 쓴다.
//   전에는 「보기·적기」 두 탭에 적기 칸 · 보낸 기록이 한 화면에 몰려 비좁고 번잡했다(오너 실기 2026-09-18).
class _HomeState extends State<Home> with WidgetsBindingObserver {
  // 서식(5단계) — 못 닿아도 지난번 받은 틀로 적게, 대기함 옆에 받아 둔다.
  late final _book = TemplateBook(File('${widget.outbox.file.parent.path}/vc_templates.json'));
  final _list = GlobalKey<_BrowseTabState>();
  String _state = '컴퓨터에 잇는 중…';
  Color _dot = _muted;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _hello();
    widget.shortcuts.start((type) {
      if (!mounted) return;
      if (type == HomeShortcuts.fromTemplate) {
        _writeFromTemplate();
      } else if (type == HomeShortcuts.newMemo) {
        _write();
      }
    });
    // 열면 바로 새 메모(설정) — 첫 화면이 뜬 뒤에
    if (widget.prefs?.openNew == true) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _write();
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  // 앱으로 돌아오면 다시 잇고, 안 보낸 글을 보낸다
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _hello();
  }

  Future<void> _hello() async {
    try {
      final n = await widget.api.notes();
      _show(n == null ? '${widget.api.pairing.label} 에 이어짐' : '이어짐 · 창고 $n장', _accent);
      await _send();
    } catch (e) {
      _fail(e);
    }
  }

  /// 전송 대기함을 비운다. 못 닿으면 글은 폰에 남고 다음에 보낸다.
  Future<void> _send() async {
    final before = widget.outbox.pending;
    final r = await widget.outbox.flush(widget.api);
    if (r == FlushResult.done && widget.outbox.pending < before) {
      try {
        final n = await widget.api.notes();
        if (n != null) _show('이어짐 · 창고 $n장', _accent);
      } catch (_) {
        // 세기만 실패 — 글은 이미 보냈다
      }
    }
    if (r == FlushResult.unauthorized) {
      widget.onUnauthorized();
    } else if (r == FlushResult.offline) {
      final why = widget.outbox.offlineReason;
      _show('컴퓨터에 못 닿았어${why.isEmpty ? '' : ' ($why)'} — 쓴 글은 폰에 두고 연결되면 보낸다', _warn);
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
      final why = e.reason.isEmpty ? '' : ' (${e.reason})';
      _show('컴퓨터에 못 닿았어$why — 테일스케일·VC 켜짐을 봐 줘', _warn);
    } else if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  /// 새 메모 · 이어 쓰기 — 전체 화면 편집기. 저장하면 곧장 돌아오고, 보내기는 뒤에서 한다.
  /// 「새 메모」를 길게 누르면 — 서식을 골라 채운 틀로 새 글(편의 기능 7번 · 단추를 늘리지 않는다 — 결정 26).
  Future<void> _writeFromTemplate() async {
    final (List<Tpl>, bool) got;
    try {
      got = await _book.load(widget.api);
    } catch (_) {
      return;
    }
    if (!mounted) return;
    if (got.$1.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('서식이 없어 — 컴퓨터 VC 창고 _서식/ 에 md 로 만든다')));
      return;
    }
    final chosen = await showModalBottomSheet<Tpl>(
      context: context,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
              child: Text(got.$2 ? '서식으로 새 메모 — 지난번 받은 서식' : '서식으로 새 메모', style: _mono(12, _muted)),
            ),
            for (final t in got.$1)
              ListTile(
                leading: const Icon(Icons.dashboard_customize_outlined, color: _accent),
                title: Text(t.name, style: const TextStyle(color: _text)),
                onTap: () => Navigator.pop(c, t),
              ),
          ],
        ),
      ),
    );
    if (chosen == null || !mounted) return;
    await _write(startBody: fillSlots(chosen.body));
  }

  Future<void> _write({String? title, String? startBody}) async {
    final item = await Navigator.push<OutboxItem>(
      context,
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => EditorPage(
          outbox: widget.outbox,
          onSend: _send,
          templates: () => _book.load(widget.api),
          fixedTitle: title,
          startBody: startBody,
        ),
      ),
    );
    if (item == null || !mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 2),
        content: Text(title == null ? '「${item.title}」 저장했어 — 연결되면 컴퓨터에 보낸다' : '「$title」 끝에 이어 붙였어'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Backdrop(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 6, 4, 0),
              child: Row(
                children: [
                  const Image(image: AssetImage(_markSolid), width: 28, height: 28),
                  const SizedBox(width: 10),
                  Expanded(
                    // 늘 보이는 한 줄(결정 17): 연결 · 보낼 것. 누르면 「상태·기록」.
                    child: InkWell(
                      borderRadius: BorderRadius.circular(8),
                      onTap: () => _openStatus(context),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Row(
                          children: [
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
                              child: Text(_state, style: _mono(11.5, _muted), overflow: TextOverflow.ellipsis),
                            ),
                            ListenableBuilder(
                              listenable: widget.outbox,
                              builder: (_, _) => widget.outbox.pending == 0
                                  ? const SizedBox.shrink()
                                  : Padding(
                                      padding: const EdgeInsets.only(left: 8),
                                      child: Text('보낼 것 ${widget.outbox.pending}', style: _mono(11.5, _warn)),
                                    ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  PopupMenuButton<String>(
                    icon: const Icon(Icons.more_vert, color: _muted),
                    onSelected: (v) {
                      if (v == 'status') {
                        _openStatus(context);
                      } else if (v == 'daily') {
                        _openDaily();
                      } else if (v == 'folders') {
                        _openFolders();
                      } else if (v == 'archive') {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => Backdrop(
                              child: Scaffold(
                                backgroundColor: Colors.transparent,
                                appBar: AppBar(title: const Text('보관함')),
                                body: BrowseTab(api: widget.api, onFail: _fail, archived: true),
                              ),
                            ),
                          ),
                        ).then((_) => _list.currentState?._find());
                      } else if (v == 'trash') {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => TrashPage(api: widget.api, onFail: _fail),
                          ),
                        ).then((_) => _list.currentState?._find());
                      } else if (v == 'settings') {
                        final pr = widget.prefs;
                        if (pr != null) {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => SettingsPage(prefs: pr, alarms: widget.alarms),
                            ),
                          );
                        }
                      } else if (v == 'send') {
                        _send();
                      } else {
                        widget.onUnpair();
                      }
                    },
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'send', child: Text('지금 보내기')),
                      PopupMenuItem(value: 'daily', child: Text('오늘 일지')),
                      PopupMenuItem(value: 'folders', child: Text('폴더')),
                      PopupMenuItem(value: 'archive', child: Text('보관함')),
                      PopupMenuItem(value: 'trash', child: Text('휴지통')),
                      PopupMenuItem(value: 'status', child: Text('상태·기록')),
                      PopupMenuItem(value: 'settings', child: Text('설정')),
                      PopupMenuItem(value: 'unpair', child: Text('연결 지우기')),
                    ],
                  ),
                ],
              ),
            ),
            Expanded(
              child: BrowseTab(
                key: _list,
                api: widget.api,
                onFail: _fail,
                outbox: widget.outbox,
                alarms: widget.alarms,
                prefs: widget.prefs,
                onAppend: (t) => _write(title: t),
                onSaveLine: (t, line) async {
                  await widget.outbox.add(t, line);
                  _send();
                },
              ),
            ),
          ],
        ),
      ),
      // 누르면 빈 메모 · 길게 누르면 서식으로 새 메모
      floatingActionButton: GestureDetector(
        onLongPress: _writeFromTemplate,
        child: FloatingActionButton.extended(
          onPressed: _write,
          // ★ 도움말(tooltip)을 달면 길게 누르기를 도움말이 먼저 가져가 서식 목록이 안 뜬다
          icon: const Icon(Icons.edit_outlined),
          label: const Text('새 메모', style: TextStyle(fontWeight: FontWeight.w700)),
        ),
      ),
    ),
  );

  /// 오늘 일지(편의 기능 23번) — 없으면 컴퓨터가 만들고 그 글을 연다.
  Future<void> _openDaily() async {
    String title;
    try {
      title = await widget.api.daily();
    } catch (e) {
      _fail(e);
      return;
    }
    if (title.isEmpty || !mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => NotePage(
          api: widget.api,
          onFail: _fail,
          title: title,
          onAppend: (x) => _write(title: x),
          onSaveLine: (x, line) async {
            await widget.outbox.add(x, line);
            _send();
          },
          alarms: widget.alarms,
        ),
      ),
    );
    if (mounted) _list.currentState?._find();
  }

  /// 폴더 보기(편의 기능 29번) — 고르면 그 폴더만 본다(`path:` 로 좁힌다).
  Future<void> _openFolders() async {
    List<Map<String, dynamic>> rows;
    try {
      rows = await widget.api.folders();
    } catch (e) {
      _fail(e);
      return;
    }
    if (!mounted) return;
    final got = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
              child: Text('폴더 — 고르면 그 폴더만 본다', style: _mono(12, _muted)),
            ),
            for (final r in rows)
              ListTile(
                leading: const Icon(Icons.folder_outlined, color: _accent),
                title: Text('${r['path']}', style: const TextStyle(color: _text)),
                trailing: Text('${r['notes']}장', style: _mono(11, _muted)),
                onTap: () => Navigator.pop(c, '${r['path']}'),
              ),
          ],
        ),
      ),
    );
    if (got == null || !mounted) return;
    _list.currentState?._openFolder(got);
  }

  void _openStatus(BuildContext context) => Navigator.push(
    context,
    MaterialPageRoute(
      builder: (_) => StatusPage(api: widget.api, outbox: widget.outbox),
    ),
  );
}

/// 휴지통(편의 기능 28번) — 지운 글. 눌러서 되살린다.
class TrashPage extends StatefulWidget {
  const TrashPage({super.key, required this.api, required this.onFail});

  final VcApi api;
  final OnFail onFail;

  @override
  State<TrashPage> createState() => _TrashPageState();
}

class _TrashPageState extends State<TrashPage> {
  List<Map<String, dynamic>>? _rows;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.trash();
      if (mounted) setState(() => _rows = r);
    } catch (e) {
      widget.onFail(e);
      if (mounted) setState(() => _rows = []);
    }
  }

  Future<void> _restore(Map<String, dynamic> row) async {
    try {
      await widget.api.restore('${row['id']}');
    } catch (e) {
      widget.onFail(e);
      return;
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text('「${row['title']}」 되살렸어')));
    _load();
  }

  @override
  Widget build(BuildContext context) => Backdrop(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(title: const Text('휴지통')),
      body: _rows == null
          ? const Center(child: CircularProgressIndicator())
          : _rows!.isEmpty
          ? const Center(
              child: Text('비었어', style: TextStyle(color: _muted)),
            )
          : ListView(
              children: [
                for (final r in _rows!)
                  ListTile(
                    title: Text('${r['title']}', style: const TextStyle(color: _text)),
                    subtitle: Text('지운 때 ${r['when']}', style: _mono(11, _muted)),
                    trailing: TextButton(onPressed: () => _restore(r), child: const Text('되살리기')),
                  ),
              ],
            ),
    ),
  );
}

/// 설정 — ⋮ 안(결정 26). 늘어나는 켜고 끄기는 여기에 모은다.
class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key, required this.prefs, this.alarms});

  final AppPrefs prefs;
  final AlarmBook? alarms;

  @override
  Widget build(BuildContext context) => Backdrop(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(title: const Text('설정')),
      body: ListenableBuilder(
        listenable: prefs,
        builder: (_, _) => ListView(
          children: [
            const SectionLabel('적기'),
            SwitchListTile(
              value: prefs.openNew,
              onChanged: prefs.setOpenNew,
              activeThumbColor: _accent,
              title: const Text('앱을 열면 바로 새 메모', style: TextStyle(color: _text)),
              subtitle: const Text('목록 대신 빈 메모로 시작한다(구글 킵처럼)', style: TextStyle(color: _muted)),
            ),
            // 걸어 둔 시간 알림(편의 기능 24번) — 여기서 보고 지운다
            if (alarms != null) ...[
              const SectionLabel('걸어 둔 알림'),
              ListenableBuilder(
                listenable: alarms!,
                builder: (_, _) => Column(
                  children: [
                    if (alarms!.items.isEmpty)
                      const Padding(
                        padding: EdgeInsets.fromLTRB(16, 4, 16, 12),
                        child: Align(
                          alignment: Alignment.centerLeft,
                          child: Text('없음 — 글 보기 ⋮ › 알림 맞추기', style: TextStyle(color: _muted)),
                        ),
                      ),
                    for (final a in alarms!.items)
                      ListTile(
                        leading: const Icon(Icons.alarm, color: _accent),
                        title: Text(a.title, style: const TextStyle(color: _text)),
                        subtitle: Text(
                          '${a.when.month}월 ${a.when.day}일 ${a.when.hour}시 ${a.when.minute.toString().padLeft(2, '0')}',
                          style: _mono(11, _muted),
                        ),
                        trailing: IconButton(
                          tooltip: '지우기',
                          icon: const Icon(Icons.close, color: _muted),
                          onPressed: () => alarms!.remove(a),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    ),
  );
}

/// 눌러야 펴지는 「상태·기록」(결정 17 ③). 늘 보이는 한 줄에 못 담는 자세한 것 —
/// 보낼 글과 그 까닭, 컴퓨터가 켜진 지, 죽음 기록, 최근 자국. 컴퓨터 쪽 글 이름·집 경로는 서버가 가려서 준다.
class StatusPage extends StatefulWidget {
  const StatusPage({super.key, required this.api, required this.outbox});

  final VcApi api;
  final Outbox outbox;

  @override
  State<StatusPage> createState() => _StatusPageState();
}

class _StatusPageState extends State<StatusPage> {
  Map<String, dynamic>? _s;
  String? _why;
  // 컴퓨터에서 도는 확장(편의 기능 31번 · 결정 23). 폰은 **보기만** 한다 — 단추를 새로 달지 않는다(결정 26).
  List<Map<String, dynamic>> _plugins = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await widget.api.status();
      // 확장 목록은 곁가지다 — 못 받아도 상태 화면은 그대로 뜬다(옛 VC 는 이 길이 없어 404 를 준다).
      List<Map<String, dynamic>> ext = const [];
      try {
        ext = await widget.api.plugins();
      } on VcError {
        ext = const [];
      }
      if (mounted) {
        setState(() {
          _s = s;
          _plugins = ext;
          _why = null;
        });
      }
    } on VcOffline catch (e) {
      if (mounted) setState(() => _why = '컴퓨터에 못 닿았어${e.reason.isEmpty ? '' : ' (${e.reason})'}');
    } on VcUnauthorized {
      if (mounted) setState(() => _why = '열쇠가 안 맞아 — 다시 짝지어 줘');
    } on VcError catch (e) {
      if (mounted) setState(() => _why = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _s;
    final waiting = widget.outbox.items.where((i) => !i.sent).toList();
    final trail = (s?['trail'] as List?) ?? const [];
    final deaths = (s?['deaths'] as num?)?.toInt() ?? 0;
    final up = (s?['uptime_s'] as num?)?.toInt();
    return Backdrop(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(backgroundColor: Colors.transparent, title: const Text('상태·기록')),
        body: RefreshIndicator(
          color: _accent,
          backgroundColor: _card,
          onRefresh: _load,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
            children: [
              SectionLabel('보낼 것', trailing: '${waiting.length}개'),
              // 보낼 글 — 전에는 적기 탭 아래에 있었다. 무엇이 남았는지 본문 첫 줄까지 보인다.
              for (final w in waiting)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${w.title.isEmpty ? '(제목 없음)' : w.title} · 시도 ${w.attempts}${w.files.isEmpty ? '' : ' · 📎${w.files.length}'}',
                        style: _mono(11.5, _text),
                      ),
                      if (w.text.trim().isNotEmpty)
                        Text(
                          w.text.trim().split('\n').first,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: _muted, fontSize: 13),
                        ),
                      if (w.error != null) Text(w.error!, style: _mono(11, _warn)),
                    ],
                  ),
                ),
              if (waiting.isNotEmpty)
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    onPressed: () async {
                      await widget.outbox.flush(widget.api);
                      if (mounted) setState(() {});
                    },
                    icon: const Icon(Icons.sync, size: 16, color: _accent),
                    label: Text('지금 보내기', style: _mono(12, _accent)),
                  ),
                ),
              SectionLabel('컴퓨터', trailing: up == null ? '—' : '켠 지 ${up ~/ 60}분'),
              if (_why != null) Text(_why!, style: _mono(11, _warn)),
              if (deaths > 0) Text('⚠ 죽음 기록 $deaths줄 — 컴퓨터 VC 에서 「문제 알리기」', style: _mono(11, _warn)),
              if (_plugins.isNotEmpty)
                SectionLabel('확장', trailing: '${_plugins.where((p) => p['on'] == true).length}개 켜짐'),
              for (final p in _plugins)
                Text(
                  '${p['on'] == true ? '● ' : '○ '}${p['name']}'
                  '${(p['error'] as String?)?.isNotEmpty == true ? ' — 못 실었어' : ''}',
                  style: _mono(11, p['on'] == true ? _text : _muted),
                ),
              if (_plugins.isNotEmpty) Text('확장은 컴퓨터에서만 돌아 — 켜고 끄는 건 컴퓨터 VC 설정 「확장」', style: _mono(10, _muted)),
              SectionLabel('최근 기록', trailing: '${trail.length}줄'),
              for (final t in trail.reversed) Text('$t', style: _mono(10, _muted)),
            ],
          ),
        ),
      ),
    );
  }
}

/// 날짜(`2026-09-17`)를 사람 말로 — 오늘 · 어제 · 9월 17일 · 2025.9.17.
String whenLabel(String ymd, {DateTime? now}) {
  final d = DateTime.tryParse(ymd);
  if (d == null) return ymd;
  final n = now ?? DateTime.now();
  final days = DateTime(n.year, n.month, n.day).difference(DateTime(d.year, d.month, d.day)).inDays;
  if (days == 0) return '오늘';
  if (days == 1) return '어제';
  if (d.year == n.year) return '${d.month}월 ${d.day}일';
  return '${d.year}.${d.month}.${d.day}';
}

class BrowseTab extends StatefulWidget {
  const BrowseTab({
    super.key,
    required this.api,
    required this.onFail,
    this.outbox,
    this.onAppend,
    this.onSaveLine,
    this.alarms,
    this.prefs,
    this.archived = false,
  });

  final VcApi api;
  final OnFail onFail;
  final Outbox? outbox; // 폰 글을 보내면 목록을 다시 부른다
  final void Function(String title)? onAppend; // 글 보기의 「이어 쓰기」
  final Future<void> Function(String title, String line)? onSaveLine; // 글 보기의 칸 고치기
  final AlarmBook? alarms; // 글 보기의 시간 알림
  final AppPrefs? prefs; // 스마트 폴더(편의 기능 25번)
  final bool archived; // 보관함으로 쓸 때

  @override
  State<BrowseTab> createState() => _BrowseTabState();
}

// ★ 목록 위 칩으로 **골라 보기**(전체 · 사진 · #태그). 전에는 다 한꺼번에 섞여 찾기 힘들었다(오너 실기 2026-09-16).
class _BrowseTabState extends State<BrowseTab> {
  static const _photo = '@photo';

  final _q = TextEditingController();
  List<Map<String, dynamic>> _hits = [];
  String _asked = '';
  String? _empty;
  bool _busy = false;
  // ★ 못 닿았을 때 「창고 앞머리 0장」이 떠, 창고가 빈 것처럼 보였다(2026-09-15 아이폰 실기). 못 센 것은 0 이 아니다.
  bool _offline = false;
  String _filter = ''; // '' 전체 · _photo 사진 · 그 밖은 태그 이름
  List<String> _tags = []; // 칩으로 보일 태그 — 전체 목록에서 많이 쓴 차례

  int _sentSeen = 0;

  @override
  void initState() {
    super.initState();
    _sentSeen = _sentCount();
    widget.outbox?.addListener(_onOutbox);
    _find();
  }

  @override
  void dispose() {
    widget.outbox?.removeListener(_onOutbox);
    _q.dispose();
    super.dispose();
  }

  int _sentCount() => widget.outbox?.items.where((i) => i.sent).length ?? 0;

  // ★ 목록은 켤 때 한 번 불렀다 — 그 뒤 대기함이 글을 보내도 「0장 · 안 나왔어」가 남았다(에뮬레이터로 봄)
  void _onOutbox() {
    final n = _sentCount();
    if (n != _sentSeen) {
      _sentSeen = n;
      if (!_busy) _find();
    }
  }

  int _asking = 0; // 마지막 물음 번호 — 늦게 온 옛 답이 새 목록을 덮지 않게

  /// 목록이 빈 **까닭**. 화면마다 다르다 — 보관함에서 「창고가 비었어 · 아래 새 메모로」 라고 말하면
  /// 거짓말이다(창고에는 글이 있고, 그 화면에는 「새 메모」 단추도 없다. 2026-09-18 시뮬레이터에서 봤다).
  String _emptyWhy(String ask) {
    if (_filter == _photo) return widget.archived ? '보관한 글 중에 사진 붙은 것이 없어' : '사진 붙은 글이 없어';
    if (ask.isNotEmpty) return widget.archived ? '보관함에서 못 찾았어 — 말을 바꿔 봐' : '안 나왔어 — 말을 바꿔 봐';
    return widget.archived ? '보관한 글이 없어 — 카드를 길게 눌러 「보관」하면 여기로 와' : '아직 창고가 비었어 — 아래 「새 메모」로 시작';
  }

  Future<void> _find() async {
    final q = _q.text.trim();
    final mine = ++_asking;
    final tag = (_filter.isEmpty || _filter == _photo) ? '' : _filter;
    final ask = [q, if (tag.isNotEmpty) 'tag:$tag'].where((s) => s.isNotEmpty).join(' ');
    setState(() => _busy = true);
    try {
      final r = await widget.api.search(ask, k: 50, archived: widget.archived);
      if (!mounted || mine != _asking) return;
      final picked = _filter == _photo ? r.where((h) => h['image'] != null).toList() : r;
      // 고정한 글이 맨 위(킵·애플 노트) — 나머지 차례는 그대로
      final shown = [...picked.where((h) => h['pinned'] == true), ...picked.where((h) => h['pinned'] != true)];
      setState(() {
        _hits = shown;
        _asked = q;
        _offline = false;
        _empty = shown.isEmpty ? _emptyWhy(ask) : null;
        // 칩은 아무것도 안 좁혔을 때의 목록으로 세운다 — 좁힌 뒤에 다시 세면 칩이 사라진다
        if (ask.isEmpty) {
          final count = <String, int>{};
          for (final h in r) {
            for (final t in (h['tags'] as List?)?.whereType<String>() ?? const <String>[]) {
              count[t] = (count[t] ?? 0) + 1;
            }
          }
          _tags = (count.keys.toList()..sort((a, b) => count[b]!.compareTo(count[a]!))).take(12).toList();
        }
      });
    } catch (e) {
      if (e is VcOffline && mounted) {
        setState(() {
          _offline = true;
          _hits = [];
          _empty = '컴퓨터에 못 닿아 창고를 못 불렀어 — 당겨서 다시';
        });
      }
      widget.onFail(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 표시 바꾸기 — 바꾸고 목록을 다시 부른다. 실패하면 까닭.
  Future<void> _mark(String title, {bool? pinned, bool? archived, String? color, bool delete = false}) async {
    try {
      if (delete) {
        await widget.api.delete(title);
      } else {
        await widget.api.mark(title, pinned: pinned, archived: archived, color: color);
      }
    } catch (e) {
      widget.onFail(e);
      return;
    }
    if (!mounted) return;
    final said = delete
        ? '「$title」 휴지통으로 — ⋮ › 휴지통에서 되살린다'
        : archived == true
        ? '「$title」 보관함으로'
        : archived == false
        ? '「$title」 목록으로 꺼냈어'
        : pinned != null
        ? (pinned ? '「$title」 맨 위에 고정' : '고정 풀었어')
        : '색을 바꿨어';
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(duration: const Duration(seconds: 2), content: Text(said)));
    _find();
  }

  /// 옆으로 밀기 — 오른쪽 고정 · 왼쪽 보관(보관함에서는 왼쪽 꺼내기).
  Widget _swipe(Map<String, dynamic> h, Widget card) {
    final title = '${h['title']}';
    final pinned = h['pinned'] == true;
    Widget bg(IconData icon, String label, Alignment at, Color c) => Container(
      alignment: at,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 22),
      decoration: BoxDecoration(color: c.withValues(alpha: .25), borderRadius: BorderRadius.circular(14)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: _text, size: 20),
          const SizedBox(width: 6),
          Text(label, style: const TextStyle(color: _text)),
        ],
      ),
    );
    return Dismissible(
      key: ValueKey('swipe/${h['folder'] ?? ''}/$title'),
      background: widget.archived
          ? bg(Icons.unarchive_outlined, '꺼내기', Alignment.centerLeft, _accent)
          : bg(
              pinned ? Icons.push_pin_outlined : Icons.push_pin,
              pinned ? '고정 풀기' : '고정',
              Alignment.centerLeft,
              _accent,
            ),
      secondaryBackground: widget.archived ? null : bg(Icons.archive_outlined, '보관', Alignment.centerRight, _muted),
      direction: widget.archived ? DismissDirection.startToEnd : DismissDirection.horizontal,
      confirmDismiss: (dir) async {
        if (widget.archived) {
          await _mark(title, archived: false);
          return true;
        }
        if (dir == DismissDirection.startToEnd) {
          await _mark(title, pinned: !pinned);
          return false; // 고정은 목록에 남는다
        }
        await _mark(title, archived: true);
        return true;
      },
      child: card,
    );
  }

  /// 카드 길게 누르기 — 고정 · 보관 · 색 · 지우기(결정 26).
  Future<void> _cardMenu(Map<String, dynamic> h) async {
    final title = '${h['title']}';
    final pinned = h['pinned'] == true;
    final got = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
              child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: _mono(12.5, _muted)),
            ),
            ListTile(
              leading: Icon(pinned ? Icons.push_pin_outlined : Icons.push_pin, color: _accent),
              title: Text(pinned ? '고정 풀기' : '맨 위에 고정', style: const TextStyle(color: _text)),
              onTap: () => Navigator.pop(c, 'pin'),
            ),
            ListTile(
              leading: Icon(widget.archived ? Icons.unarchive_outlined : Icons.archive_outlined, color: _accent),
              title: Text(widget.archived ? '목록으로 꺼내기' : '보관', style: const TextStyle(color: _text)),
              onTap: () => Navigator.pop(c, 'archive'),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: Wrap(
                spacing: 10,
                children: [
                  for (final e in cardColors.entries)
                    InkWell(
                      customBorder: const CircleBorder(),
                      onTap: () => Navigator.pop(c, 'color:${e.key}'),
                      child: Tooltip(
                        message: e.key,
                        child: CircleAvatar(
                          radius: 14,
                          backgroundColor: e.value,
                          child: h['color'] == e.key ? const Icon(Icons.check, size: 16, color: Colors.white) : null,
                        ),
                      ),
                    ),
                  InkWell(
                    customBorder: const CircleBorder(),
                    onTap: () => Navigator.pop(c, 'color:'),
                    child: const Tooltip(
                      message: '색 없음',
                      child: CircleAvatar(
                        radius: 14,
                        backgroundColor: _panel,
                        child: Icon(Icons.block, size: 16, color: _muted),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: _warn),
              title: const Text('지우기(휴지통)', style: TextStyle(color: _warn)),
              onTap: () => Navigator.pop(c, 'delete'),
            ),
          ],
        ),
      ),
    );
    if (got == null || !mounted) return;
    if (got == 'pin') {
      await _mark(title, pinned: !pinned);
    } else if (got == 'archive') {
      await _mark(title, archived: !widget.archived);
    } else if (got == 'delete') {
      await _mark(title, delete: true);
    } else if (got.startsWith('color:')) {
      await _mark(title, color: got.substring(6));
    }
  }

  /// 지금 보기를 이름 붙여 저장(편의 기능 25번 · 애플 노트 스마트 폴더).
  Future<void> _saveSmart() async {
    final book = widget.prefs;
    if (book == null) return;
    final guess = _q.text.trim().isNotEmpty ? _q.text.trim() : (_filter == _photo ? '사진' : _filter);
    final ctl = TextEditingController(text: guess);
    final name = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('이 보기를 무엇으로 부를까'),
        content: TextField(controller: ctl, autofocus: true, onSubmitted: (v) => Navigator.pop(c, v)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('그만')),
          TextButton(onPressed: () => Navigator.pop(c, ctl.text), child: const Text('저장')),
        ],
      ),
    );
    // ★ 창이 닫히는 애니메이션이 끝나기 전에 없애면 「disposed 된 것을 썼다」로 터진다 — 한 박자 뒤에
    Future<void>.delayed(const Duration(milliseconds: 400), ctl.dispose);
    if (name == null || name.trim().isEmpty || !mounted) return;
    await book.addSmart(SmartFolder(name: name.trim(), q: _q.text.trim(), filter: _filter));
    if (!mounted) return;
    setState(() {});
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text('「${name.trim()}」 로 저장했어 — 칩에서 다시 불러')));
  }

  Future<void> _dropSmart(SmartFolder f) async {
    final book = widget.prefs;
    if (book == null) return;
    await book.removeSmart(f.name);
    if (mounted) setState(() {});
  }

  /// 폴더로 좁혀 본다(편의 기능 29번). 찾기 문법 `path:` 를 쓴다.
  void _openFolder(String path) {
    _q.text = path == '/' ? '' : 'path:$path';
    setState(() => _filter = '');
    _find();
  }

  void _pickFilter(String v) {
    setState(() => _filter = _filter == v ? '' : v);
    _find();
  }

  Widget _chip(String label, String value) {
    final on = _filter == value;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: ChoiceChip(
        label: Text(label),
        selected: on,
        showCheckmark: false,
        onSelected: (_) => _pickFilter(value),
        labelStyle: TextStyle(
          color: on ? _text : _dim,
          fontSize: 13,
          fontWeight: on ? FontWeight.w700 : FontWeight.w500,
        ),
        selectedColor: _accent.withValues(alpha: .28),
        backgroundColor: _card,
        side: BorderSide(color: on ? _accent.withValues(alpha: .7) : _accent.withValues(alpha: .12)),
        shape: const StadiumBorder(),
        visualDensity: VisualDensity.compact,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final what = _asked.isNotEmpty
        ? '찾은 것'
        : _filter.isEmpty
        ? '최근'
        : (_filter == _photo ? '사진' : '#$_filter');
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
          child: TextField(
            controller: _q,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _find(),
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              hintText: '창고에서 찾기',
              isDense: true,
              prefixIcon: const Icon(Icons.search, color: _muted),
              suffixIcon: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // 지금 보기(찾는 말 + 칩)를 이름 붙여 저장 — 스마트 폴더(편의 기능 25번)
                  if (widget.prefs != null && (_q.text.trim().isNotEmpty || _filter.isNotEmpty))
                    IconButton(
                      tooltip: '이 보기 저장',
                      icon: const Icon(Icons.star_border, color: _muted),
                      onPressed: _saveSmart,
                    ),
                  if (_q.text.isNotEmpty)
                    IconButton(
                      tooltip: '지우기',
                      icon: const Icon(Icons.close, color: _muted),
                      onPressed: () {
                        _q.clear();
                        _find();
                      },
                    ),
                ],
              ),
            ),
          ),
        ),
        SizedBox(
          height: 48,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            children: [
              _chip('전체', ''),
              _chip('📷 사진', _photo),
              for (final t in _tags) _chip('#$t', t),
              // 저장해 둔 보기 — 누르면 그 조건으로, 길게 누르면 지운다
              for (final f in widget.prefs?.smart ?? const <SmartFolder>[])
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: GestureDetector(
                    onLongPress: () => _dropSmart(f),
                    child: ChoiceChip(
                      label: Text('⭐ ${f.name}'),
                      selected: _q.text.trim() == f.q && _filter == f.filter,
                      showCheckmark: false,
                      onSelected: (_) {
                        _q.text = f.q;
                        setState(() => _filter = f.filter);
                        _find();
                      },
                      labelStyle: const TextStyle(color: _dim, fontSize: 13),
                      backgroundColor: _card,
                      selectedColor: _accent.withValues(alpha: .28),
                      side: BorderSide(color: _accent.withValues(alpha: .18)),
                      shape: const StadiumBorder(),
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
                ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 2, 18, 4),
          child: Row(
            children: [
              Text(what, style: _mono(11.5, _accent.withValues(alpha: .85), weight: FontWeight.w700)),
              const Spacer(),
              Text(_busy ? '…' : (_offline ? '—' : '${_hits.length}장'), style: _mono(11.5, _muted)),
            ],
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            color: _accent,
            backgroundColor: _card,
            onRefresh: _find,
            child: ListView(
              // 오른쪽 아래 「새 메모」 단추에 마지막 카드가 안 가리게
              padding: const EdgeInsets.fromLTRB(12, 2, 12, 96),
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                if (_empty != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 40),
                    child: Column(
                      children: [
                        const Opacity(opacity: .3, child: Image(image: AssetImage(_markSolid), width: 72, height: 72)),
                        const SizedBox(height: 8),
                        Text(
                          _empty!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: _muted),
                        ),
                      ],
                    ),
                  ),
                for (final h in _hits)
                  _swipe(
                    h,
                    NoteCard(
                      // ★ 목록이 새로 불리는 사이 누른 카드를 놓치지 않게 — 자리 대신 글로 짝짓는다
                      key: ValueKey('${h['folder'] ?? ''}/${h['title']}'),
                      hit: h,
                      api: widget.api,
                      onLongPress: () => _cardMenu(h),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => NotePage(
                            api: widget.api,
                            onFail: widget.onFail,
                            title: '${h['title']}',
                            q: _asked,
                            folder: h['folder'] as String?,
                            onAppend: widget.onAppend,
                            onSaveLine: widget.onSaveLine,
                            alarms: widget.alarms,
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// 목록 한 장 — 제목 · 두 줄 미리보기 · 날짜·태그 · 오른쪽에 첫 사진.
class NoteCard extends StatelessWidget {
  const NoteCard({super.key, required this.hit, required this.onTap, this.api, this.onLongPress});

  final Map<String, dynamic> hit;
  final VoidCallback onTap;
  final VcApi? api;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final preview = '${hit['preview'] ?? hit['summary'] ?? ''}'.trim();
    final tags = (hit['tags'] as List?)?.whereType<String>().toList() ?? const <String>[];
    final image = hit['image'] as String?;
    final files = (hit['files'] as num?)?.toInt() ?? 0;
    final date = '${hit['updated'] ?? hit['created'] ?? ''}';
    final api = this.api;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: _card.withValues(alpha: .92),
        borderRadius: BorderRadius.circular(14),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          onLongPress: onLongPress,
          splashColor: _accent.withValues(alpha: .12),
          child: Container(
            // 카드 색은 왼쪽 띠로(킵)
            decoration: BoxDecoration(
              border: Border(left: BorderSide(color: cardColors[hit['color']] ?? Colors.transparent, width: 4)),
            ),
            padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          if (hit['pinned'] == true)
                            const Padding(
                              padding: EdgeInsets.only(right: 4),
                              child: Icon(Icons.push_pin, size: 14, color: _accent),
                            ),
                          Expanded(
                            child: Text(
                              '${hit['title']}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(color: _text, fontSize: 16, fontWeight: FontWeight.w600),
                            ),
                          ),
                        ],
                      ),
                      if (preview.isNotEmpty) ...[
                        const SizedBox(height: 3),
                        Text(
                          preview,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: _dim.withValues(alpha: .75), fontSize: 13.5, height: 1.4),
                        ),
                      ],
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 10,
                        runSpacing: 2,
                        children: [
                          if (date.isNotEmpty) Text(whenLabel(date), style: _mono(11, _muted)),
                          for (final t in tags.take(3)) Text('#$t', style: _mono(11, _accent.withValues(alpha: .8))),
                          if (files > 0 && image == null) Text('📎 $files', style: _mono(11, _muted)),
                        ],
                      ),
                    ],
                  ),
                ),
                if (image != null && api != null)
                  Padding(
                    padding: const EdgeInsets.only(left: 10),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: SizedBox(
                        width: 64,
                        height: 64,
                        child: Image.network(
                          api.attachmentUri(image).toString(),
                          headers: api.authHeaders,
                          fit: BoxFit.cover,
                          cacheWidth: 192,
                          semanticLabel: image,
                          errorBuilder: (_, _, _) => Container(
                            color: _panel,
                            child: const Icon(Icons.image_outlined, color: _muted, size: 22),
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class NotePage extends StatefulWidget {
  const NotePage({
    super.key,
    required this.api,
    required this.onFail,
    required this.title,
    this.q = '',
    this.folder,
    this.onAppend,
    this.onSaveLine,
    this.alarms,
  });

  final VcApi api;
  final OnFail onFail;
  final String title;
  final String q;
  final String? folder;
  final void Function(String title)? onAppend;
  // 한 줄을 이 글 끝에 덧붙인다(칸 고치기) — 폰에 먼저 저장하고 보낸다
  final Future<void> Function(String title, String line)? onSaveLine;
  // 시간 알림(편의 기능 24번). 없으면 메뉴에 안 뜬다.
  final AlarmBook? alarms;

  @override
  State<NotePage> createState() => _NotePageState();
}

class _NotePageState extends State<NotePage> {
  bool _thinking = false;

  /// 시간 알림 맞추기(편의 기능 24번) — 날·때를 고르면 폰이 그때 알려 준다.
  Future<void> _setAlarm() async {
    final book = widget.alarms;
    if (book == null) return;
    final now = DateTime.now();
    final day = await showDatePicker(
      context: context,
      initialDate: now.add(const Duration(days: 1)),
      firstDate: now,
      lastDate: DateTime(now.year + 5),
    );
    if (day == null || !mounted) return;
    final at = await showTimePicker(context: context, initialTime: const TimeOfDay(hour: 9, minute: 0));
    if (at == null || !mounted) return;
    final when = DateTime(day.year, day.month, day.day, at.hour, at.minute);
    final ok = await book.add(widget.title, when);
    if (!mounted) return;
    final mm = at.minute.toString().padLeft(2, '0'); // ★ Dart 는 한글 변수 이름을 못 쓴다
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(
            ok ? '${when.month}월 ${when.day}일 ${at.hour}시 $mm 에 알려 줄게' : '알림을 못 걸었어 — 아이폰 설정 › VC › 알림을 켜 줘',
          ),
        ),
      );
  }

  void _open(String title) => Navigator.push(
    context,
    MaterialPageRoute(
      builder: (_) => NotePage(
        api: widget.api,
        onFail: widget.onFail,
        title: title,
        onAppend: widget.onAppend,
        onSaveLine: widget.onSaveLine,
        alarms: widget.alarms,
      ),
    ),
  );

  /// AI 요약·번역 — 결과를 시트로 보이고, 원하면 글 끝에 붙인다.
  Future<void> _assist(String action) async {
    var lang = '영어';
    if (action == 'translate') {
      final got = await showModalBottomSheet<String>(
        context: context,
        backgroundColor: _card,
        builder: (c) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text('어느 말로 옮길까', style: _mono(12, _muted)),
              ),
              for (final l in const ['영어', '일본어', '중국어', '한국어'])
                ListTile(
                  title: Text(l, style: const TextStyle(color: _text)),
                  onTap: () => Navigator.pop(c, l),
                ),
            ],
          ),
        ),
      );
      if (got == null) return;
      lang = got;
    }
    if (!mounted) return;
    setState(() => _thinking = true);
    String text;
    try {
      text = await widget.api.assist(action, widget.title, lang: lang);
    } on VcError catch (e) {
      text = '';
      // 앞 알림 뒤에 줄 서지 않게 — 새 까닭은 바로 보인다
      if (mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(e.message)));
      }
    } catch (e) {
      text = '';
      widget.onFail(e);
    } finally {
      if (mounted) setState(() => _thinking = false);
    }
    if (text.isEmpty || !mounted) return;
    final head = action == 'summary' ? 'AI 요약' : 'AI 번역 ($lang)';
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(head, style: _mono(12, _accent, weight: FontWeight.w700)),
              const SizedBox(height: 8),
              ConstrainedBox(
                constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(c).height * .55),
                child: SingleChildScrollView(
                  child: SelectableText(text, style: const TextStyle(color: _text, height: 1.6)),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: text));
                      Navigator.pop(c);
                    },
                    child: const Text('복사'),
                  ),
                  if (widget.onSaveLine != null)
                    FilledButton(
                      onPressed: () async {
                        Navigator.pop(c);
                        await widget.onSaveLine!(widget.title, '## $head\n\n$text');
                        if (mounted) {
                          ScaffoldMessenger.of(context)
                            ..hideCurrentSnackBar()
                            ..showSnackBar(const SnackBar(content: Text('글 끝에 붙였어')));
                        }
                      },
                      child: const Text('글 끝에 붙이기'),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  late Future<Map<String, dynamic>> _note = _load();

  Future<Map<String, dynamic>> _load() =>
      widget.api.note(widget.title, q: widget.q, folder: widget.folder)..catchError((Object e) {
        widget.onFail(e);
        return <String, dynamic>{};
      });

  @override
  Widget build(BuildContext context) => Backdrop(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(widget.title, overflow: TextOverflow.ellipsis),
        // 드물게 쓰는 것은 ⋮ 안에(결정 26)
        actions: [
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert, color: _muted),
            onSelected: (v) => v == 'alarm' ? _setAlarm() : _assist(v),
            itemBuilder: (_) => [
              const PopupMenuItem(value: 'summary', child: Text('AI 요약')),
              const PopupMenuItem(value: 'translate', child: Text('AI 번역')),
              if (widget.alarms != null) const PopupMenuItem(value: 'alarm', child: Text('알림 맞추기')),
            ],
          ),
        ],
      ),
      floatingActionButton: widget.onAppend == null
          ? null
          : FloatingActionButton.extended(
              onPressed: () => widget.onAppend!(widget.title),
              icon: const Icon(Icons.add_comment_outlined),
              label: const Text('이어 쓰기', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
      bottomNavigationBar: _thinking ? const LinearProgressIndicator(minHeight: 2) : null,
      body: FutureBuilder<Map<String, dynamic>>(
        future: _note,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return const Center(
              child: Text('못 열었어', style: TextStyle(color: _muted)),
            );
          }
          final j = snap.data ?? {};
          return RefreshIndicator(
            color: _accent,
            backgroundColor: _card,
            onRefresh: () async {
              // ★ 화살표로 쓰면 대입 값(Future)이 돌아가 Flutter 가 다시 그리기를 거부한다 — 블록으로
              setState(() {
                _note = _load();
              });
              await _note;
            },
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
              children: [
                if (widget.folder != null) Text('// ${widget.folder}', style: _mono(11, _muted)),
                const SizedBox(height: 4),
                _Panel(
                  child: NoteBody(
                    text: '${j['text'] ?? ''}',
                    api: widget.api,
                    onLink: _open,
                    onTask: (nth, want) async {
                      try {
                        await widget.api.flipTask(widget.title, nth);
                      } catch (e) {
                        widget.onFail(e);
                        return;
                      }
                      if (mounted) {
                        setState(() {
                          _note = _load();
                        });
                      }
                    },
                    onEditProp: widget.onSaveLine == null
                        ? null
                        : (k, v) async {
                            final got = await editProp(this.context, k, v);
                            if (got == null || got.trim() == v.trim() || !mounted) return;
                            await widget.onSaveLine!(widget.title, '- $k : ${got.trim()}');
                            if (!mounted) return;
                            ScaffoldMessenger.of(this.context).showSnackBar(
                              SnackBar(
                                duration: const Duration(seconds: 2),
                                content: Text('$k → ${got.trim()} — 글 끝에 적었어. 정리에 곧 반영돼'),
                              ),
                            );
                          },
                  ),
                ),
                // 이 글을 가리키는 글(옵시디언 백링크)
                if ((j['backlinks'] as List?)?.isNotEmpty ?? false) ...[
                  const SectionLabel('이 글을 가리키는 글'),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final b in (j['backlinks'] as List).whereType<String>())
                        ActionChip(
                          label: Text(b, style: const TextStyle(color: _text)),
                          backgroundColor: _card,
                          onPressed: () => _open(b),
                        ),
                    ],
                  ),
                ],
                if (j['cut'] == true)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text('(일부만 보였어 — 전체 ${j['full_chars']}자)', style: _mono(11, _muted)),
                  ),
              ],
            ),
          );
        },
      ),
    ),
  );
}

/// 항목 칸 하나를 고친다(편의 기능 4번) — 상태는 고르고, 날짜는 달력, 나머지는 글로.
/// 고친 값을 돌려준다(그대로 두면 null).
Future<String?> editProp(BuildContext context, String key, String value) async {
  final k = key.replaceAll(' ', '');
  if (k.contains('상태')) {
    return showModalBottomSheet<String>(
      context: context,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('$key 바꾸기', style: _mono(12, _muted)),
            ),
            for (final v in const ['보유중', '보냄', '반납'])
              ListTile(
                title: Text(v, style: const TextStyle(color: _text)),
                trailing: v == value ? const Icon(Icons.check, color: _accent) : null,
                onTap: () => Navigator.pop(c, v),
              ),
          ],
        ),
      ),
    );
  }
  if (k.endsWith('날') || k.endsWith('일') || k.contains('날짜')) {
    final now = DateTime.now();
    final got = await showDatePicker(
      context: context,
      initialDate: DateTime.tryParse(value) ?? now,
      firstDate: DateTime(now.year - 20),
      lastDate: DateTime(now.year + 5),
    );
    if (got == null) return null;
    String two(int v) => v.toString().padLeft(2, '0');
    return '${got.year}-${two(got.month)}-${two(got.day)}';
  }
  final ctl = TextEditingController(text: value);
  final got = await showDialog<String>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(key),
      content: TextField(controller: ctl, autofocus: true, onSubmitted: (v) => Navigator.pop(c, v)),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c), child: const Text('그대로')),
        TextButton(onPressed: () => Navigator.pop(c, ctl.text), child: const Text('고치기')),
      ],
    ),
  );
  // ★ 창이 닫히는 애니메이션이 끝나기 전에 없애면 「disposed 된 것을 썼다」로 터진다 — 한 박자 뒤에
  Future<void>.delayed(const Duration(milliseconds: 400), ctl.dispose);
  return got;
}

/// 글 몸 — `![[사진.heic]]` 는 사진으로, 영상·녹음·pdf 는 📎 칸으로,
/// `- 제품명 : …` 줄 묶음은 항목표로, 태그만 있는 줄은 칩으로.
/// ★ 오너 실기(2026-09-16): 사진은 맥에 붙었는데 앱 글 보기에는 `![[…]]` 글자만 보였다.
class NoteBody extends StatelessWidget {
  const NoteBody({super.key, required this.text, required this.api, this.onEditProp, this.onLink, this.onTask});

  final String text;
  final VcApi api;
  // 항목 칸을 누르면 고친다(편의 기능 4번). 없으면 보기만.
  final void Function(String key, String value)? onEditProp;
  // `[[링크]]` 를 누르면(편의 기능 19번). 없으면 글자만.
  final void Function(String title)? onLink;
  // `- [ ]` 를 누르면 체크(편의 기능 26번). 몇 번째 할 일인지 준다.
  final void Function(int nth, bool done)? onTask;

  static final _embed = RegExp(r'!\[\[([^\]|#]+?)(?:[#|][^\]]*)?\]\]');
  static final _prop = RegExp(r'^\s*[-*]\s+([^:：\n]{1,24}?)\s*[:：]\s*(.*)$');
  static final _tagLine = RegExp(r'^\s*(#[^\s#]+\s*)+$');
  static final _task = RegExp(r'^\s*[-*]\s+\[([ xX])\]\s?(.*)$');
  static const _imageExt = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif'};
  static const _fileExt = {'.pdf', '.mov', '.mp4', '.m4v', '.m4a', '.aac', '.mp3', '.wav', '.svg'};
  static const _style = TextStyle(color: _text, fontSize: 15.5, height: 1.7);

  static final _link = RegExp(r'(?<!!)\[\[([^\]|#]+?)(?:#[^\]|\\]*)?(?:\\?\|([^\]]*))?\]\]');
  static final _heading = RegExp(r'^\s*#{1,6}\s+(.*)$');

  /// `[[제목]]` · `[[제목\|보일 말]]` → 보일 말(링크 누르기는 편의 기능 9번에서).
  static String label(String s) =>
      s.replaceAllMapped(_link, (m) => (m.group(2) ?? '').isNotEmpty ? m.group(2)! : m.group(1)!);

  /// 표 한 줄을 칸으로 — `\|` 는 칸 가름이 아니다.
  static List<String> _cells(String line) => line
      .trim()
      .replaceAll(r'\|', '\u0000')
      .replaceAll(RegExp(r'^\||\|$'), '')
      .split('|')
      .map((c) => label(c.replaceAll('\u0000', '|')).trim())
      .toList();

  /// 글 조각을 항목표 · 표 · 소제목 · 태그 칩 · 글로 가른다.
  static List<Widget> _words(
    String s, [
    void Function(String, String)? onEdit,
    void Function(String)? onLink,
    void Function(int, bool)? onTask,
    int taskFrom = 0,
  ]) {
    final out = <Widget>[];
    final plain = <String>[];
    final props = <(String, String)>[];
    final table = <List<String>>[];
    void flushPlain() {
      final raw = plain.join('\n').trim();
      plain.clear();
      if (raw.isEmpty) return;
      if (onLink == null || !_link.hasMatch(raw)) {
        out.add(SelectableText(label(raw), style: _style));
        return;
      }
      // `[[링크]]` 를 누르면 그 글로(편의 기능 19번 · 옵시디언)
      final spans = <InlineSpan>[];
      var at = 0;
      for (final m in _link.allMatches(raw)) {
        if (m.start > at) spans.add(TextSpan(text: raw.substring(at, m.start)));
        final target = m.group(1)!.trim();
        spans.add(
          TextSpan(
            text: (m.group(2) ?? '').isNotEmpty ? m.group(2)! : target,
            style: const TextStyle(color: _accent, decoration: TextDecoration.underline),
            recognizer: TapGestureRecognizer()..onTap = () => onLink(target),
          ),
        );
        at = m.end;
      }
      if (at < raw.length) spans.add(TextSpan(text: raw.substring(at)));
      out.add(Text.rich(TextSpan(style: _style, children: spans)));
    }

    void flushTable() {
      if (table.isEmpty) return;
      final cols = table.map((r) => r.length).reduce((a, b) => a > b ? a : b);
      out.add(
        Container(
          margin: const EdgeInsets.symmetric(vertical: 6),
          decoration: BoxDecoration(color: _bg.withValues(alpha: .6), borderRadius: BorderRadius.circular(10)),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.all(8),
            child: Table(
              defaultColumnWidth: const IntrinsicColumnWidth(),
              border: TableBorder(horizontalInside: BorderSide(color: _accent.withValues(alpha: .12))),
              children: [
                for (var r = 0; r < table.length; r++)
                  TableRow(
                    children: [
                      for (var c = 0; c < cols; c++)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                          child: Text(
                            c < table[r].length ? table[r][c] : '',
                            style: r == 0
                                ? _mono(12, _muted, weight: FontWeight.w700)
                                : const TextStyle(color: _text, fontSize: 14),
                          ),
                        ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      );
      table.clear();
    }

    void flushProps() {
      if (props.isEmpty) return;
      out.add(
        Container(
          margin: const EdgeInsets.symmetric(vertical: 6),
          decoration: BoxDecoration(color: _bg.withValues(alpha: .6), borderRadius: BorderRadius.circular(10)),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Column(
            children: [
              for (final (k, v) in props)
                InkWell(
                  onTap: onEdit == null ? null : () => onEdit(k, v),
                  borderRadius: BorderRadius.circular(6),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 92, child: Text(k, style: _mono(12.5, _muted))),
                        Expanded(
                          child: Text(
                            v.isEmpty ? '—' : label(v),
                            style: TextStyle(color: v.isEmpty ? _muted : _text, fontSize: 15),
                          ),
                        ),
                        if (onEdit != null) const Icon(Icons.chevron_right, size: 16, color: _muted),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      );
      props.clear();
    }

    var inCode = false;
    final code = <String>[];
    var seen = 0; // 이 조각에서 지나온 할 일 수
    for (final line in s.split('\n')) {
      final t = line.trim();
      // 코드 울타리 — 안은 그대로, 고정폭으로
      if (t.startsWith('```')) {
        if (inCode) {
          out.add(
            Container(
              width: double.infinity,
              margin: const EdgeInsets.symmetric(vertical: 6),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: _bg, borderRadius: BorderRadius.circular(8)),
              child: SelectableText(
                code.join('\n'),
                style: const TextStyle(fontFamily: 'Menlo', fontSize: 13, color: _dim, height: 1.4),
              ),
            ),
          );
          code.clear();
        } else {
          flushPlain();
          flushProps();
          flushTable();
        }
        inCode = !inCode;
        continue;
      }
      if (inCode) {
        code.add(line);
        continue;
      }
      if (t.startsWith('|')) {
        flushPlain();
        flushProps();
        if (!RegExp(r'^\|[\s:|-]+\|?$').hasMatch(t)) table.add(_cells(t)); // 가름줄 |---| 은 건너뛴다
        continue;
      }
      flushTable();
      final h = _heading.firstMatch(line);
      if (h != null) {
        flushPlain();
        flushProps();
        out.add(
          Padding(
            padding: const EdgeInsets.only(top: 12, bottom: 2),
            child: Text(
              label(h.group(1)!),
              style: const TextStyle(color: _text, fontSize: 17, fontWeight: FontWeight.w700),
            ),
          ),
        );
        continue;
      }
      if (t.startsWith('>')) {
        flushPlain();
        flushProps();
        final inner = t.replaceFirst(RegExp(r'^>\s?'), '');
        final callout = RegExp(r'^\[!(\w+)\][+-]?\s*(.*)$').firstMatch(inner);
        out.add(
          callout != null
              // 옵시디언 접는 칸 머리 — 굵게
              ? Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Row(
                    children: [
                      const Icon(Icons.expand_more, size: 16, color: _accent),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Text(
                          label(callout.group(2)!.isEmpty ? callout.group(1)! : callout.group(2)!),
                          style: const TextStyle(color: _text, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                )
              : Container(
                  padding: const EdgeInsets.only(left: 10),
                  decoration: BoxDecoration(
                    border: Border(left: BorderSide(color: _accent.withValues(alpha: .4), width: 2)),
                  ),
                  child: Text(label(inner), style: const TextStyle(color: _dim, fontSize: 14, height: 1.5)),
                ),
        );
        continue;
      }
      final task = _task.firstMatch(line);
      if (task != null) {
        flushPlain();
        flushProps();
        final done = task.group(1)!.toLowerCase() == 'x';
        final nth = taskFrom + seen++;
        out.add(
          InkWell(
            onTap: onTask == null ? null : () => onTask(nth, !done),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    done ? Icons.check_box : Icons.check_box_outline_blank,
                    size: 20,
                    color: done ? _accent : _muted,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      label(task.group(2)!),
                      style: _style.copyWith(
                        color: done ? _muted : _text,
                        decoration: done ? TextDecoration.lineThrough : null,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
        continue;
      }
      final p = _prop.firstMatch(line);
      if (p != null) {
        flushPlain();
        props.add((p.group(1)!.trim(), p.group(2)!.trim()));
        continue;
      }
      flushProps();
      if (_tagLine.hasMatch(line)) {
        flushPlain();
        out.add(
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in line.trim().split(RegExp(r'\s+')))
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: _accent.withValues(alpha: .14),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(t, style: _mono(12.5, _accent)),
                  ),
              ],
            ),
          ),
        );
        continue;
      }
      plain.add(line);
    }
    flushTable();
    flushProps();
    flushPlain();
    return out;
  }

  static final _comment = RegExp(r'%%[\s\S]*?%%');

  /// 글 앞쪽(`upto` 전)에 할 일이 몇 개인지 — 서버가 세는 차례와 맞춘다.
  static int _tasksBefore(String text, int upto) =>
      _task.allMatches(text.substring(0, upto).split('\n').join('\n')).length;

  @override
  Widget build(BuildContext context) {
    final parts = <Widget>[];
    var at = 0;
    // 옵시디언 주석(`%% … %%` — 사진 글자 등)은 안 보인다
    final text = this.text.replaceAll(_comment, '').trimRight();
    for (final m in _embed.allMatches(text)) {
      final name = m.group(1)!.trim();
      final dot = name.lastIndexOf('.');
      final ext = dot < 0 ? '' : name.substring(dot).toLowerCase();
      if (!_imageExt.contains(ext) && !_fileExt.contains(ext)) continue; // 글 끼움은 글자 그대로 둔다
      parts.addAll(_words(text.substring(at, m.start), onEditProp, onLink, onTask, _tasksBefore(text, m.start)));
      if (_imageExt.contains(ext)) {
        parts.add(
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Image.network(
                api.attachmentUri(name).toString(),
                headers: api.authHeaders,
                fit: BoxFit.contain,
                semanticLabel: name,
                errorBuilder: (_, _, _) => _fileTile(name, '사진을 못 불러왔어 — 컴퓨터 연결을 봐 줘'),
              ),
            ),
          ),
        );
      } else {
        parts.add(_fileTile(name, '영상·녹음·문서는 컴퓨터 VC 에서 연다'));
      }
      at = m.end;
    }
    parts.addAll(_words(text.substring(at), onEditProp, onLink, onTask, _tasksBefore(text, at)));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: parts);
  }

  static Widget _fileTile(String name, String hint) => Container(
    margin: const EdgeInsets.symmetric(vertical: 6),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(color: _card, borderRadius: BorderRadius.circular(10)),
    child: Row(
      children: [
        const Icon(Icons.attach_file, size: 18, color: _accent),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(name, style: const TextStyle(color: _text)),
              Text(hint, style: _mono(10, _muted)),
            ],
          ),
        ),
      ],
    ),
  );
}

/// 새 메모 · 이어 쓰기 — 전체 화면 편집기(노션·에버노트처럼). 저장하면 곧장 닫히고 보내기는 뒤에서 한다.
class EditorPage extends StatelessWidget {
  const EditorPage({
    super.key,
    required this.outbox,
    required this.onSend,
    this.templates,
    this.fixedTitle,
    this.startBody,
  });

  final Outbox outbox;
  final Future<void> Function() onSend;
  final Future<(List<Tpl>, bool)> Function()? templates;
  final String? fixedTitle;
  final String? startBody; // 서식에서 새 글 — 채운 틀로 연다

  @override
  Widget build(BuildContext context) => Backdrop(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        leading: IconButton(tooltip: '닫기', icon: const Icon(Icons.close), onPressed: () => Navigator.maybePop(context)),
        title: Text(fixedTitle == null ? '새 메모' : '이어 쓰기', style: const TextStyle(fontSize: 17)),
      ),
      body: WriteTab(
        outbox: outbox,
        onSend: onSend,
        templates: templates,
        fixedTitle: fixedTitle,
        startBody: startBody,
        autofocus: true,
        onSaved: (item) => Navigator.pop(context, item),
      ),
    ),
  );
}

class WriteTab extends StatefulWidget {
  const WriteTab({
    super.key,
    required this.outbox,
    required this.onSend,
    this.pick = pickMedia,
    this.templates,
    this.fixedTitle,
    this.startBody,
    this.autofocus = false,
    this.readText = readImageText,
    this.record = recordMemo,
    this.onSaved,
  });

  final Outbox outbox;
  final Future<void> Function() onSend;
  final Picker pick; // 사진·영상 고르기(4단계). 시험에서는 가짜로 갈아 끼운다
  final Future<(List<Tpl>, bool)> Function()? templates; // 서식(5단계) — (틀 목록, 못 닿음)
  final String? fixedTitle; // 이어 쓰기 — 이 제목 글 끝에 붙는다(서버 기본이 덧붙이기)
  final String? startBody; // 서식에서 새 글
  final TextReader readText; // 사진 속 글자(기기 안) — 시험은 가짜
  final RecordMemo record; // 녹음 — 시험은 가짜
  final bool autofocus;
  // 편집기로 쓸 때 — 저장하면 불린다(보내기는 기다리지 않는다)
  final void Function(OutboxItem item)? onSaved;

  @override
  State<WriteTab> createState() => _WriteTabState();
}

class _WriteTabState extends State<WriteTab> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  String _say = '';
  bool _sayOk = true;
  bool _busy = false;
  // ★ 알림 줄이 가리키는 글. 저장할 때만 줄을 바꾸면, 오프라인에서 저장한 뒤 나중에 보내져도
  //   「폰에 저장됨 · 전송 대기」가 그대로 남았다(아래 목록만 「서버 저장 완료」로 바뀜 — 윈도우 실기).
  //   대기함이 그 글을 보내면 줄도 따라 바꾼다.
  String? _sayId;
  // 이 글에 붙일 사진·영상(4단계). 저장하면 대기함이 폰 안에 사본을 둔다.
  final List<File> _picked = [];

  @override
  void initState() {
    super.initState();
    if (widget.fixedTitle != null) _title.text = widget.fixedTitle!;
    if (widget.startBody != null) _body.text = widget.startBody!;
    widget.outbox.addListener(_onOutbox);
  }

  /// 서식 넣기(5단계 · 결정 19). 쓰던 글은 안 지우고 **끝에** 붙인다 — PC 「서식 넣기」와 같은 규칙.
  Future<void> _pickTemplate() async {
    final load = widget.templates;
    if (load == null) return;
    final (List<Tpl>, bool) got;
    try {
      got = await load();
    } catch (_) {
      _tell('서식을 못 불렀어 — 컴퓨터 연결을 봐 줘', false);
      return;
    }
    if (!mounted) return;
    if (got.$1.isEmpty) {
      _tell(got.$2 ? '컴퓨터에 못 닿고, 받아 둔 서식도 없어' : '서식이 없어 — 컴퓨터 VC 창고 _서식/ 에 md 로 만든다', false);
      return;
    }
    final chosen = await showModalBottomSheet<Tpl>(
      context: context,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            if (got.$2)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: Text('컴퓨터에 못 닿아 지난번 받은 서식이야', style: _mono(11, _warn)),
              ),
            for (final t in got.$1)
              ListTile(
                title: Text(t.name, style: const TextStyle(color: _text)),
                subtitle: Text(
                  t.body.replaceAll('\n', ' '),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: _muted),
                ),
                onTap: () => Navigator.pop(c, t),
              ),
          ],
        ),
      ),
    );
    if (chosen == null || !mounted) return;
    final title = _title.text.trim().isEmpty ? _today() : _title.text.trim();
    final filled = fillSlots(chosen.body, title: title);
    final cur = _body.text;
    _body.text = cur.trim().isEmpty ? filled : '$cur\n\n$filled';
    _body.selection = TextSelection.collapsed(offset: _body.text.length);
  }

  /// ＋ 시트 — 드물게 쓰는 붙이기(결정 26).
  Future<void> _more() async {
    // 격자 — 붙일 것이 늘어도 시트가 길어지지 않는다(작은 폰에서 아래가 잘렸다)
    final got = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: _card,
      builder: (c) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 16, 12, 8),
          child: Wrap(
            alignment: WrapAlignment.center,
            spacing: 4,
            runSpacing: 8,
            children: [
              for (final (key, icon, label) in const [
                ('library', Icons.photo_library_outlined, '사진첩'),
                ('video', Icons.videocam_outlined, '영상'),
                ('record', Icons.mic_none, '녹음'),
                ('table', Icons.table_chart_outlined, '표'),
                ('fold', Icons.expand_more, '접는 칸'),
                ('code', Icons.code, '코드'),
                ('quote', Icons.format_quote_outlined, '인용'),
              ])
                SizedBox(
                  width: 84,
                  child: InkWell(
                    borderRadius: BorderRadius.circular(12),
                    onTap: () => Navigator.pop(c, key),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      child: Column(
                        children: [
                          Icon(icon, color: _accent, size: 26),
                          const SizedBox(height: 6),
                          Text(label, style: const TextStyle(color: _text, fontSize: 12.5)),
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
    if (!mounted || got == null) return;
    switch (got) {
      case 'library':
        await _pick(PickHow.library);
      case 'video':
        await _pick(PickHow.video);
      case 'record':
        final f = await widget.record(context);
        if (f != null && mounted) setState(() => _picked.add(f));
      case 'table':
        _insert('| 항목 | 내용 |\n|---|---|\n|  |  |\n');
      case 'fold':
        _insert('> [!note]- 접는 칸\n> ');
      case 'code':
        _insert('```\n\n```\n', back: 5);
      case 'quote':
        _insert('> ');
    }
  }

  /// 커서 자리에 끼운다(줄 머리에서 시작하게). `back` 만큼 커서를 되돌린다.
  void _insert(String snippet, {int back = 0}) {
    final t = _body.text;
    final sel = _body.selection;
    final at = sel.isValid ? sel.start : t.length;
    final head = at > 0 && t[at - 1] != '\n' ? '\n' : '';
    final next = t.replaceRange(at, sel.isValid ? sel.end : at, '$head$snippet');
    final cursor = at + head.length + snippet.length - back;
    _body.value = TextEditingValue(
      text: next,
      selection: TextSelection.collapsed(offset: cursor),
    );
    if (widget.onSaved != null) setState(() {});
  }

  Future<void> _pick(PickHow how) async {
    try {
      final got = await widget.pick(how);
      if (got.isNotEmpty && mounted) setState(() => _picked.addAll(got));
    } catch (_) {
      _tell('사진을 못 가져왔어 — 아이폰 설정 › VC 에서 사진·카메라 허락을 봐 줘', false);
    }
  }

  @override
  void dispose() {
    widget.outbox.removeListener(_onOutbox);
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  void _onOutbox() {
    final id = _sayId;
    if (id == null || !mounted) return;
    for (final it in widget.outbox.items) {
      if (it.id == id && it.sent) {
        _sayId = null;
        _tell('서버 저장 완료 — 「${it.savedAs ?? it.title}」', true);
        return;
      }
    }
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
    // 사진만 붙여도 기록이다(에버노트처럼) — 글이 비어도 첨부가 있으면 저장한다.
    if ((text.isEmpty && _picked.isEmpty) || _busy) return;
    final title = widget.fixedTitle ?? (_title.text.trim().isEmpty ? _today() : _title.text.trim());
    setState(() => _busy = true);
    try {
      // 사진 속 글자를 숨은 주석으로 붙인다 — 영수증·송장 번호가 찾기에 걸린다(편의 기능 13번)
      final seen = <String, String>{};
      for (final f in _picked) {
        final t = await widget.readText(f);
        if (t.isNotEmpty) seen[f.uri.pathSegments.last] = t;
      }
      final hidden = hiddenText(seen);
      final withText = hidden.isEmpty ? text : (text.isEmpty ? hidden : '$text\n\n$hidden');
      final OutboxItem item;
      try {
        item = await widget.outbox.add(title, withText, files: List.of(_picked)); // ① 폰에 먼저 — 여기서 끝나면 앱이 꺼져도 남는다
      } catch (e) {
        _tell('폰에 저장 못 했어 — 적은 글은 칸에 그대로 있어 ($e)', false);
        return;
      }
      _body.clear();
      setState(() => _picked.clear());
      _sayId = item.id;
      _tell('폰에 저장됨 — 보내는 중…', true);
      final saved = widget.onSaved;
      if (saved != null) {
        // 편집기 — 보내기를 기다리지 않고 닫는다(사진이 크면 오래 걸린다). 보내기는 뒤에서.
        widget.onSend();
        WidgetsBinding.instance.addPostFrameCallback((_) => saved(item));
        return;
      }
      await widget.onSend(); // ② 닿으면 보낸다
      if (item.sent) _sayId = null;
      _tell(item.sent ? '서버 저장 완료 — 「${item.savedAs ?? item.title}」' : '폰에 저장됨 · 전송 대기 — 연결되면 보낸다', true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // 편집기 칸 — 상자 없이 종이처럼(노션·에버노트). 밖을 누르면 자판이 내려간다.
  static const _bare = InputDecoration(
    filled: false,
    border: InputBorder.none,
    enabledBorder: InputBorder.none,
    focusedBorder: InputBorder.none,
    contentPadding: EdgeInsets.symmetric(vertical: 8),
  );

  bool get _dirty => _body.text.trim().isNotEmpty || _picked.isNotEmpty;

  Future<void> _askLeave() async {
    final leave = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('적은 것을 버릴까?'),
        content: const Text('저장하지 않은 글·사진이 사라진다.', style: TextStyle(color: _dim)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('계속 쓰기')),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('버리기', style: TextStyle(color: _warn)),
          ),
        ],
      ),
    );
    if (leave == true && mounted) {
      _body.clear();
      setState(() => _picked.clear());
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) Navigator.maybePop(context);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    // 도구줄은 넷까지(결정 26) — 사진 · 서식 · ＋. 나머지는 ＋ 시트 안에.
    final tool = <Widget>[
      IconButton(
        tooltip: '사진 찍기',
        onPressed: _busy ? null : () => _pick(PickHow.photo),
        icon: const Icon(Icons.photo_camera_outlined, color: _accent),
      ),
      if (widget.templates != null)
        IconButton(
          tooltip: '서식 넣기',
          onPressed: _busy ? null : _pickTemplate,
          icon: const Icon(Icons.dashboard_customize_outlined, color: _accent),
        ),
      IconButton(
        tooltip: '더 붙이기',
        onPressed: _busy ? null : _more,
        icon: const Icon(Icons.add_circle_outline, color: _accent),
      ),
    ];
    return PopScope(
      canPop: widget.onSaved == null || !_dirty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _askLeave();
      },
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 0),
            child: TextField(
              controller: _title,
              readOnly: widget.fixedTitle != null,
              textInputAction: TextInputAction.next,
              // 글칸 밖을 누르면 자판이 내려간다(노트앱이 다 그렇다) — 전에는 제목을 눌러 ✓ 를 눌러야 내려갔다(오너 실기).
              onTapOutside: (_) => FocusManager.instance.primaryFocus?.unfocus(),
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: _text),
              decoration: _bare.copyWith(hintText: '제목 — 비우면 오늘 날짜'),
            ),
          ),
          if (widget.fixedTitle != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('이 글 끝에 이어 붙인다', style: _mono(11.5, _muted)),
              ),
            ),
          Divider(height: 1, indent: 20, endIndent: 20, color: _accent.withValues(alpha: .12)),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: TextField(
                controller: _body,
                autofocus: widget.autofocus,
                onTapOutside: (_) => FocusManager.instance.primaryFocus?.unfocus(),
                onChanged: (_) {
                  if (widget.onSaved != null) setState(() {}); // 버릴지 묻기(PopScope)를 새로 셈
                },
                maxLines: null,
                expands: true,
                keyboardType: TextInputType.multiline,
                textAlignVertical: TextAlignVertical.top,
                style: const TextStyle(fontSize: 16.5, height: 1.65, color: _text),
                decoration: _bare.copyWith(hintText: '대충 적어도 된다 — 사진만 붙여도 된다'),
              ),
            ),
          ),
          // 고른 사진·영상 — 눌러서 뺀다
          if (_picked.isNotEmpty)
            SizedBox(
              height: 44,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                children: [
                  for (var i = 0; i < _picked.length; i++)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: InputChip(
                        avatar: const Icon(Icons.attach_file, size: 16, color: _accent),
                        label: Text(_picked[i].uri.pathSegments.last, style: _mono(11, _text)),
                        onDeleted: () => setState(() => _picked.removeAt(i)),
                      ),
                    ),
                ],
              ),
            ),
          if (_say.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 4),
              child: Row(
                children: [
                  Icon(
                    _sayOk ? Icons.check_circle_outline : Icons.error_outline,
                    size: 16,
                    color: _sayOk ? _accent : _warn,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(_say, style: TextStyle(color: _dim.withValues(alpha: .85), fontSize: 13)),
                  ),
                ],
              ),
            ),
          // 도구줄 — 자판 바로 위에 붙는다. 저장도 여기서(엄지 닿는 자리).
          Container(
            decoration: BoxDecoration(
              color: _panel,
              border: Border(top: BorderSide(color: _accent.withValues(alpha: .14))),
            ),
            padding: EdgeInsets.fromLTRB(4, 4, 12, 4 + (keyboard ? 0 : MediaQuery.paddingOf(context).bottom)),
            child: Row(
              children: [
                ...tool,
                const Spacer(),
                if (keyboard)
                  IconButton(
                    tooltip: '자판 내리기',
                    onPressed: () => FocusManager.instance.primaryFocus?.unfocus(),
                    icon: const Icon(Icons.keyboard_hide_outlined, color: _muted),
                  ),
                FilledButton.icon(
                  onPressed: _busy ? null : _save,
                  style: FilledButton.styleFrom(minimumSize: const Size(92, 44)),
                  icon: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                        )
                      : const Icon(Icons.check, size: 18),
                  label: const Text('저장', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
