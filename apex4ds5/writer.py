# SPDX-License-Identifier: MIT
"""Everything sent to the pad goes through one thread, latest value wins.

A write to the vendor interface is not free: it goes out on an interrupt OUT
endpoint polled every 2 ms, and the write blocks until its slot -- measured at
~2 ms each, O_NONBLOCK or not. That used to happen inline, once per changed
rumble level, inside the loop that drains the game's output reports. A game
driving "haptics" through rumble (Ghostwire: Tokyo) changes the level in
nearly every report, hundreds a second; the drain then spent all its time in
writes and the input reports -- sticks, buttons -- waited behind it. The pad
answered late for as long as the haptics ran.

So the relay only *submits*, and this thread writes:

* **Per key, only the newest packet is kept.** A rumble level that was replaced
  before it could be sent is not worth sending: the motors cannot play levels
  that last a few milliseconds, and sending them anyway is what flooded the
  2.4 GHz link.
* **Rumble is paced** to RUMBLE_INTERVAL_S. Trigger effects are not -- they are
  rare, and their own repeat schedule lives in triggers.py.
* The fd is used under the link's lock, so the main loop can close it without
  this thread writing to a number that has meanwhile been reused.
"""
import os, threading, time

RUMBLE = "rumble"
RUMBLE_INTERVAL_S = 0.015


class PadWriter(threading.Thread):
    def __init__(self, link):
        super().__init__(name="pad-writer", daemon=True)
        self.link = link
        self.cond = threading.Condition()
        self.pending = {}            # key -> newest packet not yet written
        self.stopping = False
        self.failed = False          # a write failed; the loop drops the fd
        self.next_rumble = 0.0
        self.submitted = 0
        self.written = 0

    def submit(self, key, packet):
        """Queue a packet; replaces anything still pending under that key."""
        with self.cond:
            self.pending[key] = packet
            self.submitted += 1
            self.cond.notify()

    def discard(self):
        """Forget pending writes -- the pad they were meant for is gone."""
        with self.cond:
            self.pending.clear()

    def stop(self):
        with self.cond:
            self.stopping = True
            self.cond.notify()
        self.join(timeout=1.0)

    def _next(self):
        """(key, packet) to write now, or (None, seconds to wait)."""
        now = time.monotonic()
        for key in self.pending:
            if key != RUMBLE:
                return key, self.pending.pop(key)
        if RUMBLE in self.pending:
            if now >= self.next_rumble:
                self.next_rumble = now + RUMBLE_INTERVAL_S
                return RUMBLE, self.pending.pop(RUMBLE)
            return None, self.next_rumble - now
        return None, None

    def run(self):
        while True:
            with self.cond:
                while True:
                    if self.stopping:
                        return
                    key, item = self._next()
                    if key is not None:
                        break
                    self.cond.wait(item)
            with self.link.lock:
                fd = self.link.vendor_fd
                if fd is None:
                    continue
                try:
                    os.write(fd, item)
                    self.written += 1
                except OSError:
                    self.failed = True
