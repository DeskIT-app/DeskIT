; A Setup that installs nothing and only asks packaging\one_copy.iss's
; question — the prototype's picture of the installer's half
; (dev\proto_one_copy.py --installer compiles it and photographs it on the
; hidden desktop). /SHOW=wait shows the second dialog instead of the first.
;
;     ISCC.exe dev\proto_one_copy_setup.iss /O<folder>

[Setup]
AppId={{2B0C8E4A-0D5B-4C1E-9B7E-5F0E0C0DE5C0}
AppName=DeskIT
AppVersion=0.0.0
DefaultDirName={localappdata}\DeskIT-one-copy-prototype
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
Uninstallable=no
CreateAppDir=no
OutputBaseFilename=one-copy-prototype
SetupIconFile=..\icon.ico
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Messages]
english.SetupWindowTitle=%1
hebrew.SetupWindowTitle=%1

#include "..\packaging\one_copy.iss"

[Code]
function InitializeSetup: Boolean;
begin
  Result := False;
  { /SHOW=detect /OUT=<file>: the detection alone, written out — proof
    that the kernel32 call answers inside Inno's 32-bit Setup }
  if ExpandConstant('{param:SHOW|ask}') = 'detect' then
    SaveStringToFile(ExpandConstant('{param:OUT}'), Format('store installed: %d', [Ord(StoreCopyInstalled)]), False)
  else if ExpandConstant('{param:SHOW|ask}') = 'wait' then
    SuppressibleTaskDialogMsgBox(CustomMessage('OneCopyWaitTitle'), CustomMessage('OneCopyWaitText'),
      mbInformation, MB_OKCANCEL, [CustomMessage('OneCopyContinue'), CustomMessage('OneCopyCancel')],
      0, IDCANCEL)
  else
    SuppressibleTaskDialogMsgBox(CustomMessage('OneCopyTitle'), CustomMessage('OneCopyText'),
      mbConfirmation, MB_YESNO, [CustomMessage('OneCopyKeep'), CustomMessage('OneCopyRemove')],
      0, IDYES);
end;
