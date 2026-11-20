"""Bounded reference lines derived from public circuit maps (ODbL, see NOTICE)."""
import math

from track_data import TRACKS, geometry_at

LENGTH = TRACKS["parkland"]["length"]
# Uniform cubic B-spline controls, metres left of centre, spaced every 10 m.
# Reproduce with scripts/fit_parkland_line.py. End offsets and slopes are zero.
CONTROLS = {
    2190: (
        0.0, 0.0, -0.1987, -0.5029, -0.8988, -1.352, -1.8275, -2.2815,
        -2.6597, -2.9, -2.9, -2.6239, -0.3265, 2.9, 1.7088, -0.0156,
        -1.2745, -2.9, -1.0657, 2.0649, 2.9, 2.9, 2.363, 1.5423,
        0.6951, 0.0, 0.0,
    ),
    2570: (
        0.0, 0.0, 0.3502, 0.8321, 1.3675, 1.838, 2.1374, 2.182,
        1.9363, 1.4314, 0.764, 0.074, -0.5009, -0.8847, -1.0927, -1.2088,
        -1.3191, -1.4641, -1.626, -1.739, -1.7212, -1.5214, -1.161, -0.7304,
        -0.3461, -0.0941, 0.0, 0.0,
    ),
    2920: (
        0.0, 0.0, 0.2935, 0.7165, 1.2312, 1.7711, 2.2751, 2.6771,
        2.9, 2.9, 2.4808, 1.377, -0.5467, -2.4936, -2.6144, -0.6624,
        1.4106, 2.5681, 2.9, 2.6626, 2.0654, 1.3008, 0.5661, 0.0,
        0.0,
    ),
    4000: (
        0.0, 0.0, -0.2931, -0.7167, -1.2337, -1.7785, -2.2876, -2.6932,
        -2.9, -2.8746, -2.2744, -0.8419, 1.5017, 2.9, 1.3791, -0.7585,
        -2.1456, -2.7651, -2.9, -2.9, -2.9, -2.9, -2.9, -2.9,
        -2.9, -2.9, -2.9, -2.8215, -2.4185, -1.5139, 0.035, 2.0424,
        2.9, 1.69, 0.1089, -0.8701, -1.246, -1.1754, -0.8296, -0.3901,
        0.0, 0.0,
    ),
}

CROSSOVER_CONTROLS = {
    470: (
        0.0, 0.0, -0.356, -0.7959, -1.2131, -1.4786, -1.4981, -1.2141,
        -0.6374, 0.1436, 0.9815, 1.7108, 2.2044, 2.4, 2.4, 2.1771,
        1.7198, 1.2504, 1.1378, 1.4299, 1.8107, 2.031, 2.031, 1.8614,
        1.6214, 1.4366, 1.417, 1.595, 1.9024, 2.2123, 2.4, 2.4,
        2.1944, 1.7507, 1.128, 0.4044, -0.3387, -1.0296, -1.6039, -2.0002,
        -2.1636, -2.0535, -1.6627, -1.0231, -0.212, 0.6523, 1.4224, 1.9599,
        2.1617, 2.0812, 1.6976, 1.0295, 0.1972, -0.6591, -1.395, -1.8813,
        -2.0344, -1.8983, -1.5067, -0.975, -0.4399, 0.0, 0.0,
    ),
    1140: (
        0.0, 0.0, 0.3282, 0.7958, 1.312, 1.7655, 2.0977, 2.2993,
        2.3957, 2.4, 2.3601, 2.1562, 1.7515, 1.159, 0.4403, -0.3277,
        -1.0688, -1.7027, -2.141, -2.3122, -2.2235, -1.9416, -1.5902, -1.2944,
        -1.1454, -1.1877, -1.4074, -1.7341, -2.0585, -2.2614, -2.2578, -2.0064,
        -1.5515, -0.9894, -0.4214, 0.0907, 0.5396, 0.9568, 1.3709, 1.776,
        2.1214, 2.3402, 2.3894, 2.2798, 2.0518, 1.7579, 1.4312, 1.0782,
        0.6965, 0.3199, 0.0, 0.0,
    ),
    2020: (
        0.0, 0.0, 0.3855, 0.9134, 1.5029, 2.03, 2.376, 2.4,
        1.9824, 0.8631, -1.1285, -2.4, -0.6323, 1.1929, 2.0982, 2.4,
        2.4, 2.4, 2.3824, 2.3766, 2.3838, 2.4, 2.4, 2.4,
        2.0086, 0.1548, -2.2224, -2.4, -0.8112, 0.6705, 0.6648, 0.0,
        0.0,
    ),
    2650: (
        0.0, 0.0, -0.385, -0.9642, -1.6177, -2.1857, -2.4, -2.4,
        -1.9742, -2.4, -2.4, -2.3041, -1.2816, -0.3611, 0.0, 0.0,
    ),
}


# Each sample holds offset, tangent heading relative to the road, signed
# curvature correction, path metres per road metre, and original road curvature.
def build_samples(length, controls):
    samples = {}
    for start, points in controls.items():
        # Zero padding also gives a flat join at the physical endpoints.
        padded = (0.0,) + points + (0.0, 0.0)
        for ds in range((len(points)-1)*10 + 1):
            index, remainder = divmod(ds, 10)
            t = remainder / 10
            p, q, r, u = padded[index:index+4]
            n = ((1-t)**3*p + (3*t**3-6*t*t+4)*q
                 + (-3*t**3+3*t*t+3*t+1)*r + t**3*u) / 6
            slope = (-(1-t)**2*p + (3*t*t-4*t)*q
                     + (-3*t*t+2*t+1)*r + t*t*u) / 20
            second = ((1-t)*p + (3*t-2)*q + (1-3*t)*r + t*u) / 100
            s = start + ds
            k = geometry_at(length, s)[0]
            dk = geometry_at(length, s+.5)[0] - geometry_at(length, s-.5)[0]
            a = 1-k*n
            metric = math.hypot(a, slope)
            curve = (a*(second + a*k) + slope*(dk*n + 2*k*slope)) / metric**3
            samples[s] = (n, math.atan2(slope, a), curve-k, metric, k)
    return samples


CROSSOVER_LENGTH = TRACKS["crossover"]["length"]
CROSSOVER_SAMPLES = build_samples(CROSSOVER_LENGTH, CROSSOVER_CONTROLS)
SAMPLES = build_samples(LENGTH, CONTROLS)


def available_samples(length, station):
    if abs(length - LENGTH) < 2 and (1800 <= station <= 3160 or 3600 <= station <= 4410):
        return SAMPLES
    if abs(length - CROSSOVER_LENGTH) < 2 and 180 <= station <= 2800:
        return CROSSOVER_SAMPLES
    return None


def reference(station, samples=SAMPLES):
    index = int(station)
    left = samples.get(index)
    if left is None:
        return None
    right = samples.get(index+1, left)
    t = station-index
    return tuple(a+t*(b-a) for a,b in zip(left,right))


def planning_window(planning, station, tracked, samples=SAMPLES):
    """Transform live and public road knots into path arc distance and curvature."""
    result = []
    distance = previous = 0.0
    current = reference(station, samples)
    last_scale = current[3] if current else 1.0
    for row in planning:
        ds, curve, grade = row[:3]
        ref = reference(station+ds, samples)
        scale = 1.0
        if ref is not None:
            _, _, change, scale, road_curve = ref
            path_curve = curve + change
            # An unexpected live restriction or large tracking error can add
            # constraints, but cannot disappear behind a mapped correction.
            if (tracked and abs(curve-road_curve) < .001) or abs(path_curve) > abs(curve):
                curve = path_curve
        distance += (ds-previous)*min(1.0, scale, last_scale)
        result.append((distance, curve, grade))
        previous, last_scale = ds, scale
    return result
