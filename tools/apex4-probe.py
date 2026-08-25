#!/usr/bin/env python3
"""Apex 4 (old-dialect) hidraw probe: find the vendor collection, map moving bytes.

No dependencies. Run with the pad in DInput mode.
  python3 apex4-probe.py                      # list hidraw nodes + report descriptors
  python3 apex4-probe.py /dev/hidrawN -s 10   # dump reports, report per-byte activity
"""
import argparse, fcntl, glob, os, struct, sys, time

HIDIOCGRDESCSIZE = 0x80044801
HIDIOCGRDESC = 0x90044802
VENDOR_PREFIX = bytes((0x06, 0xA0, 0xFF))  # usage page 0xFFA0


def sysfs(node, *names):
    base = "/sys/class/hidraw/%s/device" % os.path.basename(node)
    out = []
    for n in names:
        for p in (os.path.join(base, n), os.path.join(base, "..", n)):
            try:
                out.append(open(p).read().strip())
                break
            except OSError:
                continue
        else:
            out.append("?")
    return out


def descriptor(fd):
    size = struct.unpack("i", fcntl.ioctl(fd, HIDIOCGRDESCSIZE, struct.pack("i", 0)))[0]
    buf = bytearray(struct.pack("I4096s", size, b""))
    fcntl.ioctl(fd, HIDIOCGRDESC, buf, True)  # >1024B needs a mutable buffer
    return bytes(buf[4:4 + size])


def listing():
    found = []
    for node in sorted(glob.glob("/dev/hidraw*")):
        uevent, name = sysfs(node, "uevent", "../../product")
        ids = dict(l.split("=", 1) for l in uevent.splitlines() if "=" in l)
        hid_id = ids.get("HID_ID", "?")
        hid_name = ids.get("HID_NAME", name)
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            print("%-14s %-38s %s  [cannot open: %s]" % (node, hid_name, hid_id, e.strerror))
            continue
        try:
            rd = descriptor(fd)
        finally:
            os.close(fd)
        vendor = rd.startswith(VENDOR_PREFIX)
        print("%-14s %-38s %s  desc=%dB %s" % (
            node, hid_name[:38], hid_id, len(rd), "<-- VENDOR COLLECTION" if vendor else ""))
        print("               first 16 desc bytes: %s" % rd[:16].hex(" "))
        if vendor:
            found.append(node)
    return found


def sample(node, seconds):
    fd = os.open(node, os.O_RDONLY)
    lo, hi, count, first = {}, {}, 0, None
    deadline = time.time() + seconds
    print("reading %s for %ss -- move the pad / squeeze one trigger" % (node, seconds))
    try:
        while time.time() < deadline:
            data = os.read(fd, 64)
            count += 1
            if first is None:
                first = data
                print("first report (%dB): %s" % (len(data), data.hex(" ")))
            for i, b in enumerate(data):
                lo[i] = min(lo.get(i, b), b)
                hi[i] = max(hi.get(i, b), b)
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)
    print("\n%d reports (~%.0f Hz)" % (count, count / seconds if seconds else 0))
    print("byte  min  max  span")
    for i in sorted(lo):
        span = hi[i] - lo[i]
        if span:
            print("%4d  %3d  %3d  %4d  %s" % (i, lo[i], hi[i], span, "#" * min(span // 4, 40)))
    static = [i for i in sorted(lo) if hi[i] == lo[i]]
    print("static bytes: %s" % (static or "none"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("node", nargs="?")
    ap.add_argument("-s", "--seconds", type=float, default=8.0)
    a = ap.parse_args()
    if a.node:
        sample(a.node, a.seconds)
    else:
        cands = listing()
        print("\nvendor-collection nodes: %s" % (cands or "NONE -- pad is probably not in DInput mode"))
