; Photolab のインストーラー定義（Inno Setup 6）
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\photolab.iss
;
; 前提: 先に PyInstaller で dist\Photolab\ を作っておくこと（tools\build.ps1）。
;
; 方針:
;   - **ユーザー単位のインストール**（管理者権限を要求しない）。
;     写真の取り込みに管理者権限は要らず、要求すると SmartScreen の警告と相まって
;     心理的な障壁が上がるため。
;   - onedir をそのまま配置する。PySide6 (LGPLv3) の Qt DLL を差し替え可能な
;     状態で保つことがライセンス条件を満たす前提になっている。
;   - RapidRAW / darktable は**同梱しない**（別ライセンスのソフト）。
;     任意でダウンロードスクリプトを呼ぶ。

#define AppName "Photolab"
#define AppPublisher "3048mm"
#define AppURL "https://github.com/3048mm/photolab"
#define AppExeName "Photolab.exe"
; ビルド出力の場所。ISCC の /DSourceDir=... で差し替えられる
#ifndef SourceDir
  #define SourceDir "..\dist\Photolab"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{8F3C2A14-6D1B-4E7A-9C55-1B2E7A0D9F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir={#OutDir}
OutputBaseFilename=Photolab-{#AppVersion}-setup
SetupIconFile=..\photolab\ui\assets\photolab.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 管理者権限を要求しない。ユーザー単位でインストールする。
;
; `dialog` にしてはならない。「すべてのユーザー用」を選ばれると、昇格のために
; セットアップが自分自身を起動し直し、**ウィザードが最初の画面に戻る**
; （2026-08-12 に実際に起きた）。既定でその選択肢を見せない。
; 全ユーザー向けに入れたい場合は /ALLUSERS を付けて実行する。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作る"; \
    GroupDescription: "追加のショートカット"
Name: "startup"; Description: "ログイン時に常駐し、カードを挿したら取り込み画面を開く"; \
    GroupDescription: "自動起動"
Name: "rapidraw"; Description: "RapidRAW（現像ソフト）をダウンロードして入れる"; \
    GroupDescription: "現像ソフト"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\install_rapidraw.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} を常駐させる"; Filename: "{app}\{#AppExeName}"; Parameters: "watch"
Name: "{group}\{#AppName} をアンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; ログイン時の常駐。解除はスタートアップからショートカットを消すだけ
Name: "{userstartup}\{#AppName} 常駐"; Filename: "{app}\{#AppExeName}"; \
    Parameters: "watch"; Tasks: startup

[Run]
; RapidRAW は同梱せず、公式リリースから取得する（AGPL-3.0 のため再配布しない）
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\install_rapidraw.ps1"" -Yes"; \
    StatusMsg: "RapidRAW をダウンロードしています..."; \
    Flags: waituntilterminated; Tasks: rapidraw
Filename: "{app}\{#AppExeName}"; Description: "{#AppName} を起動する"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; アンインストール時に PyInstaller の残骸を消す。
; **カタログと設定（%LOCALAPPDATA%\Photolab）は消さない。**
; 取り込み済みの記録は写真と対で意味を持つ資産であり、
; 再インストール時に失うと「取り込んだかどうか」が分からなくなる。
Type: filesandordirs; Name: "{app}\_internal"
