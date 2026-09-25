; VC 윈도우 단일 설치 파일 (Inno Setup)
;
; ★★ **onefile 로는 안 만든다.** 재 봤다: 기동이 3.95초 → 1.36초로 2.9배 느려지고,
;    임시폴더에 제 몸을 푸는 것이 백신 오탐의 대표 트리거다(`VC.spec` 머리말).
;    그래서 **폴더 통째로 굽고, 그것을 설치 프로그램 한 장으로 감싼다.**
;
; ★★ **기록·설정·모델은 안 건드린다.** 그것들은 앱 폴더 **밖**에 산다 —
;    창고는 `기록자리.txt` 가 가리키는 곳, 기계 파일은 `%LOCALAPPDATA%\VC`.
;    그래서 **덮어 깔아도 쓰던 것이 그대로 남는다**(업데이트가 곧 재설치다).
;
; ★ 관리자 권한을 안 쓴다(`lowest`). 사용자 자리에 깔면 회사 PC 에서도 막히지 않고,
;   자동 업데이트를 넣을 때도 권한 상승 없이 갈아 끼울 수 있다.
;
; 굽기:  ISCC.exe /DVer=0.5.19 /DSrc=<dist\VC 자리> /DOut=<낼 자리> VC.iss

; ★★ **이름을 `Ver` 로 두면 안 된다.** Inno 전처리기는 이름의 대소문자를 안 가리고
;    `VER` 는 **제가 쓰는 이름**이다(Inno 자신의 판 번호). 우리 값이 그걸 덮어써서
;    제 판을 견주는 줄에서 터진다:
;      Error on line 216 in ISPPBuiltins.iss: Operator not applicable to this operand type.
;    오너 기계엔 Inno 가 없어 여태 건너뛰었고, CI 에서 처음 돌려 보고 알았다(2026-09-25).
#ifndef VCVer
  #define VCVer "0.0.0"
#endif
#ifndef Src
  #define Src "..\dist\VC"
#endif
#ifndef Out
  #define Out "."
#endif

[Setup]
AppId={{8F2B6C21-5D4E-4A77-9C13-VC000000001}
AppName=VC
AppVersion={#VCVer}
AppPublisher=Unknown
DefaultDirName={autopf}\VC
DefaultGroupName=VC
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Out}
OutputBaseFilename=VC-설치-{#VCVer}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 돌고 있는 VC 를 덮어쓰려다 반쯤 깔리는 것을 막는다
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=VC {#VCVer}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VC"; Filename: "{app}\VC.exe"
Name: "{autodesktop}\VC"; Filename: "{app}\VC.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 아이콘 만들기"; GroupDescription: "덤:"; Flags: unchecked

[Run]
Filename: "{app}\VC.exe"; Description: "지금 VC 켜기"; Flags: nowait postinstall skipifsilent

; ★ 지울 때도 **기록은 안 지운다.** 앱만 지운다 — 20년 치를 지우는 단추를
;   실수로 누를 자리를 만들지 않는다.
[UninstallDelete]
Type: filesandordirs; Name: "{app}"
