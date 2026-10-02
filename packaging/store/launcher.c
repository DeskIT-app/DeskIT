/* DeskIT.exe, DeskITQuiet.exe and DeskITHook.exe: the Store package's
 * three doors into the same tree (DISTRIBUTION_PLAN.md 10.7).
 *
 * An MSIX application is an executable with no arguments field, and the
 * working directory Windows gives a packaged desktop app is not the
 * package's folder. So the package cannot name python\pythonw.exe with
 * app\deskit.pyw beside it; it names this, compiled three times:
 *
 *   DeskIT.exe       python\pythonw.exe app\deskit.pyw          (Start)
 *   DeskITQuiet.exe  python\pythonw.exe app\deskit.pyw --quiet  (logon)
 *   DeskITHook.exe   python\pythonw.exe app\notify_hook.py      (alias)
 *
 * Everything it does: find its own folder, point Python's bytecode cache
 * at %LOCALAPPDATA%\DeskIT\cache\pycache (the package folder is read-only,
 * and without a writable cache every start compiles every module again),
 * start the interpreter with the package root as the working directory and
 * its own arguments passed through, hand over its standard handles when it
 * has any (the hook's stdin is Claude Code's event), wait, and exit with
 * the interpreter's exit code. No network, no registry, no files written.
 * A start that fails says so in a message box, except the hook's, which
 * runs on every Claude turn and must fail in silence like notify_hook.py.
 *
 * Built by packaging/store/build_msix.ps1 (cl /O1, the static CRT, the
 * GUI subsystem: no console ever opens).
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

/* Which door: cl /DDESKIT_VARIANT=1 or 2 (a number, so no quoted string
 * has to survive cmd.exe on the way in). */
#ifndef DESKIT_VARIANT
#define DESKIT_VARIANT 0
#endif
#if DESKIT_VARIANT == 1                 /* DeskITQuiet.exe */
#define DESKIT_SCRIPT L"deskit.pyw"
#define DESKIT_EXTRA L"--quiet"
#elif DESKIT_VARIANT == 2               /* DeskITHook.exe */
#define DESKIT_SCRIPT L"notify_hook.py"
#define DESKIT_EXTRA L""
#define DESKIT_SILENT
#else                                   /* DeskIT.exe */
#define DESKIT_SCRIPT L"deskit.pyw"
#define DESKIT_EXTRA L""
#endif

#define LONG_PATH 32768

static void say(const wchar_t *what, DWORD code)
{
#ifndef DESKIT_SILENT
    wchar_t text[512];
    swprintf(text, 512, L"DeskIT could not start: %ls (Windows error %lu).", what, code);
    MessageBoxW(NULL, text, L"DeskIT", MB_OK | MB_ICONERROR);
#else
    (void)what;
    (void)code;
#endif
}

static int valid(HANDLE h)
{
    return h != NULL && h != INVALID_HANDLE_VALUE;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show)
{
    static wchar_t root[LONG_PATH], exe[LONG_PATH], local[LONG_PATH], cache[LONG_PATH];
    wchar_t *slash, *line;
    size_t size;
    DWORD n, code = 1;
    BOOL inherit = FALSE;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;

    (void)instance;
    (void)previous;
    (void)show;

    n = GetModuleFileNameW(NULL, root, LONG_PATH);
    if (n == 0 || n >= LONG_PATH) {
        say(L"its own folder could not be read", GetLastError());
        return 1;
    }
    slash = wcsrchr(root, L'\\');
    if (slash == NULL) {
        say(L"its own folder could not be read", ERROR_BAD_PATHNAME);
        return 1;
    }
    *slash = L'\0';

    n = GetEnvironmentVariableW(L"LOCALAPPDATA", local, LONG_PATH);
    if (n > 0 && n < LONG_PATH - 64) {
        swprintf(cache, LONG_PATH, L"%ls\\DeskIT\\cache\\pycache", local);
        SetEnvironmentVariableW(L"PYTHONPYCACHEPREFIX", cache);
    }

    swprintf(exe, LONG_PATH, L"%ls\\python\\pythonw.exe", root);
    if (args == NULL) {
        args = L"";
    }
    size = wcslen(exe) + wcslen(root) + wcslen(DESKIT_SCRIPT) + wcslen(DESKIT_EXTRA)
           + wcslen(args) + 32;
    line = (wchar_t *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, size * sizeof(wchar_t));
    if (line == NULL) {
        say(L"out of memory", ERROR_NOT_ENOUGH_MEMORY);
        return 1;
    }
    swprintf(line, size, L"\"%ls\" \"%ls\\app\\%ls\"%ls%ls%ls%ls",
             exe, root, DESKIT_SCRIPT,
             DESKIT_EXTRA[0] ? L" " : L"", DESKIT_EXTRA,
             args[0] ? L" " : L"", args);

    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    if (valid(si.hStdInput) || valid(si.hStdOutput) || valid(si.hStdError)) {
        si.dwFlags = STARTF_USESTDHANDLES;
        inherit = TRUE;
    }
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(exe, line, NULL, NULL, inherit, 0, NULL, root, &si, &pi)) {
        say(L"python\\pythonw.exe did not start", GetLastError());
        HeapFree(GetProcessHeap(), 0, line);
        return 1;
    }
    HeapFree(GetProcessHeap(), 0, line);
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    if (!GetExitCodeProcess(pi.hProcess, &code)) {
        code = 1;
    }
    CloseHandle(pi.hProcess);
    return (int)code;
}
