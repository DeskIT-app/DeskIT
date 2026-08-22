' Choose which version of Hebrew dictation runs: the proven classic one
' or the faster experiment. Stops and restarts the app for you.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" """ & folder & "\versions.py"" --gui", 0, False
