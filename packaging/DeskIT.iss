; DeskIT — the per-user installer (DISTRIBUTION_PLAN.md 10.4, D20, D21).
;
; Compiled by the build (release.yml step 10) and by packaging\build_local.ps1:
;     ISCC.exe packaging\DeskIT.iss /DVersion=1.2.0 /DVersionInfo=1.2.0.0 /DStage=stage /DOutDir=dist
; Stage is the tree steps 1-7 assembled: python\, app\, MANIFEST.sha256.
;
; What it buys, in the order a person meets it: no UAC prompt ever
; (per-user, under %LOCALAPPDATA%\Programs\DeskIT), Hebrew or English from
; the Windows UI language with no dialog when one of them matches, one
; Start-menu shortcut with the AppUserModelID the app expects, the app
; launched straight after so the first-run wizard follows, upgrades in
; place through Restart Manager, a downgrade refused by name, and an
; uninstaller that asks once whether the person's data goes too.

#ifndef Version
  #error Pass /DVersion=x.y.z (the VERSION file)
#endif
#ifndef VersionInfo
  #define VersionInfo Version + ".0"
#endif
#ifndef Stage
  #define Stage "stage"
#endif
#ifndef OutDir
  #define OutDir "dist"
#endif

[Setup]
; Fixed forever: Inno's upgrade-in-place key. A new version with the same
; AppId replaces the files in the same folder and keeps one Apps entry.
AppId={{9DE44D29-7270-4406-B00A-E6517B5629CE}
AppName=DeskIT
AppVersion={#Version}
VersionInfoVersion={#VersionInfo}
VersionInfoProductName=DeskIT
VersionInfoProductVersion={#Version}
AppPublisher=Yoav Shimron
AppPublisherURL=https://github.com/DeskIT-app/DeskIT
AppSupportURL=https://github.com/DeskIT-app/DeskIT
AppUpdatesURL=https://github.com/DeskIT-app/DeskIT/releases
DefaultDirName={localappdata}\Programs\DeskIT
DisableDirPage=yes
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
SetupLogging=yes
Compression=lzma2/ultra64
SolidCompression=yes
ShowLanguageDialog=auto
; Every relative path here — the stage, the icon, the output folder —
; is read from the repository root, where both builds run and where
; /DStage and /DOutDir point; the compiler's own base is the script's
; folder (dry run #4 looked for packaging\stage).
SourceDir=..
OutputDir={#OutDir}
OutputBaseFilename=DeskIT-Setup-{#Version}
SetupIconFile={#Stage}\app\icon.ico
UninstallDisplayIcon={app}\app\icon.ico
UninstallDisplayName=DeskIT
AppVerName=DeskIT {#Version}
WizardStyle=modern
; The wizard's own pictures, drawn at build time by dev\make_wizard_images.py
; from icon.png (never committed); Inno picks the size that fits the DPI.
; The Welcome page carries the three privacy sentences and, with the
; Ready page gone, its button is already Install: Welcome > Installing
; > Finished, two clicks.
WizardImageFile=packaging\wizard\side-314.bmp,packaging\wizard\side-386.bmp,packaging\wizard\side-459.bmp,packaging\wizard\side-556.bmp,packaging\wizard\side-604.bmp
WizardSmallImageFile=packaging\wizard\small-55.bmp,packaging\wizard\small-64.bmp,packaging\wizard\small-83.bmp,packaging\wizard\small-92.bmp,packaging\wizard\small-110.bmp,packaging\wizard\small-119.bmp,packaging\wizard\small-138.bmp
DisableWelcomePage=no
DisableReadyPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Messages]
english.SetupWindowTitle=%1
english.WelcomeLabel1=Welcome to DeskIT
english.WelcomeLabel2=Hebrew dictation that stays on this PC.%n%nDeskIT installs for your user only, without an administrator password. On the first start a short wizard sets up the microphone, the key and the Hebrew model (a 1.6 GB download, once).%n%nYour voice stays on this computer. Nothing is sent anywhere until you turn it on yourself.
english.ButtonNext=&Install
english.ClickNext=Click Install to continue, or Cancel to exit.
english.FinishedHeadingLabel=DeskIT is installed
english.FinishedLabel=Start it now: the first-run wizard takes about two minutes, most of it the model's download.
english.ClickFinish=Click Finish to exit Setup.
hebrew.SetupWindowTitle=%1
hebrew.WelcomeLabel1=ברוכים הבאים ל־DeskIT
hebrew.WelcomeLabel2=הכתבה בעברית שנשארת במחשב הזה.%n%nDeskIT מותקן למשתמש שלך בלבד, בלי סיסמת מנהל. בהפעלה הראשונה אשף קצר מגדיר את המיקרופון, את המקש ואת המודל העברי (הורדה של 1.6 ג'יגה־בייט, פעם אחת).%n%nהקול שלך נשאר במחשב הזה. שום דבר לא נשלח לשום מקום עד שתפעיל את זה בעצמך.
hebrew.ButtonNext=&התקנה
hebrew.ClickNext=לחץ על 'התקנה' כדי להמשיך, או על 'ביטול' כדי לצאת.
hebrew.FinishedHeadingLabel=DeskIT מותקן
hebrew.FinishedLabel=אפשר להפעיל עכשיו: אשף ההפעלה הראשונה לוקח כשתי דקות, רובן הורדת המודל.
hebrew.ClickFinish=לחץ על סיום כדי לצאת מההתקנה.

[CustomMessages]
english.LaunchNow=Start DeskIT now
english.DeleteDataQuestion=Also delete your settings, history and downloaded models?%n%nKeep them if you plan to install DeskIT again.
english.KeepData=&Keep
english.DeleteData=&Delete
english.Downgrade=DeskIT %1 is already installed; this installer is version %2.%n%nTo go back to an older version, uninstall DeskIT first, then run the older installer (its link is in the release notes).
hebrew.LaunchNow=להפעיל את DeskIT עכשיו
hebrew.DeleteDataQuestion=למחוק גם את ההגדרות, ההיסטוריה והמודלים שהורדו?%n%nאם בכוונתך להתקין את DeskIT שוב, עדיף להשאיר אותם.
hebrew.KeepData=&להשאיר
hebrew.DeleteData=&למחוק
hebrew.Downgrade=DeskIT %1 כבר מותקן; קובץ ההתקנה הזה הוא גרסה %2.%n%nכדי לחזור לגרסה ישנה יותר, הסר את DeskIT ואז הפעל את קובץ ההתקנה הישן (הקישור נמצא בהערות הגרסה).

[Files]
; Everything the build staged: python\, app\, MANIFEST.sha256. ignoreversion
; because .py files carry no version resource and must always be replaced.
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[InstallDelete]
; A file the new tree no longer has must not survive an upgrade: Inno
; replaces files, it does not remove the ones that went away. app\ is
; the product's source and is rebuilt whole. python\ is left as it is
; for now: chapter 6's packs will add wheels there that an upgrade must
; keep, and the rule for the base's own dist-info records comes with them.
Type: filesandordirs; Name: "{app}\app"

[Icons]
; One entry, the AppUserModelID the app sets on its own windows (D5), so
; the taskbar shows DeskIT rather than pythonw. No desktop icon, no
; Startup-folder entry: "Start with Windows" is the app's own switch.
Name: "{userprograms}\DeskIT"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\deskit.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; AppUserModelID: "DeskIT.App"

[Run]
; The first-run wizard follows the install. /NOLAUNCH (winget, the smoke
; test) leaves the box out; a silent install never launches.
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\deskit.pyw"""; WorkingDir: "{app}"; Description: "{cm:LaunchNow}"; Flags: postinstall nowait skipifsilent; Check: not NoLaunch

[UninstallDelete]
; The whole folder: CHANNEL, __pycache__ and pack-installed wheels were
; not in [Files] and would otherwise stay behind.
Type: filesandordirs; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'DeskIT';

function NoLaunch: Boolean;
begin
  Result := ExpandConstant('{param:NOLAUNCH|no}') <> 'no';
end;

{ The channel this copy came through: github (default), winget (the manifest
  passes /CHANNEL=winget), store (the MSIX build writes its own). The app
  reads CHANNEL beside its tree at start; a missing or unknown word reads
  as github. (No brace inside a brace comment: the first close brace ends
  it — dry run #5.) }
function ChannelWord: String;
begin
  Result := Lowercase(ExpandConstant('{param:CHANNEL|github}'));
  if (Result <> 'github') and (Result <> 'winget') and (Result <> 'store') then
    Result := 'github';
end;

{ MAJOR.MINOR.PATCH as one comparable number; a -beta.N suffix is ignored,
  so a beta of the same numbers neither upgrades nor downgrades a release. }
function VersionNumber(S: String): Integer;
var
  Parts: TArrayOfString;
  I, Dash: Integer;
  Core, Piece: String;
begin
  Result := 0;
  Dash := Pos('-', S);
  if Dash > 0 then Core := Copy(S, 1, Dash - 1) else Core := S;
  Piece := '';
  SetArrayLength(Parts, 0);
  for I := 1 to Length(Core) do
  begin
    if Core[I] = '.' then
    begin
      SetArrayLength(Parts, GetArrayLength(Parts) + 1);
      Parts[GetArrayLength(Parts) - 1] := Piece;
      Piece := '';
    end
    else
      Piece := Piece + Core[I];
  end;
  SetArrayLength(Parts, GetArrayLength(Parts) + 1);
  Parts[GetArrayLength(Parts) - 1] := Piece;
  if GetArrayLength(Parts) >= 3 then
    Result := StrToIntDef(Parts[0], 0) * 1000000 + StrToIntDef(Parts[1], 0) * 1000 + StrToIntDef(Parts[2], 0);
end;

function InstalledVersion: String;
var
  Key: String;
begin
  Result := '';
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + ExpandConstant('{#SetupSetting("AppId")}') + '_is1';
  if not RegQueryStringValue(HKCU, Key, 'DisplayVersion', Result) then
    Result := '';
end;

{ A downgrade is refused by name (D21: rollback is uninstall, then the
  older installer, whose link the release notes carry). }
function InitializeSetup: Boolean;
var
  Have: String;
begin
  Result := True;
  Have := InstalledVersion;
  if (Have <> '') and (VersionNumber(Have) > VersionNumber('{#Version}')) then
  begin
    SuppressibleMsgBox(FmtMessage(CustomMessage('Downgrade'), [Have, '{#Version}']), mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\CHANNEL'), ChannelWord(), False);
end;

{ One question, Keep by default (and the only answer a silent uninstall
  gives): Delete runs the app's own reset over its data folder. Either
  way the Run value goes — a stale autostart pointing at nothing is the
  bug people report. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Answer, ResultCode: Integer;
  Py, Entry: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  RegDeleteValue(HKCU, RunKey, RunValue);
  { the button labels stay on the call's line: a line that begins with
    "[" is a section tag to the compiler, even inside [Code] (dry run #3) }
  Answer := SuppressibleTaskDialogMsgBox('', CustomMessage('DeleteDataQuestion'), mbConfirmation, MB_YESNO, [
    CustomMessage('DeleteData'), CustomMessage('KeepData')], IDNO, IDNO);
  if Answer = IDYES then
  begin
    Py := ExpandConstant('{app}\python\pythonw.exe');
    Entry := ExpandConstant('{app}\app\deskit.pyw');
    Exec(Py, '"' + Entry + '" --reset-data --yes', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
