"""Real POSTs from the phone to a live fake, fast and then slowly enough that the
server has dropped the connection each time: how many arrive, and what the rest
died of. A failure a flow meets once in a hundred requests shows up here.

    python post_stress.py [fast] [slow]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive                                     # noqa: E402
import flow_account as flow                      # noqa: E402


def run(acct, count: int, gap_ms: int) -> None:
    before = len(acct.events("stress"))
    drive.logcat_clear()
    t0 = time.time()
    limit = 30 + count * (gap_ms + 200) / 1000
    # Android 14 holds `am broadcast` until the receiver is done
    drive.shell("am", "broadcast", "-n", f"{drive.PKG}/.ProbeReceiver",
                "--ei", "posts", count, "--el", "gap", gap_ms, timeout=limit)
    while time.time() - t0 < limit:
        if "posts done" in drive.logcat():
            break
        time.sleep(1)
    got = len(acct.events("stress")) - before
    bad = [ln for ln in drive.logcat().splitlines() if "account:" in ln]
    print(f"{count} POSTs {gap_ms} ms apart: {got} arrived, {len(bad)} failed, "
          f"{time.time() - t0:.0f} s", flush=True)
    for ln in bad[:6]:
        print("  ", ln[30:170], flush=True)


def main() -> None:
    fast = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    slow = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    acct = flow.fresh()
    try:
        flow.join(acct)
        run(acct, fast, 0)
        run(acct, slow, 2300)                    # the fake drops an idle socket at 2 s
    finally:
        acct.stop()


if __name__ == "__main__":
    main()
