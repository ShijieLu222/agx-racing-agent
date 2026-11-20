"""Fit cubic B-spline offsets to public circuit geometry (offline only).

Print the control points for parkland_line.py. The convex quadratic fit reduces
linearized path curvature with a lateral slope and offset penalty. Bounds on
each control point apply over its entire spline support. No replay inputs.
"""
from pathlib import Path
import sys
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from track_data import TRACKS, geometry_at

STEP = 10
SECTIONS = {
    "parkland": [(2190,2450),(2570,2840),(2920,3160),(4000,4410)],
    "crossover": [(470,1090),(1140,1650),(2020,2340),(2650,2800)],
}


def fit(start, end, track="parkland"):
    length = TRACKS[track]["length"]
    max_offset = 2.9 if track == "parkland" else 2.4
    count = (end - start) // STEP + 1
    normal = [[0.0] * count for _ in range(count)]
    rhs = [0.0] * count
    lower = [0.0] * count
    upper = [0.0] * count
    for s in range(start, end + 1, 2):
        i, remainder = divmod(s - start, STEP)
        t = remainder / STEP
        w = [(1-t)**3/6, (3*t**3-6*t*t+4)/6,
             (-3*t**3+3*t*t+3*t+1)/6, t**3/6]
        dw = [-.5*(1-t)**2, 1.5*t*t-2*t, -1.5*t*t+t+.5, .5*t*t]
        ddw = [1-t, 3*t-2, 1-3*t, t]
        k, _, _, _ = geometry_at(length, s)
        indices = [(j, i+j-1) for j in range(4) if 2 <= i+j-1 < count-2]
        # For a parallel curve, k_path = k/(1-k*n); n'' adds the
        # leading curvature correction for a varying lateral offset.
        curvature = [ddw[j]/STEP**2 + k*k*w[j] for j in range(4)]
        for j, a in indices:
            rhs[a] -= curvature[j]*k
            for h, b in indices:
                normal[a][b] += (curvature[j]*curvature[h]
                                 + .025**2 * dw[j]*dw[h]/STEP**2
                                 + .00055**2 * w[j]*w[h])
    for i in range(2,count-2):
        widths = [geometry_at(length, start+i*STEP+ds)[2:] for ds in range(-20,21,2)]
        lower[i] = -min(max_offset, min(w[1] for w in widths)-3.0)
        upper[i] = min(max_offset, min(w[0] for w in widths)-3.0)
    points = [0.0]*count
    for _ in range(2000):
        movement = 0.0
        for i in range(2,count-2):
            residual = rhs[i] - sum(normal[i][j]*points[j]
                                    for j in range(max(0,i-3),min(count,i+4)) if j != i)
            new = max(lower[i], min(upper[i], residual / normal[i][i]))
            movement = max(movement, abs(points[i]-new))
            points[i] = new
        if movement < .0001:
            break
    return tuple(round(x, 4) for x in points)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("track", choices=SECTIONS, default="parkland", nargs="?")
    track = parser.parse_args().track
    for start, end in SECTIONS[track]:
        print(start, fit(start, end, track))
