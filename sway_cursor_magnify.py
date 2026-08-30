#!/usr/bin/env python3
"""Magnify the sway cursor while it is moving quickly.

Polls the seat's pointer position over the sway IPC socket, estimates the
pointer speed, and grows the xcursor theme size while the pointer is moving
faster than a threshold so that it is easy to find on a large display.

Requires a sway build whose GET_SEATS reply includes the "cursor" object
(x/y/hidden) -- see the sway-local-patches skill. Upstream sway 1.12 does not
have it, and this script exits with a clear error in that case.
"""

import argparse
import json
import os
import signal
import socket
import struct
import sys
import time

MAGIC = b"i3-ipc"
HEADER = struct.Struct("=6sII")
RUN_COMMAND = 0
GET_SEATS = 101


class SwayIPC:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)

    def _recv_exactly(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("sway closed the IPC connection")
            buf += chunk
        return buf

    def request(self, msg_type, payload=b""):
        self.sock.sendall(HEADER.pack(MAGIC, len(payload), msg_type) + payload)
        _, length, _ = HEADER.unpack(self._recv_exactly(HEADER.size))
        return json.loads(self._recv_exactly(length))

    def command(self, cmd):
        return self.request(RUN_COMMAND, cmd.encode())

    def close(self):
        self.sock.close()


def find_seat(ipc, wanted):
    """Return (seat_name, cursor) for the seat to track."""
    seats = ipc.request(GET_SEATS)
    for seat in seats:
        if wanted and seat["name"] != wanted:
            continue
        if "cursor" not in seat:
            raise SystemExit(
                "error: this sway build's GET_SEATS has no 'cursor' field.\n"
                "       Run a sway built from the cursor-magnify-on-fast-move_with_ai\n"
                "       branch (see the sway-local-patches skill)."
            )
        if seat["cursor"] is not None:
            return seat["name"], seat["cursor"]
    raise SystemExit("error: no seat with a pointer found")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=1500.0,
                    help="speed in layout px/sec above which the cursor grows "
                         "(default: %(default)s)")
    ap.add_argument("--scale", type=float, default=2.5,
                    help="size multiplier while moving fast (default: %(default)s)")
    ap.add_argument("--base-size", type=int, default=24,
                    help="normal xcursor size, must match your seat's "
                         "xcursor_theme size (default: %(default)s)")
    ap.add_argument("--theme", default=os.environ.get("XCURSOR_THEME") or "default",
                    help="xcursor theme name (default: $XCURSOR_THEME or 'default')")
    ap.add_argument("--rate", type=float, default=60.0,
                    help="polling rate in Hz (default: %(default)s)")
    ap.add_argument("--smoothing", type=float, default=0.4,
                    help="EMA weight of each new sample, 0..1; lower is smoother "
                         "(default: %(default)s)")
    ap.add_argument("--hysteresis", type=float, default=0.5,
                    help="shrink only below threshold*this, to avoid flapping "
                         "(default: %(default)s)")
    ap.add_argument("--linger", type=float, default=0.3,
                    help="seconds to stay magnified after dropping below the "
                         "shrink threshold (default: %(default)s)")
    ap.add_argument("--seat", default=None, help="seat name (default: first with a pointer)")
    ap.add_argument("--verbose", action="store_true", help="log speed and transitions")
    ap.add_argument("--benchmark", action="store_true",
                    help="measure IPC poll cost and exit")
    args = ap.parse_args()

    sock_path = os.environ.get("SWAYSOCK")
    if not sock_path:
        raise SystemExit("error: SWAYSOCK is not set")

    ipc = SwayIPC(sock_path)
    seat, cursor = find_seat(ipc, args.seat)

    if args.benchmark:
        n = 300
        start = time.monotonic()
        for _ in range(n):
            ipc.request(GET_SEATS)
        elapsed = time.monotonic() - start
        print(f"{n} GET_SEATS round trips in {elapsed*1000:.1f} ms "
              f"({elapsed/n*1000:.3f} ms each, max ~{n/elapsed:.0f} Hz)")
        return

    big = max(1, int(round(args.base_size * args.scale)))
    interval = 1.0 / args.rate
    shrink_at = args.threshold * args.hysteresis

    magnified = False
    speed = 0.0
    last_x, last_y = cursor["x"], cursor["y"]
    last_t = time.monotonic()
    slow_since = None

    def set_size(size):
        reply = ipc.command(f'seat {seat} xcursor_theme "{args.theme}" {size}')
        for result in reply:
            if not result.get("success", True):
                print(f"warning: {result.get('error', 'command failed')}",
                      file=sys.stderr, flush=True)
                return False
        return True

    def restore(*_):
        if magnified:
            try:
                set_size(args.base_size)
            except Exception:
                pass
        ipc.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, restore)
    signal.signal(signal.SIGTERM, restore)

    if args.verbose:
        print(f"seat={seat} theme={args.theme} {args.base_size}->{big} "
              f"threshold={args.threshold} shrink_at={shrink_at:.0f} rate={args.rate}Hz",
              flush=True)

    while True:
        time.sleep(interval)
        try:
            _, cur = find_seat(ipc, seat)
        except ConnectionError:
            break
        now = time.monotonic()
        dt = now - last_t
        last_t = now
        if dt <= 0:
            continue

        dx = cur["x"] - last_x
        dy = cur["y"] - last_y
        last_x, last_y = cur["x"], cur["y"]
        sample = (dx * dx + dy * dy) ** 0.5 / dt
        # Exponential moving average so one jittery sample cannot toggle us.
        speed += (sample - speed) * args.smoothing

        if not magnified and speed > args.threshold and not cur["hidden"]:
            if set_size(big):
                magnified = True
                slow_since = None
                if args.verbose:
                    print(f"grow   speed={speed:8.0f} px/s", flush=True)
        elif magnified:
            if speed < shrink_at:
                slow_since = slow_since or now
                if now - slow_since >= args.linger:
                    set_size(args.base_size)
                    magnified = False
                    slow_since = None
                    if args.verbose:
                        print(f"shrink speed={speed:8.0f} px/s", flush=True)
            else:
                slow_since = None

    restore()


if __name__ == "__main__":
    main()
