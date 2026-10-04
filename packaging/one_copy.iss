; One DeskIT per PC — the installer's half (onecopy.py holds the app's
; half and what two copies share, measured on 2026-10-04).
;
; The website's installer, winget (this same installer) and the Microsoft
; Store package are ONE app downloaded three ways: the owner's rule of
; 2026-10-04. So before anything is installed, Setup asks Windows whether
; the Store package is installed for this user (kernel32
; GetPackagesByPackageFamily, the same call onecopy.store_copy makes) and,
; when it is, says so once:
;
;   Keep the Store copy    (the default; Setup closes, nothing changed)
;   Remove the Store copy  (Windows Settings opens at DeskIT App, where
;                           Uninstall is; Continue checks again and the
;                           install goes on once it is gone)
;
; Silent: an UPGRADE of an installed website copy goes on (the app's own
; update must never stall here; the app asks at its next start), a fresh
; silent install (winget) stops with a line in the log.
;
; Included by DeskIT.iss, which calls OneCopyOk first in InitializeSetup.
; The owner approved the words on 2026-10-04 from pictures of them
; (dev\shot_one_copy.py --installer photographs them on the hidden desktop).

[CustomMessages]
english.OneCopyTitle=DeskIT is already on this PC, from the Microsoft Store
english.OneCopyText=One PC keeps one DeskIT: two would share some settings and the cloud keys, and only one can run at a time.%n%nKeep the Store copy and close this installer, or remove the Store copy and install this one. What the Store copy kept only on this PC goes with it; synced words and settings come back from your account.
english.OneCopyKeep=&Keep the Store copy
english.OneCopyRemove=&Remove the Store copy
english.OneCopyWaitTitle=Uninstall DeskIT App in Settings
english.OneCopyWaitText=Windows Settings is open at DeskIT App. Press Uninstall there, then Continue here.
english.OneCopyContinue=&Continue
english.OneCopyCancel=C&ancel
english.OneCopySilent=DeskIT is already installed from the Microsoft Store; one PC keeps one DeskIT. Uninstall DeskIT App first.
hebrew.OneCopyTitle=DeskIT כבר מותקן במחשב הזה, מ־Microsoft Store
hebrew.OneCopyText=במחשב אחד יש DeskIT אחד: שני עותקים היו חולקים חלק מההגדרות ואת מפתחות הענן, ורק אחד מהם יכול לפעול בכל רגע.%n%nאפשר להשאיר את העותק מהחנות ולסגור את ההתקנה, או להסיר את העותק מהחנות ולהתקין את זה. מה שהעותק מהחנות שמר רק במחשב הזה יוסר יחד איתו; מילים והגדרות שסונכרנו יחזרו מהחשבון שלך.
hebrew.OneCopyKeep=&להשאיר את העותק מהחנות
hebrew.OneCopyRemove=&להסיר את העותק מהחנות
hebrew.OneCopyWaitTitle=הסר את DeskIT App בהגדרות
hebrew.OneCopyWaitText=הגדרות Windows פתוחות בעמוד של DeskIT App. לחץ שם על 'הסרת התקנה', ואחר כך על 'המשך' כאן.
hebrew.OneCopyContinue=&המשך
hebrew.OneCopyCancel=&ביטול
hebrew.OneCopySilent=DeskIT כבר מותקן מ־Microsoft Store; במחשב אחד יש DeskIT אחד. הסר קודם את DeskIT App.

[Code]
const
  StoreFamily = 'YoavShimron.DeskITApp_d0r2ms77220w6';
  StoreSettings = 'ms-settings:appsfeatures-app?YoavShimron.DeskITApp_d0r2ms77220w6';

{ Every pointer is a var Cardinal, so its size is the process's own; with
  both counts 0 the call only answers how many there are: ERROR_SUCCESS
  (0) and Count 0 when none, ERROR_INSUFFICIENT_BUFFER (122) when some. }
function GetPackagesByPackageFamily(Family: String; var Count: Cardinal;
  var Names: Cardinal; var BufferLength: Cardinal; var Buffer: Cardinal): Longint;
  external 'GetPackagesByPackageFamily@kernel32.dll stdcall delayload';

function StoreCopyInstalled: Boolean;
var
  Count, Names, BufferLength, Buffer: Cardinal;
begin
  Count := 0; Names := 0; BufferLength := 0; Buffer := 0;
  try
    Result := (GetPackagesByPackageFamily(StoreFamily, Count, Names, BufferLength, Buffer) = 122)
      and (Count > 0);
  except
    Result := False;   { no such call on this Windows: no Store copy either }
  end;
end;

procedure OpenStoreSettings;
var
  ErrorCode: Integer;
begin
  ShellExec('open', StoreSettings, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

{ The question, then — on Remove — the wait. True: go on installing. }
function OneCopyAsk: Boolean;
begin
  Result := False;
  if SuppressibleTaskDialogMsgBox(CustomMessage('OneCopyTitle'), CustomMessage('OneCopyText'),
       mbConfirmation, MB_YESNO, [CustomMessage('OneCopyKeep'), CustomMessage('OneCopyRemove')],
       0, IDYES) = IDYES then
    Exit;
  OpenStoreSettings;
  repeat
    if SuppressibleTaskDialogMsgBox(CustomMessage('OneCopyWaitTitle'), CustomMessage('OneCopyWaitText'),
         mbInformation, MB_OKCANCEL, [CustomMessage('OneCopyContinue'), CustomMessage('OneCopyCancel')],
         0, IDCANCEL) <> IDOK then
      Exit;
  until not StoreCopyInstalled;
  Result := True;
end;

{ Called first thing in InitializeSetup. `Upgrading`: a website copy is
  already installed (its DisplayVersion was found). }
function OneCopyOk(Upgrading: Boolean): Boolean;
begin
  Result := True;
  if not StoreCopyInstalled then
    Exit;
  if WizardSilent then
  begin
    if Upgrading then
      Exit;
    Log(CustomMessage('OneCopySilent'));
    Result := False;
    Exit;
  end;
  Result := OneCopyAsk;
end;
