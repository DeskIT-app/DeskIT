' The owner's master app: dev\master\web\dist in a WebView2 window, with no
' console behind it (pythonw). Nothing of the running DeskIT is touched — the
' master reads files, git, GitHub and the account server, and writes only its
' own state and the folders an export makes.
'
' Put a shortcut to this on the desktop and call it "DeskIT Master".
' The pages must be built once:  cd dev\master\web  &&  npm install  &&  npm run build
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
shell.CurrentDirectory = folder
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" -m dev.master.window", 0, False
