import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


CAPTCHA_SIGNAL_KEYWORDS = (
    "captcha/risk-control encountered",
    "response [461",
    "risk_page",
    "\u5b89\u5168\u9a8c\u8bc1",
    "website-login/captcha",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the existing Xiaohongshu crawler main.py in multiple batches."
    )
    parser.add_argument("--rounds", type=int, default=12, help="Total number of rounds to run.")
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=10,
        help="Minutes to wait between rounds.",
    )
    parser.add_argument(
        "--python-exe",
        default=r".\.venv\Scripts\python.exe",
        help=r"Python executable used to run main.py. Default: .\.venv\Scripts\python.exe",
    )
    parser.add_argument(
        "--main-script",
        default="main.py",
        help="Main crawler script path. Default: main.py",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop remaining rounds immediately if any round exits with non-zero return code.",
    )
    parser.add_argument(
        "--captcha-wait-minutes",
        type=float,
        default=10,
        help="Maximum minutes to wait for manual captcha/risk-page recovery within the same round.",
    )
    parser.add_argument(
        "--captcha-status-interval-seconds",
        type=float,
        default=5,
        help="Seconds between status reminders while waiting for the user to press Enter after captcha/risk-page is detected.",
    )
    return parser.parse_args()


def format_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def resolve_path(project_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (project_root / candidate).resolve()


def validate_args(args: argparse.Namespace, project_root: Path) -> tuple[Path, Path]:
    if args.rounds <= 0:
        raise ValueError("--rounds must be greater than 0")
    if args.interval_minutes < 0:
        raise ValueError("--interval-minutes must be >= 0")
    if args.captcha_wait_minutes < 0:
        raise ValueError("--captcha-wait-minutes must be >= 0")
    if args.captcha_status_interval_seconds <= 0:
        raise ValueError("--captcha-status-interval-seconds must be greater than 0")

    python_exe = resolve_path(project_root, args.python_exe)
    main_script = resolve_path(project_root, args.main_script)

    if not python_exe.exists():
        raise FileNotFoundError(f"Python executable not found: {python_exe}")
    if not main_script.exists():
        raise FileNotFoundError(f"Main script not found: {main_script}")

    return python_exe, main_script


def contains_captcha_signal(line: str) -> bool:
    normalized_line = str(line or "").strip().lower()
    if not normalized_line:
        return False
    return any(keyword in normalized_line for keyword in CAPTCHA_SIGNAL_KEYWORDS)


def sleep_between_rounds(interval_minutes: float) -> None:
    sleep_seconds = int(interval_minutes * 60)
    if sleep_seconds <= 0:
        return
    print(
        f"[run_xhs_batches] Waiting {interval_minutes} minutes ({sleep_seconds} seconds) before next round...",
        flush=True,
    )
    time.sleep(sleep_seconds)


def sleep_before_retry(wait_seconds: float, remaining_seconds: float) -> None:
    actual_wait = max(0.0, min(wait_seconds, remaining_seconds))
    if actual_wait <= 0:
        return
    print(
        f"[run_xhs_batches] Waiting {actual_wait:.1f} seconds before retrying current round. "
        f"Remaining captcha recovery window: {remaining_seconds:.1f} seconds",
        flush=True,
    )
    time.sleep(actual_wait)


def wait_for_manual_recovery(max_wait_seconds: float, status_interval_seconds: float) -> bool:
    print(
        "[run_xhs_batches] Please complete captcha/verification in the browser, then press Enter to retry this same round.",
        flush=True,
    )
    if max_wait_seconds <= 0:
        return False

    if os.name == "nt":
        return _wait_for_enter_windows(max_wait_seconds, status_interval_seconds)
    return _wait_for_enter_generic(max_wait_seconds, status_interval_seconds)


def _wait_for_enter_windows(max_wait_seconds: float, status_interval_seconds: float) -> bool:
    import msvcrt

    while msvcrt.kbhit():
        try:
            msvcrt.getwch()
        except Exception:
            break

    deadline = time.monotonic() + max_wait_seconds
    next_status_at = time.monotonic()
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return False

        current_ts = time.monotonic()
        if current_ts >= next_status_at:
            print(
                f"[run_xhs_batches] Waiting for Enter to retry current round. "
                f"Remaining captcha recovery window: {remaining_seconds:.1f} seconds",
                flush=True,
            )
            next_status_at = current_ts + max(1.0, status_interval_seconds)

        if msvcrt.kbhit():
            try:
                char = msvcrt.getwch()
            except KeyboardInterrupt:
                raise
            except Exception:
                char = ""

            if char in ("\r", "\n"):
                print("[run_xhs_batches] Enter received, retrying current round now.", flush=True)
                return True

        time.sleep(0.2)


def _wait_for_enter_generic(max_wait_seconds: float, status_interval_seconds: float) -> bool:
    input_queue: "queue.Queue[bool]" = queue.Queue()

    def _read_enter() -> None:
        try:
            input()
            input_queue.put(True)
        except Exception:
            input_queue.put(False)

    reader_thread = threading.Thread(target=_read_enter, daemon=True)
    reader_thread.start()

    deadline = time.monotonic() + max_wait_seconds
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return False

        print(
            f"[run_xhs_batches] Waiting for Enter to retry current round. "
            f"Remaining captcha recovery window: {remaining_seconds:.1f} seconds",
            flush=True,
        )
        timeout_seconds = min(max(1.0, status_interval_seconds), remaining_seconds)
        try:
            if input_queue.get(timeout=timeout_seconds):
                print("[run_xhs_batches] Enter received, retrying current round now.", flush=True)
                return True
        except queue.Empty:
            continue


def run_main_attempt(
    round_index: int,
    total_rounds: int,
    attempt_index: int,
    python_exe: Path,
    main_script: Path,
    project_root: Path,
) -> Dict[str, Any]:
    if attempt_index == 1:
        print(
            f"[run_xhs_batches] Round {round_index}/{total_rounds} started at {format_now()}",
            flush=True,
        )
    else:
        print(
            f"[run_xhs_batches] Retrying current round after captcha/risk-page recovery wait. "
            f"This is still round {round_index}/{total_rounds}, retry #{attempt_index}.",
            flush=True,
        )

    print(
        f"[run_xhs_batches] Executing: {python_exe} -u {main_script}",
        flush=True,
    )

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [str(python_exe), "-u", str(main_script)],
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    captcha_detected = False
    captcha_detected_at_monotonic: Optional[float] = None
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            print(line, flush=True)
            if not captcha_detected and contains_captcha_signal(line):
                captcha_detected = True
                captcha_detected_at_monotonic = time.monotonic()
                print(
                    f"[run_xhs_batches] Captcha/risk_page signal detected in round {round_index}/{total_rounds}, "
                    f"attempt #{attempt_index}.",
                    flush=True,
                )
        returncode = process.wait()
    except KeyboardInterrupt:
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        raise
    finally:
        if process.stdout:
            process.stdout.close()

    return {
        "returncode": returncode,
        "captcha_detected": captcha_detected,
        "captcha_detected_at_monotonic": captcha_detected_at_monotonic,
        "attempt_index": attempt_index,
    }


def run_round(
    round_index: int,
    total_rounds: int,
    python_exe: Path,
    main_script: Path,
    project_root: Path,
    captcha_wait_minutes: float,
    captcha_status_interval_seconds: float,
) -> Dict[str, Any]:
    attempt_index = 1
    max_wait_seconds = max(0.0, captcha_wait_minutes * 60)
    captcha_encountered = False
    captcha_wait_started_at_monotonic: Optional[float] = None
    last_returncode = 1

    while True:
        attempt_result = run_main_attempt(
            round_index=round_index,
            total_rounds=total_rounds,
            attempt_index=attempt_index,
            python_exe=python_exe,
            main_script=main_script,
            project_root=project_root,
        )
        last_returncode = int(attempt_result["returncode"])
        attempt_captcha_detected = bool(attempt_result["captcha_detected"])
        captcha_encountered = captcha_encountered or attempt_captcha_detected

        if not attempt_captcha_detected and last_returncode == 0:
            print(
                f"[run_xhs_batches] Round {round_index}/{total_rounds} finished at {format_now()}, "
                f"returncode={last_returncode}, captcha_encountered={captcha_encountered}, round_succeeded=True",
                flush=True,
            )
            return {
                "success": True,
                "returncode": last_returncode,
                "captcha_encountered": captcha_encountered,
                "attempts": attempt_index,
            }

        if attempt_captcha_detected:
            detected_at = attempt_result.get("captcha_detected_at_monotonic")
            if captcha_wait_started_at_monotonic is None:
                captcha_wait_started_at_monotonic = (
                    float(detected_at) if detected_at is not None else time.monotonic()
                )
            elapsed_seconds = time.monotonic() - captcha_wait_started_at_monotonic
            remaining_seconds = max_wait_seconds - elapsed_seconds
            print(
                f"[run_xhs_batches] Round {round_index}/{total_rounds} detected captcha/risk_page. "
                "Please complete captcha/verification in the browser window.",
                flush=True,
            )
            if remaining_seconds <= 0:
                print(
                    f"[run_xhs_batches] Captcha recovery timed out for round {round_index}/{total_rounds}. "
                    f"returncode={last_returncode}, captcha_encountered=True, round_succeeded=False",
                    flush=True,
                )
                return {
                    "success": False,
                    "returncode": last_returncode,
                    "captcha_encountered": True,
                    "attempts": attempt_index,
                    "reason": "captcha_wait_timeout",
                }

            print(
                f"[run_xhs_batches] Waiting for manual captcha recovery on the same round. "
                f"Remaining wait window: {remaining_seconds:.1f} seconds",
                flush=True,
            )
            recovered = wait_for_manual_recovery(remaining_seconds, captcha_status_interval_seconds)
            if not recovered:
                print(
                    f"[run_xhs_batches] Captcha recovery timed out for round {round_index}/{total_rounds}. "
                    f"User did not press Enter within the allowed window.",
                    flush=True,
                )
                return {
                    "success": False,
                    "returncode": last_returncode,
                    "captcha_encountered": True,
                    "attempts": attempt_index,
                    "reason": "captcha_wait_timeout",
                }
            attempt_index += 1
            continue

        print(
            f"[run_xhs_batches] Round {round_index}/{total_rounds} finished at {format_now()}, "
            f"returncode={last_returncode}, captcha_encountered={captcha_encountered}, round_succeeded=False",
            flush=True,
        )
        return {
            "success": False,
            "returncode": last_returncode,
            "captcha_encountered": captcha_encountered,
            "attempts": attempt_index,
            "reason": "non_zero_returncode",
        }


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent

    try:
        python_exe, main_script = validate_args(args, project_root)
    except Exception as exc:
        print(f"[run_xhs_batches] Argument validation failed: {exc}", flush=True)
        return 2

    print(f"[run_xhs_batches] Batch scheduler started at {format_now()}", flush=True)
    print(
        f"[run_xhs_batches] rounds={args.rounds}, interval_minutes={args.interval_minutes}, "
        f"python_exe={python_exe}, main_script={main_script}, cwd={project_root}, "
        f"stop_on_failure={args.stop_on_failure}, captcha_wait_minutes={args.captcha_wait_minutes}, "
        f"captcha_status_interval_seconds={args.captcha_status_interval_seconds}",
        flush=True,
    )

    success_count = 0
    failed_count = 0

    try:
        for round_index in range(1, args.rounds + 1):
            round_result = run_round(
                round_index=round_index,
                total_rounds=args.rounds,
                python_exe=python_exe,
                main_script=main_script,
                project_root=project_root,
                captcha_wait_minutes=args.captcha_wait_minutes,
                captcha_status_interval_seconds=args.captcha_status_interval_seconds,
            )

            if round_result["success"]:
                success_count += 1
            else:
                failed_count += 1
                print(
                    f"[run_xhs_batches] Round {round_index} failed with returncode={round_result['returncode']}, "
                    f"captcha_encountered={round_result['captcha_encountered']}, "
                    f"reason={round_result.get('reason', 'unknown')}",
                    flush=True,
                )
                if args.stop_on_failure:
                    print(
                        "[run_xhs_batches] stop-on-failure is enabled, stopping remaining rounds early.",
                        flush=True,
                    )
                    break

            if round_index < args.rounds:
                sleep_between_rounds(args.interval_minutes)

    except KeyboardInterrupt:
        print(
            f"[run_xhs_batches] Interrupted by user at {format_now()}, stopping batch scheduler.",
            flush=True,
        )
        print(
            f"[run_xhs_batches] Partial summary: success_rounds={success_count}, failed_rounds={failed_count}",
            flush=True,
        )
        return 130

    print(
        f"[run_xhs_batches] Batch scheduler finished at {format_now()}, "
        f"success_rounds={success_count}, failed_rounds={failed_count}",
        flush=True,
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
