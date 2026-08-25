#!/usr/bin/env python3
"""Axis-aligned ellipsoid fit of the accelerometer, over any number of captures.

Solves for per-axis scale and bias from the one physical fact available: at rest
the measured vector must have constant length. Fits
    A*x^2 + B*x + C*y^2 + D*y + E*z^2 + F*z = 1
by least squares over samples that are actually at rest (gyro quiet), then reads
scale and bias per axis out of the coefficients.
"""
import struct, sys


def load(path):
    out, blob, i = [], open(path, "rb").read(), 0
    while i + 9 <= len(blob):
        t, ln = struct.unpack_from("dB", blob, i); i += 9
        out.append((t, blob[i:i+ln])); i += ln
    return out


def solve(m, rhs):
    n = len(m)
    a = [row[:] + [rhs[i]] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise SystemExit("singular system -- not enough distinct orientations")
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col] / a[col][col]
            for c in range(col, n + 1):
                a[r][c] -= f * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


samples = []
for path in sys.argv[1:]:
    for _, p in load(path):
        if len(p) < 32 or p[0] != 4:
            continue
        gp = struct.unpack_from("<h", p, 26)[0]
        gr = struct.unpack_from("<h", p, 29)[0]
        if abs(gp) > 8 or abs(gr) > 8:      # only samples at rest
            continue
        samples.append(struct.unpack_from("<3h", p, 11))
print("%d resting samples from %d captures" % (len(samples), len(sys.argv) - 1))

# Normal equations for the six coefficients.
mat = [[0.0] * 6 for _ in range(6)]
rhs = [0.0] * 6
for x, y, z in samples:
    row = [x * x, x, y * y, y, z * z, z]
    for i in range(6):
        rhs[i] += row[i]
        for j in range(6):
            mat[i][j] += row[i] * row[j]
coef = solve(mat, rhs)

print("\nper-axis fit:")
scales, biases = [], []
const = 1.0
for i, name in enumerate("XYZ"):
    q, l = coef[2 * i], coef[2 * i + 1]
    bias = -l / (2 * q)
    const += q * bias * bias
    scales.append(q)
    biases.append(bias)
for i, name in enumerate("XYZ"):
    lsb_per_g = (const / scales[i]) ** 0.5
    print("  %s: bias %+7.1f LSB   scale %7.1f LSB per g" % (name, biases[i], lsb_per_g))

print("\nresidual check (|a| after correction, should sit at 1.00):")
import statistics
mags = []
for x, y, z in samples[::37]:
    v = []
    for i, raw in enumerate((x, y, z)):
        v.append((raw - biases[i]) / ((const / scales[i]) ** 0.5))
    mags.append((v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5)
print("  mean %.4f  stdev %.4f  min %.4f  max %.4f  (n=%d)"
      % (statistics.mean(mags), statistics.pstdev(mags), min(mags), max(mags), len(mags)))
