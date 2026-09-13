"""A headless Android phone for checking the DeskIT keyboard.

    python emu.py create      make the AVD (once)
    python emu.py boot        start it with no window, wait for boot
    python emu.py install     install the freshly built APK, enable the IME
    python emu.py shot NAME   screenshot to NAME.png in this folder
    python emu.py sh CMD...   adb shell CMD
    python emu.py stop        kill the emulator

Nothing appears on the owner's screen: -no-window, and the screenshots
come out through adb.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

SDK = Path(r"C:\Users\shimr\dev-tools\android-sdk")
JDK = Path(r"C:\Users\shimr\dev-tools\jdk")
HERE = Path(__file__).resolve().parent
# Screenshots and logs go next to the script unless told otherwise.
OUT = Path(os.environ.get("DESKIT_EMU_OUT", HERE))
APK = Path(r"C:\Users\shimr\Desktop\Organized\Projects\DeskIT\android\app\build\outputs\apk\debug\app-debug.apk")
AVD = "deskit"
IMAGE = "system-images;android-34;google_apis;x86_64"
ADB = SDK / "platform-tools" / "adb.exe"
EMU = SDK / "emulator" / "emulator.exe"
AVDMGR = SDK / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat"
PKG = "com.yoav.dictation"
IME = f"{PKG}/.DictationIme"

ENV = dict(os.environ, JAVA_HOME=str(JDK), ANDROID_HOME=str(SDK),
           ANDROID_SDK_ROOT=str(SDK))


def run(*args, check=True, capture=True, timeout=120, **kw):
    r = subprocess.run([str(a) for a in args], env=ENV, capture_output=capture,
                       encoding="utf-8", errors="replace", timeout=timeout, **kw)
    if check and r.returncode != 0:
        raise SystemExit(f"{args[0]} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def adb(*args, **kw):
    return run(ADB, *args, **kw)


def create():
    r = run(AVDMGR, "list", "avd", check=False)
    if f"Name: {AVD}" in (r.stdout or ""):
        print("avd exists"); return
    r = subprocess.run([str(AVDMGR), "create", "avd", "-n", AVD, "-k", IMAGE,
                        "-d", "pixel_6", "--force"], env=ENV, input="no\n",
                       capture_output=True, encoding="utf-8", errors="replace")
    print(r.stdout[-800:], r.stderr[-800:])
    if r.returncode != 0:
        raise SystemExit("avdmanager create failed")
    # A little more RAM and a phone-sized screen; the defaults are fine
    # otherwise. config.ini lives in the user's .android.
    ini = Path.home() / ".android" / "avd" / f"{AVD}.avd" / "config.ini"
    if ini.exists():
        text = ini.read_text("utf-8")
        text += "\nhw.ramSize=2048\nhw.keyboard=yes\nhw.gpu.enabled=yes\nhw.gpu.mode=swiftshader_indirect\n"
        ini.write_text(text, "utf-8")
    print("created", AVD)


def boot():
    log = OUT / "emu.log"
    proc = subprocess.Popen(
        [str(EMU), "-avd", AVD, "-no-window", "-no-audio", "-no-boot-anim",
         "-gpu", "swiftshader_indirect", "-no-snapshot",
         # The tailnet name resolves only through MagicDNS on the host.
         "-dns-server", "100.100.100.100"],
        env=ENV, stdout=open(log, "w"), stderr=subprocess.STDOUT,
        # CREATE_NO_WINDOW, not DETACHED_PROCESS: a detached parent has no
        # console, so every console child the emulator spawns (netsimd,
        # the crash handler) opened a window of its own on the owner's
        # screen. A hidden console is inherited by all of them.
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL)
    print("emulator pid", proc.pid)
    deadline = time.time() + 300
    adb("wait-for-device", timeout=300)
    while time.time() < deadline:
        r = adb("shell", "getprop", "sys.boot_completed", check=False, timeout=20)
        if (r.stdout or "").strip() == "1":
            print("booted"); break
        if proc.poll() is not None:
            raise SystemExit("emulator died:\n" + log.read_text("utf-8", errors="replace")[-2000:])
        time.sleep(3)
    else:
        raise SystemExit("boot timed out:\n" + log.read_text("utf-8", errors="replace")[-2000:])
    # Settle, and keep the screen on and unlocked for screenshots.
    time.sleep(5)
    adb("shell", "settings", "put", "global", "window_animation_scale", "0")
    adb("shell", "settings", "put", "global", "transition_animation_scale", "0")
    adb("shell", "settings", "put", "global", "animator_duration_scale", "0")
    adb("shell", "svc", "power", "stayon", "true")
    adb("shell", "input", "keyevent", "82")


def install():
    adb("install", "-r", "-g", APK, timeout=300)
    adb("shell", "ime", "enable", IME)
    adb("shell", "ime", "set", IME)
    print(adb("shell", "ime", "list", "-s").stdout)


def shot(name):
    out = OUT / f"{name}.png"
    r = subprocess.run([str(ADB), "exec-out", "screencap", "-p"], env=ENV,
                       capture_output=True, timeout=60)
    out.write_bytes(r.stdout)
    print("wrote", out, len(r.stdout))


def stop():
    adb("emu", "kill", check=False)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                     # noqa: BLE001
        pass
    cmd = sys.argv[1]
    if cmd == "create":
        create()
    elif cmd == "boot":
        boot()
    elif cmd == "install":
        install()
    elif cmd == "shot":
        shot(sys.argv[2])
    elif cmd == "sh":
        r = adb("shell", *sys.argv[2:], check=False)
        print(r.stdout, r.stderr)
    elif cmd == "stop":
        stop()
