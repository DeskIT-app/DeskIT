' Starts Hebrew dictation in the background: no console window, nothing in
' the taskbar. Two rising beeps mean it is listening.
' Stop it with "Stop Dictation.vbs".
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" """ & folder & "\main.py""", 0, False
