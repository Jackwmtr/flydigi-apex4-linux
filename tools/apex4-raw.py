#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Continuous raw capture of a HID stream: timestamp + payload, until a time cap.

Flushes on a timer rather than every N reports, and flushes on SIGTERM. Both
matter: an earlier version flushed every 2000 reports, which is a fraction of a
second on the pad's 1000 Hz vendor stream and *several minutes* over Bluetooth,
where reports only arrive on change -- so a Bluetooth capture looked like an
empty file while all of it sat in a buffer waiting to be killed off by systemd.
"""
import os, select, signal, struct, sys, time

FLUSH_EVERY = 0.5   # seconds


def main(node, seconds, out):
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(True))
    signal.signal(signal.SIGINT, lambda *_: stop.append(True))
    t0 = time.time()
    n = 0
    next_flush = t0 + FLUSH_EVERY
    with open(out, "wb") as f:
        while not stop and time.time() - t0 < seconds:
            if not select.select([fd], [], [], 0.2)[0]:
                if time.time() >= next_flush:
                    f.flush()
                    next_flush = time.time() + FLUSH_EVERY
                continue
            payload = os.read(fd, 64)
            f.write(struct.pack("dB", time.time() - t0, len(payload)) + payload)
            n += 1
            if time.time() >= next_flush:
                f.flush()
                os.fsync(f.fileno())
                next_flush = time.time() + FLUSH_EVERY
    os.close(fd)
    print("%d reports -> %s" % (n, out))


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), sys.argv[3])
