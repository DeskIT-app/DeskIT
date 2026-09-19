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
;
; And, since 2026-09-19 (10.4, the owner's "everything comes the moment I
; install"): the downloads the first-run wizard's computer page used to
; make are this installer's, with the person's tick — the Hebrew model,
; and with an NVIDIA card its libraries and the English detector, and the
; Recording pack — from the same URLs and against the same SHA-256s the
; app's own models.py and packs.py use (downloads.iss, generated from the
; two locks). Nothing is bundled (D13, D24). What lands is placed under
; the data folder and `main.py --adopt-downloads` hashes and completes
; it; what does not, the wizard offers as before. Silent installs and
; /NODOWNLOAD download nothing.

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
english.WelcomeLabel2=Hebrew dictation that stays on this PC.%n%nDeskIT installs for your user only, without an administrator password. The next page downloads the Hebrew model (1.6 GB, once); on the first start a short wizard sets up the microphone and the key.%n%nYour voice stays on this computer. Nothing is sent anywhere until you turn it on yourself.
english.ButtonNext=&Install
english.ClickNext=Click Install to continue, or Cancel to exit.
english.FinishedHeadingLabel=DeskIT is installed
english.FinishedLabel=Start it now: the first-run wizard takes about a minute.
english.ClickFinish=Click Finish to exit Setup.
hebrew.SetupWindowTitle=%1
hebrew.WelcomeLabel1=ברוכים הבאים ל־DeskIT
hebrew.WelcomeLabel2=הכתבה בעברית שנשארת במחשב הזה.%n%nDeskIT מותקן למשתמש שלך בלבד, בלי סיסמת מנהל. העמוד הבא מוריד את המודל העברי (1.6 ג'יגה־בייט, פעם אחת); בהפעלה הראשונה אשף קצר מגדיר את המיקרופון ואת המקש.%n%nהקול שלך נשאר במחשב הזה. שום דבר לא נשלח לשום מקום עד שתפעיל את זה בעצמך.
hebrew.ButtonNext=&התקנה
hebrew.ClickNext=לחץ על 'התקנה' כדי להמשיך, או על 'ביטול' כדי לצאת.
hebrew.FinishedHeadingLabel=DeskIT מותקן
hebrew.FinishedLabel=אפשר להפעיל עכשיו: אשף ההפעלה הראשונה לוקח כדקה.
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
; The Downloads page (10.4): the items with their sizes, the licence line,
; and the three sentences the download itself may need.
; Plain words, one link (the owner, 2026-09-19: "half the people do not
; understand this; a wall of programmer-level text makes them MORE afraid,
; not less") — what each thing does for you and how big it is; the exact
; figures, the licences and their links are one click away, in the guide.
english.DlCaption=Downloads
english.DlDescription=A few big files DeskIT needs, downloaded now so it is ready the first time you start it
english.DlSub=Leave the boxes ticked unless you know you do not want something — each can be added later. Ticking a box accepts its licence.
english.DlItem_model=Hebrew speech — %1
english.DlItem_detector=English detection — %1
english.DlItem_gpu=Faster with your NVIDIA card — %1
english.DlItem_recording=Screen recording — %1
english.DlMore=More about these downloads and their licences
english.DlMoreUrl=https://deskit-app.github.io/DeskIT/en/01-install#downloads
english.DlFailed=The download did not finish: %1%n%nRetry, or Cancel — DeskIT will offer it again the first time you start it.
english.DlNoRoom=Not enough room for the downloads: %1 MB needed, %2 MB free on this drive. DeskIT will offer them again the first time you start it.
english.DlFinishing=Checking the downloads and putting them in place...
hebrew.DlCaption=הורדות
hebrew.DlDescription=כמה קבצים גדולים ש־DeskIT צריך, יורדים עכשיו כדי שבהפעלה הראשונה הכול יהיה מוכן
hebrew.DlSub=השאר את התיבות מסומנות אלא אם ברור לך שמשהו לא נחוץ — אפשר להוסיף הכול גם אחר כך. סימון תיבה הוא הסכמה לרישיון שלה.
hebrew.DlItem_model=דיבור בעברית — %1
hebrew.DlItem_detector=זיהוי אנגלית — %1
hebrew.DlItem_gpu=מהיר יותר עם כרטיס ה־NVIDIA שלך — %1
hebrew.DlItem_recording=הקלטת מסך — %1
hebrew.DlMore=עוד על ההורדות האלה ועל הרישיונות
hebrew.DlMoreUrl=https://deskit-app.github.io/DeskIT/he/01-install#downloads
hebrew.DlFailed=ההורדה לא הסתיימה: %1%n%nנסה שוב, או בטל — DeskIT יציע אותה שוב בהפעלה הראשונה.
hebrew.DlNoRoom=אין די מקום להורדות: נדרשים %1 מגה־בייט, פנויים %2 מגה־בייט בכונן הזה. DeskIT יציע אותן שוב בהפעלה הראשונה.
hebrew.DlFinishing=בודק את ההורדות ומניח אותן במקומן...

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
; The Start-menu entry and a desktop icon, both with the AppUserModelID
; the app sets on its own windows (D5), so the taskbar shows DeskIT rather
; than pythonw. The desktop icon since 1.1.1: the owner closed the 1.1.0
; install and could not find it again (2026-09-19) — the Start menu alone
; is not where people look. No Startup-folder entry: "Start with Windows"
; is the app's own switch.
Name: "{userprograms}\DeskIT"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\deskit.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; AppUserModelID: "DeskIT.App"
Name: "{userdesktop}\DeskIT"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\deskit.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; AppUserModelID: "DeskIT.App"

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

{ The download list, one function per fact, generated from the two locks
  by dev\make_downloads_iss.py - never edited by hand. }
#include "downloads.iss"

var
  DlPage: TInputOptionWizardPage;
  DownloadPage: TDownloadWizardPage;
  DlOffered: TArrayOfString;     { the items on the page, in checkbox order }
  DlGot: TArrayOfString;         { the items whose every file came down }
  DlCardVram: Integer;
  DlCardDriver: String;

function NoLaunch: Boolean;
begin
  Result := ExpandConstant('{param:NOLAUNCH|no}') <> 'no';
end;

function NoDownload: Boolean;
begin
  Result := ExpandConstant('{param:NODOWNLOAD|no}') <> 'no';
end;

{ The app's data folder on an installed copy (paths.py, no DESKIT_HOME). }
function DataDir: String;
begin
  Result := ExpandConstant('{localappdata}\DeskIT');
end;

procedure SplitOn(S, Sep: String; var Parts: TArrayOfString);
var
  P: Integer;
begin
  SetArrayLength(Parts, 0);
  P := Pos(Sep, S);
  while P > 0 do
  begin
    SetArrayLength(Parts, GetArrayLength(Parts) + 1);
    Parts[GetArrayLength(Parts) - 1] := Copy(S, 1, P - 1);
    S := Copy(S, P + Length(Sep), Length(S));
    P := Pos(Sep, S);
  end;
  SetArrayLength(Parts, GetArrayLength(Parts) + 1);
  Parts[GetArrayLength(Parts) - 1] := S;
end;

procedure AppendTo(var List: TArrayOfString; Item: String);
begin
  SetArrayLength(List, GetArrayLength(List) + 1);
  List[GetArrayLength(List) - 1] := Item;
end;

function InList(Item: String; List: TArrayOfString): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 0 to GetArrayLength(List) - 1 do
    if List[I] = Item then
      Result := True;
end;

{ The item is already on this PC: its marker file holds every stamp the
  lock names (the model's revision, each wheel's version) - the same
  test models.state and packs.state make, so an upgrade fetches nothing
  that is there and a release that moved a version fetches the new one. }
function DlPresent(Item: String): Boolean;
var
  Marker, Content: String;
  Ansi: AnsiString;
  Stamps: TArrayOfString;
  I: Integer;
begin
  Result := False;
  Marker := DataDir + '\' + DlMarker(Item);
  if not FileExists(Marker) then
    Exit;
  if not LoadStringFromFile(Marker, Ansi) then
    Exit;
  Content := Ansi;
  SplitOn(DlStamps(Item), '|', Stamps);
  for I := 0 to GetArrayLength(Stamps) - 1 do
    if Pos(Stamps[I], Content) = 0 then
      Exit;
  Result := True;
end;

{ The card, the way hardware.py asks: nvidia-smi's memory and driver
  version. No NVIDIA driver, no nvidia-smi, no card. }
procedure ProbeCard;
var
  SmiFile, Line: String;
  Lines: TArrayOfString;
  Code, Comma: Integer;
begin
  DlCardVram := 0;
  DlCardDriver := '';
  SmiFile := ExpandConstant('{tmp}\nvidia-smi.txt');
  if not Exec(ExpandConstant('{cmd}'), '/C nvidia-smi --query-gpu=memory.total,driver_version --format=csv,noheader,nounits > "' + SmiFile + '" 2>&1', '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Exit;
  if Code <> 0 then
    Exit;
  if not LoadStringsFromFile(SmiFile, Lines) then
    Exit;
  if GetArrayLength(Lines) = 0 then
    Exit;
  Line := Trim(Lines[0]);
  Comma := Pos(',', Line);
  if Comma = 0 then
    Exit;
  DlCardVram := StrToIntDef(Trim(Copy(Line, 1, Comma - 1)), 0);
  DlCardDriver := Trim(Copy(Line, Comma + 1, Length(Line)));
end;

{ hardware.DRIVER_FLOOR: 545.84, the first driver CUDA 12.3 runs on. }
function DriverOk(Driver: String): Boolean;
var
  Dot, Major, Minor: Integer;
begin
  Result := False;
  Dot := Pos('.', Driver);
  if Dot = 0 then
    Exit;
  Major := StrToIntDef(Copy(Driver, 1, Dot - 1), 0);
  Minor := StrToIntDef(Copy(Driver, Dot + 1, Length(Driver)), 0);
  Result := (Major > 545) or ((Major = 545) and (Minor >= 84));
end;

{ What this PC is offered: the model and the Recording pack always; the
  CUDA libraries with a card of 4 GB and a driver new enough; the English
  detector with 6 GB (firstrun.card_tier) - and never what is there. }
function DlWanted(Item: String): Boolean;
begin
  Result := False;
  if (Item = 'model') or (Item = 'recording') then
    Result := True
  else if Item = 'gpu' then
    Result := (DlCardVram >= 4096) and DriverOk(DlCardDriver)
  else if Item = 'detector' then
    Result := (DlCardVram >= 6144) and DriverOk(DlCardDriver);
  if Result then
    Result := not DlPresent(Item);
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if (ProgressMax > 0) and (Progress = ProgressMax) then
    Log(FileName + ' landed: ' + IntToStr(ProgressMax) + ' bytes');
  Result := True;
end;

procedure MoreClick(Sender: TObject);
var
  Code: Integer;
begin
  ShellExec('open', CustomMessage('DlMoreUrl'), '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

{ The size line in the page's language: Hebrew units under Hebrew, so the
  number and its unit stay one run and do not swap places. }
function DlSize(Item: String): String;
begin
  if ActiveLanguage = 'hebrew' then
    Result := DlHumanHe(Item)
  else
    Result := DlHuman(Item);
end;

procedure InitializeWizard;
var
  Items: TArrayOfString;
  Item: String;
  I, N: Integer;
  Link: TNewStaticText;
begin
  SetArrayLength(DlOffered, 0);
  SetArrayLength(DlGot, 0);
  if WizardSilent or NoDownload then
    Exit;
  ProbeCard;
  DlPage := CreateInputOptionPage(wpWelcome, CustomMessage('DlCaption'),
    CustomMessage('DlDescription'), CustomMessage('DlSub'), False, False);
  SplitOn(DlItems, '|', Items);
  for I := 0 to GetArrayLength(Items) - 1 do
  begin
    Item := Items[I];
    if DlWanted(Item) then
    begin
      N := DlPage.Add(FmtMessage(CustomMessage('DlItem_' + Item), [DlSize(Item)]));
      DlPage.Values[N] := True;
      AppendTo(DlOffered, Item);
    end;
  end;
  { one link under the list: the guide's page on these downloads, where the
    exact sizes, what each one is and every licence live }
  DlPage.CheckListBox.Height := ScaleY(24) * GetArrayLength(DlOffered) + ScaleY(6);
  Link := TNewStaticText.Create(DlPage);
  Link.Parent := DlPage.Surface;
  Link.Caption := CustomMessage('DlMore');
  Link.Cursor := crHand;
  Link.Font.Style := [fsUnderline];
  Link.Font.Color := clBlue;
  Link.OnClick := @MoreClick;
  Link.Left := DlPage.CheckListBox.Left;
  Link.Top := DlPage.CheckListBox.Top + DlPage.CheckListBox.Height + ScaleY(10);
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing),
    SetupMessage(msgPreparingDesc), @OnDownloadProgress);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (DlPage <> nil) and (PageID = DlPage.ID) then
    Result := GetArrayLength(DlOffered) = 0;
end;

{ One item, all its files, against the lock's SHA-256s (Inno checks them
  as they land). Retry on a failure, or leave the item to the wizard. }
function DownloadItem(Item: String): Boolean;
var
  I: Integer;
  Row: TArrayOfString;
  Again: Boolean;
begin
  Result := False;
  DownloadPage.Clear;
  for I := 0 to DlCount - 1 do
  begin
    SplitOn(DlRow(I), '|', Row);
    if Row[0] = Item then
      DownloadPage.Add(Row[2], Item + '--' + ExtractFileName(Row[1]), Row[3]);
  end;
  Again := True;
  while Again do
  begin
    Again := False;
    try
      DownloadPage.Download;
      Result := True;
    except
      if DownloadPage.AbortedByUser then
        Log('download of ' + Item + ' aborted by the user')
      else
      begin
        Log('download of ' + Item + ' failed: ' + GetExceptionMessage);
        Again := SuppressibleMsgBox(FmtMessage(CustomMessage('DlFailed'), [AddPeriod(GetExceptionMessage)]),
          mbError, MB_RETRYCANCEL, IDCANCEL) = IDRETRY;
      end;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  Need, FreeBytes, TotalBytes: Int64;
  Any: Boolean;
begin
  Result := True;
  if (DlPage = nil) or (CurPageID <> DlPage.ID) then
    Exit;
  Need := 0;
  Any := False;
  for I := 0 to GetArrayLength(DlOffered) - 1 do
    if DlPage.Values[I] then
    begin
      Need := Need + StrToInt64(DlBytes(DlOffered[I]));
      Any := True;
    end;
  if not Any then
    Exit;
  if GetSpaceOnDisk64(ExpandConstant('{localappdata}'), FreeBytes, TotalBytes) and (FreeBytes < Need + 1073741824) then
  begin
    SuppressibleMsgBox(FmtMessage(CustomMessage('DlNoRoom'), [IntToStr(Need div 1048576), IntToStr(FreeBytes div 1048576)]),
      mbInformation, MB_OK, IDOK);
    Exit;
  end;
  DownloadPage.Show;
  try
    for I := 0 to GetArrayLength(DlOffered) - 1 do
    begin
      if DlPage.Values[I] and not DownloadPage.AbortedByUser then
      begin
        if DownloadItem(DlOffered[I]) then
          AppendTo(DlGot, DlOffered[I]);
      end;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

{ After the files: what came down goes from the setup's temp folder to
  its place under the data folder (a move on one drive, a copy across
  two), and the installed Python hashes and completes it - no window,
  no network. The wizard's computer page then has nothing to offer. }
procedure PlaceDownloads;
var
  I, Code: Integer;
  Row: TArrayOfString;
  Src, Dest: String;
begin
  if GetArrayLength(DlGot) = 0 then
    Exit;
  WizardForm.StatusLabel.Caption := CustomMessage('DlFinishing');
  for I := 0 to DlCount - 1 do
  begin
    SplitOn(DlRow(I), '|', Row);
    if InList(Row[0], DlGot) then
    begin
      Src := ExpandConstant('{tmp}\') + Row[0] + '--' + ExtractFileName(Row[1]);
      Dest := DataDir + '\' + Row[1];
      ForceDirectories(ExtractFileDir(Dest));
      DeleteFile(Dest);
      if not RenameFile(Src, Dest) then
        if not FileCopy(Src, Dest, False) then
          Log('could not place ' + Dest);
    end;
  end;
  if not Exec(ExpandConstant('{app}\python\python.exe'), '"' + ExpandConstant('{app}\app\main.py') + '" --adopt-downloads',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  Log('main.py --adopt-downloads exited ' + IntToStr(Code));
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
  begin
    SaveStringToFile(ExpandConstant('{app}\CHANNEL'), ChannelWord(), False);
    PlaceDownloads;
  end;
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
