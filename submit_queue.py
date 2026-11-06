"""
Submit Queue
----------------
Takes multiple alpha IDs and processes them one at a time: review,
confirm (or skip), submit, verify ACTIVE — same safety pattern as
submit.py, just chained across a list instead of one command per alpha.

Does NOT blind-submit everything — you still confirm each one
individually. This saves re-typing `python submit.py <id>` repeatedly,
not the judgment step itself.

Usage:
    python submit_queue.py <alpha_id_1> <alpha_id_2> <alpha_id_3> ...

    python submit_queue.py KPNMeQNz O0NXv7vd 1YZVjpa6

Or from a file (one alpha ID per line):
    python submit_queue.py --file queue.txt
"""

import sys
import time

from auth import WQSession
from submit import get_alpha, show_summary, submit_alpha


def load_ids_from_file(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            print("Usage: python submit_queue.py --file <path>")
            sys.exit(1)
        alpha_ids = load_ids_from_file(sys.argv[2])
    else:
        alpha_ids = sys.argv[1:]

    if not alpha_ids:
        print("No alpha IDs to process.")
        sys.exit(0)

    print(f"Queue: {len(alpha_ids)} alpha(s) — {', '.join(alpha_ids)}\n")

    session = WQSession()
    session.login()

    submitted, skipped, failed = [], [], []

    for i, alpha_id in enumerate(alpha_ids):
        print(f"\n{'#'*60}")
        print(f"# [{i+1}/{len(alpha_ids)}] {alpha_id}")
        print(f"{'#'*60}")

        try:
            alpha = get_alpha(session.session, alpha_id)
        except Exception as e:
            print(f"Could not fetch {alpha_id}: {e} — skipping.")
            failed.append(alpha_id)
            continue

        show_summary(alpha)

        choice = input(
            f"\n[{i+1}/{len(alpha_ids)}] Type 'yes' to submit {alpha_id}, "
            f"'skip' to move to the next one, or 'stop' to end the queue here: "
        ).strip().lower()

        if choice == "stop":
            print("Stopping queue — remaining alphas not processed.")
            break
        elif choice != "yes":
            print(f"Skipped {alpha_id}.")
            skipped.append(alpha_id)
            continue

        try:
            submit_alpha(session.session, alpha_id)
            submitted.append(alpha_id)
        except Exception as e:
            print(f"Error submitting {alpha_id}: {e}")
            failed.append(alpha_id)

        if i < len(alpha_ids) - 1:
            time.sleep(3)  # brief pause between queue items

    print(f"\n{'='*60}")
    print("QUEUE COMPLETE")
    print(f"{'='*60}")
    print(f"Submitted: {submitted if submitted else 'none'}")
    print(f"Skipped:   {skipped if skipped else 'none'}")
    print(f"Failed:    {failed if failed else 'none'}")
    print("\nNote: 'Submitted' here means the request was sent and verified —")
    print("check each one's actual status with check_status_batch.py if any")
    print("are still showing PENDING on SELF_CORRELATION.")


if __name__ == "__main__":
    main()