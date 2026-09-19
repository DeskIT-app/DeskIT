' The stranger's copy of this checkout, started the way the installed copy is:
' the installed entry (deskit.pyw), no console, against its own home under
' %LOCALAPPDATA%\DeskIT-dev\stranger (paths.STRANGER; dev\stranger.py says the
' rest). The desktop shortcut "DeskIT" points here. The owner's keys and
' .env are not read; the reset is dev\stranger.py's (--all, --keep).
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set env = shell.Environment("Process")
env("DESKIT_HOME") = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\DeskIT-dev\stranger"
env("DESKIT_STRANGER") = "1"
For Each name In Array("DESKIT_PORTABLE", "GROQ_API_KEY", "GEMINI_API_KEY", "DESKIT_GROQ_API_KEY", "DESKIT_GEMINI_API_KEY")
    env.Remove name
Next
shell.CurrentDirectory = folder
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" """ & folder & "\deskit.pyw""", 0, False
