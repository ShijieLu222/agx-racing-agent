"""AGX Formula Racing v7: tyre-aware grip, combined braking and spin recovery.

Contract: rsi-racing-4.4. Public geometry and legal observations only.
Control/grip constants below are conservative engineering hypotheses, not the
private engine model or a claim of measured race performance. See docs/rules.md.
"""
import math
from bisect import bisect_right

try:
    from track_data import TRACKS, geometry_at, pit_distance, aero_remaining
except ImportError:
    TRACKS = {}
    def geometry_at(length, station):
        return None
    def pit_distance(length, station):
        return None
    def aero_remaining(length, station):
        return None


COLUMNS = ("distance_m", "curvature_1pm", "grade", "half_width_left_m",
           "half_width_right_m", "aero_zone")
COMPOUNDS = ("soft", "medium", "hard")
# A tyre coefficient is a model estimate, not a speed/acceleration ceiling.
# Downforce changes the available lateral force with speed. These coefficients
# still need validation in a new race; public replays do not expose tyre physics.
BASE_TYRE_MU = 1.75
LATERAL_RESERVE = 0.92
# Relative planning hypotheses. Use the published circuit allocation: a medium
# C2 at Crossover is not the same specification as a medium C4 at Parkland.
SPEC_GRIP = {"C1": 0.90, "C2": 0.94, "C3": 0.97, "C4": 1.0, "C5": 1.02}
DRY_LATERAL_ACCEL = BASE_TYRE_MU * 9.81
DRY_SPEED_CAP = None  # Optional cap for the diagnostic script; disabled in races.


def clip(value, low, high):
    return max(low, min(high, value))


def number(value, default=0.0):
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return default


def maximum(values, default=0.0):
    return max((number(v, default) for v in (values or [])), default=default)


def tyre_mu(observation):
    """Shared planning hypothesis, not a measurement of the private tyre model."""
    car = observation["self"]
    wet = clip(number((observation.get("weather") or {}).get("track_wetness")), 0, 1)
    wear = clip(maximum(car.get("tyre_wear")), 0, 1)
    hot = max(0.0, maximum(car.get("tyre_temp_c"), 85) - 118)
    temps = [number(t, 80) for t in (car.get("tyre_temp_c") or [80])]
    cold_factor = max(0.80, 1 - 0.004 * max(0.0, 80 - min(temps)))
    allocation = (observation.get("tyres") or {}).get("allocation") or {}
    compound = car.get("compound")
    spec = allocation.get(compound)
    compound_factor = SPEC_GRIP.get(spec, {"soft": 1.0, "medium": .96, "hard": .92}.get(compound, .92))
    return (BASE_TYRE_MU * (1 - 0.30 * wet) * max(0.65, 1 - 0.30 * wear)
            * max(0.75, 1 - hot * 0.008) * cold_factor * compound_factor)


def longitudinal_grip(observation, geometry):
    """Remaining tyre force after observed lateral load; not aero drag.

    Do not substitute preview/current-road curvature here: an approaching bend
    is not lateral force already being generated, especially on unknown maps.
    The route planner separately budgets the future combined demand.
    """
    car = observation["self"]
    mass = max(300.0, number(car.get("effective_mass_kg"), 1000))
    speed = max(0.0, number(car.get("speed_mps")))
    grip = tyre_mu(observation) * (mass * 9.81 + max(0.0, number(car.get("downforce_n"))))
    lateral = mass * max(abs(number(car.get("g_lat"))) * 9.81,
                         speed * abs(number(car.get("yaw_rate"))))
    return math.sqrt(max(0.0, grip * grip - lateral * lateral))


def stability_state(car, geometry):
    """Instantaneous risk; flags alone cannot latch a slow driving mode."""
    speed = max(0.0, number(car.get("speed_mps")))
    vx, vy = number(car.get("vx"), speed), number(car.get("vy"))
    heading = number(car.get("heading_error"))
    beta = math.atan2(vy, max(6.0, vx))
    along = (vx * math.cos(heading) - vy * math.sin(heading)) / max(.3, 1 - number(car.get("n")) * geometry[0])
    yaw_error = number(car.get("yaw_rate")) - along * geometry[0]
    # Detect growing oversteer earlier than the old 0.30 rad heading threshold,
    # while allowing ordinary curvature tracking and small steady sideslip.
    risk = max((abs(beta) - .035) / .14, (abs(heading) - .08) / .28,
               (abs(yaw_error) - .22) / .6 * clip((abs(beta) - .015) / .04, 0, 1))
    return clip(risk, 0, 1) * clip((speed - 5) / 10, 0, 1), beta, yaw_error


def preview_rows(observation):
    """Canonical rows, without relying on transport column order."""
    preview = observation.get("preview") or {}
    names = preview.get("columns") or COLUMNS
    indices = {name: i for i, name in enumerate(names)}
    if any(name not in indices for name in COLUMNS[:5]):
        return []
    result = []
    for row in preview.get("rows") or []:
        if not isinstance(row, (list, tuple)):
            continue
        if any(indices[name] >= len(row) for name in COLUMNS[:5]):
            continue
        values = [number(row[indices[name]]) for name in COLUMNS[:5]]
        zone_index = indices.get("aero_zone", len(row))
        values.append(number(row[zone_index]) if zone_index < len(row) else 0.0)
        if values[0] >= 0 and min(values[3:5]) > 0:
            result.append(values)
    return sorted(result, key=lambda r: r[0])


def neutral():
    return {"throttle": 0.0, "brake": 0.0, "steer": 0.0,
            "ers_mode": 1, "aero_mode": 0, "aid": False,
            "override": False, "pit_request": False, "pit_compound": None}


class Driver:
    def __init__(self):
        self.phase = None
        self.last_time = None
        self.last_steer = 0.0
        self.last_distance = None
        self.last_pit_state = 0
        self.last_stops = 0
        self.last_compound = None
        self.used_compounds = set()
        self.wet_waiver = False
        self.pending_pit = None
        self.lane = 0.0
        self.pass_lane = 0.0
        self.pass_seat = None
        self.last_target = None
        self.last_control_target = None
        self.free_target = math.inf
        self.braking = False
        self.boosting = False
        self.in_straight = False
        self.downforce_per_v2 = 0.0
        self.available_braking = DRY_LATERAL_ACCEL
        self.fuel_sample = None
        self.fuel_per_m = None
        self.fuel_power_scale = 1.0
        self.previous_preview = None
        self.planning_knots = None

    def public_window(self, length, station, horizon):
        """All original map knots ahead; a moving probe grid can skip peaks."""
        if not TRACKS or length <= 0:
            return None
        public = min(TRACKS.values(), key=lambda t: abs(t['length'] - length))
        if abs(public['length'] - length) >= 2:
            return None
        cache = self.planning_knots
        if cache is None or cache[0] is not public['rows'] or cache[1] != length:
            knots = [r for r in public['rows'] if r[0] < length]
            if length > public['length']:
                knots.extend((r[0] + public['length'], *r[1:])
                             for r in public['rows']
                             if r[0] + public['length'] < length)
            knots.append((length - 1e-7, *geometry_at(length, length - 1e-7)))
            knots.sort(key=lambda r: r[0])
            cache = (public['rows'], length, tuple(knots), tuple(r[0] for r in knots))
            self.planning_knots = cache
        knots, stations = cache[2:]
        position = station % length
        index = bisect_right(stations, position)
        offset = -position
        if index == len(knots):
            index, offset = 0, offset + length
        result = [[0.0, *geometry_at(length, station), 0.0]]
        while knots[index][0] + offset < horizon:
            row = knots[index]
            result.append([row[0] + offset, *row[1:], 0.0])
            index += 1
            if index == len(knots):
                index, offset = 0, offset + length
        result.append([horizon, *geometry_at(length, station + horizon), 0.0])
        return result

    def current_geometry(self, observation, rows):
        car = observation["self"]
        length = number(observation.get("track_length_m"))
        station = number(car.get("s"))
        public = geometry_at(length, station)
        if public is not None:
            return tuple(number(v) for v in public)
        # Align OLD preview to the current travelled distance when it covers us.
        # The first CURRENT preview row is 15 m ahead, never current geometry.
        distance = number(car.get("distance"), station)
        cached = self.previous_preview
        if cached:
            old_distance, old_rows = cached
            advance = distance - old_distance
            for left, right in zip(old_rows, old_rows[1:]):
                if left[0] <= advance <= right[0] and right[0] > left[0]:
                    t = (advance - left[0]) / (right[0] - left[0])
                    return tuple(left[j] + t * (right[j] - left[j])
                                 for j in (1, 2, 3, 4))
        if rows:
            # Conservative explicit extrapolation for unknown tracks/startup.
            first = rows[0]
            curve = first[1]
            if len(rows) > 1 and rows[1][0] > first[0]:
                curve -= first[0] * (rows[1][1] - curve) / (rows[1][0] - first[0])
                bound = max(abs(first[1]), abs(rows[1][1]), 0.001) * 2
                curve = clip(curve, -bound, bound)
            return curve, first[2], first[3], first[4]
        return 0.0, 0.0, 4.0, 4.0

    def speed_plan(self, observation, rows, geometry, dt):
        car = observation["self"]
        # No flag-driven grip ratchet, 0.88*speed target, or slow target recovery.
        # Slip flags alone do not measure loss of control. Heading, sideslip,
        # road clearance and visible collision threats are handled explicitly.
        mu = tyre_mu(observation)
        speed = max(0.0, number(car.get("speed_mps")))
        mass = max(300.0, number(car.get("effective_mass_kg"), 1000))
        downforce = max(0.0, number(car.get("downforce_n")))
        # F_down ~ coefficient*v^2. Extrapolate only from moving telemetry; the
        # initial zero-downforce sample must not erase grip for a whole phase.
        if speed > 8.0 and downforce > 0:
            self.downforce_per_v2 = downforce / (speed * speed)
        aero_coefficient = self.downforce_per_v2
        # Available ground-level braking, bounded only by measured brake force.
        braking = min(mu * 9.81,
                      max(1.0, number(car.get("brake_force_max_n"), mass * 12)) / mass)
        self.available_braking = braking
        weakest_grade = min([geometry[1]] + [row[2] for row in rows])
        horizon_braking = max(0.1, braking + 9.81 * weakest_grade)
        horizon = max(360.0, speed * speed / (2 * horizon_braking) + speed * dt + 3)
        length = number(observation.get("track_length_m"))
        if length > 0:
            horizon = min(horizon, length)
        drag = max(0.0, number(car.get("drag_n")))
        drag += max(0.0, number(car.get("rolling_resistance_n")))
        available_drive = maximum(car.get("drive_force_n"))
        # A finite reachable target for a clear road, NOT a terminal speed cap.
        # It grows with current speed and lets the engine/drag determine top speed.
        free_accel = max(1.0, (available_drive - drag) / mass)
        free_target = math.sqrt(speed * speed + 2 * free_accel * horizon)
        if DRY_SPEED_CAP is not None:
            free_target = min(free_target, DRY_SPEED_CAP)
        self.free_target = free_target
        def corner_speed(kappa):
            # Solve v^2*kappa <= mu*(g + F_down(v)/mass).
            lateral_mu = mu * LATERAL_RESERVE
            denominator = abs(kappa) - lateral_mu * aero_coefficient / mass
            if denominator <= 0:
                return free_target
            return min(free_target, math.sqrt(lateral_mu * 9.81 / denominator))
        def segment_braking(v2, kappa):
            capacity = mu * (9.81 + aero_coefficient * v2 / mass)
            lateral = v2 * abs(kappa)
            return min(braking, math.sqrt(max(0.0, capacity * capacity - lateral * lateral)))
        curve, grade, width_left, width_right = geometry
        target = corner_speed(curve)
        planning = [row for row in rows if row[0] <= horizon]
        # Preserve the live v4's full ~2 m maps, checking every original knot.
        station = number(car.get("s"))
        public = self.public_window(length, station, horizon)
        if public is not None:
            planning.extend(public)
        else:
            for distance in range(2, int(horizon) + 1, 2):
                sample = geometry_at(length, station + distance)
                if sample is None:
                    break
                planning.append([distance, *sample, 0.0])
        planning.sort(key=lambda r: r[0])
        if not planning:
            target = min(target, 12.0)
        else:
            # Propagate between adjacent knots, using the weaker endpoint grade.
            # Shift restrictions by one callback plus 3 m of reaction distance.
            envelope = free_target
            reaction = 3.0 + dt * speed
            next_distance = max(0.0, planning[-1][0] - reaction)
            next_grade = planning[-1][2]
            next_curve = planning[-1][1]
            for row in reversed(planning):
                distance, kappa, slope = row[:3]
                distance = max(0.0, distance - reaction)
                corner = corner_speed(kappa)
                gap = max(0.0, next_distance - distance)
                grade_accel = 9.81 * min(slope, next_grade)
                trial_v2 = min(corner * corner, max(0.0, envelope * envelope + 2 * (braking + grade_accel) * gap))
                decel = segment_braking(trial_v2, max(abs(kappa), abs(next_curve))) + grade_accel
                envelope = min(corner, math.sqrt(max(0.0, envelope * envelope
                                  + 2 * decel * gap)))
                next_distance, next_grade, next_curve = distance, slope, kappa
            trial_v2 = min(target * target, max(0.0, envelope * envelope + 2 * braking * next_distance))
            decel = segment_braking(trial_v2, max(abs(curve), abs(next_curve))) + 9.81 * min(grade, next_grade)
            target = min(target, math.sqrt(max(0.0, envelope * envelope
                                              + 2 * decel * next_distance)))
        self.last_target = max(3.0, target)
        target = self.last_target
        margin = min(width_left - number(car.get("n")),
                     width_right + number(car.get("n")))
        if margin < 1.5:
            target = min(target, 11.0 + 5.0 * max(0.0, margin))
        # Pose recovery is a force constraint in act(), not a discontinuous
        # 18/8 m/s target whose derivative can request a full-brake impulse.
        return max(3.0, target)

    def traffic_plan(self, observation, rows, target, dt):
        car = observation["self"]
        speed = max(0.0, number(car.get("speed_mps")))
        n = number(car.get("n"))
        nearby = [r for r in observation.get("rivals", [])
                  if r.get("status") == "racing"]
        near_rows = [r for r in rows if r[0] <= 100]
        straight = bool(near_rows) and max(abs(r[1]) for r in near_rows) < 0.0025
        width_left = min((r[3] for r in near_rows), default=4.0)
        width_right = min((r[4] for r in near_rows), default=4.0)
        low, high = -width_right + 1.8, width_left - 1.8
        leaders = [r for r in nearby if 0 < number(r.get("gap_m")) < 65
                   and abs(number(r.get("dn"))) < 2.7]
        front = min(leaders, key=lambda r: r["gap_m"]) if leaders else None
        tracked = next((r for r in nearby if r.get("seat") == self.pass_seat), None)
        alongside = any(abs(number(r.get("gap_m"))) < 12 for r in nearby)
        if self.pass_seat is not None:
            passed = tracked is None or number(tracked.get("gap_m")) < -15
            if (passed or not straight) and not alongside:
                self.pass_seat, self.pass_lane = None, 0.0
        slow_clearance = bool(front and speed < 6
                              and number(front.get("speed_mps")) < 3
                              and number(front.get("gap_m")) >= 8)
        if (self.pass_seat is None and front and straight
                and (number(front.get("gap_m")) > 12 or slow_clearance)):
            front_n = n + number(front.get("dn"))
            candidates = sorted((-3.0, 3.0), key=lambda x: -abs(x - front_n))
            for lane in candidates:
                if not low <= lane <= high or abs(lane - front_n) < 2.7:
                    continue
                clear = all(not (-18 < number(r.get("gap_m")) < 50
                                and abs(n + number(r.get("dn")) - lane) < 2.6)
                            for r in nearby)
                if clear:
                    self.pass_seat, self.pass_lane = front.get("seat"), lane
                    break
        requested = clip(self.pass_lane, min(low, 0.0), max(high, 0.0))
        self.lane += clip(requested - self.lane, -0.85 * dt, 0.85 * dt)
        # Collision constraint remains active while changing lanes. It is based
        # on current lateral clearance, not the hoped-for future passing lane.
        emergency = False
        for rival in leaders:
            gap = number(rival.get("gap_m"))
            front_speed = max(0.0, number(rival.get("speed_mps")))
            # As the cars separate laterally, release the longitudinal following
            # constraint smoothly rather than braking right until a hard lane
            # threshold. This allows a committed pass to continue beside a car.
            lateral_overlap = math.sqrt(max(0.0, 1 - (abs(number(rival.get("dn"))) / 2.7) ** 2))
            closing = max(0.0, speed - front_speed)
            stopping_gap = closing * closing / (2 * max(1.0, getattr(self, "available_braking", 7.0)))
            desired_gap = (6.0 + speed * dt + stopping_gap) * lateral_overlap
            following = max(0.0, front_speed + (gap - desired_gap) / 1.3)
            target = min(target, following)
            closing = speed - front_speed
            if gap < max(2.5, 6.0 * lateral_overlap) or (
                    closing > 1 and gap / closing < 0.7 and lateral_overlap > 0.65):
                emergency = True
                target = min(target, max(0.0, front_speed - 5.0))
        return target, self.lane, emergency, straight

    def pit_plan(self, observation):
        car = observation["self"]
        phase = observation.get("phase")
        pit_state = int(number(car.get("pit_state")))
        stops = int(number(car.get("pit_stops")))
        distance = number(car.get("distance"), number(car.get("s")))
        compound = car.get("compound")
        wet = number((observation.get("weather") or {}).get("track_wetness"))
        if phase != "race":
            return False, None
        self.wet_waiver = self.wet_waiver or wet >= 0.5
        # Only actual forward on-track use counts, not fitting a tyre in the box.
        if (pit_state == 0 and self.last_pit_state == 0
                and self.last_distance is not None and distance > self.last_distance
                and compound == self.last_compound and compound in COMPOUNDS):
            self.used_compounds.add(compound)
        just_exited = stops > self.last_stops
        if pit_state or just_exited:
            self.pending_pit = None
        self.last_distance, self.last_pit_state = distance, pit_state
        self.last_stops, self.last_compound = stops, compound
        if pit_state or just_exited:
            return False, None
        if self.pending_pit:
            return True, self.pending_pit
        length = number(observation.get("track_length_m"))
        completed = int(number(car.get("lap")))
        remaining = number(observation.get("laps_total"), 4) - completed
        progress = clip(number(car.get("s")) / max(1.0, length), 0.0, 1.0)
        needed = len(self.used_compounds) < 2 and not self.wet_waiver
        entry = pit_distance(length, number(car.get("s")))
        window = (completed >= 1 and entry is not None and entry < 650)
        if entry is None:
            window = completed >= 2
        # A final-lap request is still preferable to a dry-tyre disqualification.
        mandatory = needed and (window or remaining <= 1)
        wear = maximum(car.get("tyre_wear"))
        hot = maximum(car.get("tyre_temp_c"), 85)
        extra = remaining - progress > 0.8 and (wear > 0.78 or hot > 139)
        if mandatory or extra:
            unused = [c for c in ("medium", "hard", "soft")
                      if c != compound and c not in self.used_compounds]
            next_compound = unused[0] if needed and unused else (
                "hard" if compound == "medium" else "medium")
            self.pending_pit = next_compound
            return True, next_compound
        return False, None

    def fuel_saving(self, observation):
        car = observation["self"]
        distance = number(car.get("distance"))
        fuel = number(car.get("fuel_kg"), 60)
        if self.fuel_sample is None:
            self.fuel_sample = distance, fuel
        else:
            old_distance, old_fuel = self.fuel_sample
            if distance - old_distance > 150 and old_fuel >= fuel:
                rate = (old_fuel - fuel) / (distance - old_distance)
                self.fuel_per_m = rate if self.fuel_per_m is None else (
                    0.8 * self.fuel_per_m + 0.2 * rate)
                self.fuel_sample = distance, fuel
        length = number(observation.get("track_length_m"))
        remaining = max(0.0, (number(observation.get("laps_total"), 4)
                       - number(car.get("lap"))) * length - number(car.get("s")))
        projected = remaining * (self.fuel_per_m or 0.0)
        self.fuel_power_scale = min(1.0, fuel / projected) if projected > 0 else 1.0
        return self.fuel_power_scale < 1.0

    def energy_mode(self, observation, geometry, force, braking_rate, eligible):
        """Choose deployment from useful demand and a conservative friction circle.

        This selects an ERS mode only: it never caps the throttle or stores a
        lower speed target. No fixed SOC reserve or recovery timer is added.
        Public replay evidence showed v5 spending attack mostly in tight bends
        and reaching the subsequent straights empty. Actual savings need a race.
        """
        if self.braking:
            return 0
        if not eligible:
            return 1
        car = observation["self"]
        drives = car.get("drive_force_n") or []
        if len(drives) < 4:
            return 1  # No evidence that an extra mode supplies useful force.
        neutral_force = max(0.0, number(drives[1]))
        balanced_force = max(neutral_force, number(drives[2]))
        mass = max(300.0, number(car.get("effective_mass_kg"), 1000))
        speed = max(0.0, number(car.get("speed_mps")))
        normal = mass * 9.81 + max(0.0, number(car.get("downforce_n")))
        grip = tyre_mu(observation) * normal
        lateral = mass * max(speed * speed * abs(geometry[0]),
                             abs(number(car.get("g_lat"))) * 9.81)
        longitudinal = math.sqrt(max(0.0, grip * grip - lateral * lateral))
        useful_force = min(max(0.0, force), longitudinal)
        # Request no extra energy when neutral already meets the wheel-force
        # demand, or when an approaching braking envelope is falling.
        if useful_force <= neutral_force * 1.02 or braking_rate < -0.5:
            return 1
        if (useful_force > balanced_force * 1.02
                and lateral < grip * 0.65
                and number(drives[3]) > balanced_force * 1.02):
            return 3
        # Balanced is useful only if it really adds force over neutral. Under
        # lateral load this avoids spending attack while keeping full throttle.
        return 2 if balanced_force > neutral_force * 1.02 else 1

    def act(self, observation):
        car = observation.get("self") or {}
        phase = observation.get("phase")
        if self.phase != phase:
            self.__init__()
            self.phase = phase
        if not car or car.get("status", "racing") != "racing":
            return neutral()
        now = number(observation.get("time"))
        dt = clip(now - self.last_time, 1 / 60, 0.15) if self.last_time is not None else 1 / 30
        self.last_time = now
        rows = preview_rows(observation)
        geometry = self.current_geometry(observation, rows)
        # Retain an older window until it no longer includes the car's station.
        travelled = number(car.get("distance"), number(car.get("s")))
        if self.previous_preview is None or travelled - self.previous_preview[0] > 100:
            self.previous_preview = travelled, rows
        pit, compound = self.pit_plan(observation)
        if car.get("pit_state"):
            self.last_steer = 0.0
            self.braking, self.boosting = False, False
            return neutral()
        target = self.speed_plan(observation, rows, geometry, dt)
        target, lane, emergency, straight = self.traffic_plan(observation, rows, target, dt)
        saving = self.fuel_saving(observation)
        speed = max(0.0, number(car.get("speed_mps")))
        kappa, grade, _, _ = geometry
        heading = number(car.get("heading_error"))
        stability, sideslip, yaw_error = stability_state(car, geometry)
        desired_heading = -math.atan2(0.9 * (number(car.get("n")) - lane), speed + 7)
        # Yaw response per radian of steer grows with speed. A fixed large
        # derivative gain can alternate wheel commands at the 30 Hz boundary.
        yaw_gain = 0.06 / (1.0 + speed / 25.0)
        angle = (math.atan(3.4 * kappa) + 0.66 * (desired_heading - heading)
                 - 0.18 * sideslip - yaw_gain * yaw_error)
        if sideslip * yaw_error < 0 and abs(sideslip) > .035:
            # During oversteer, align the front wheels with their local travel
            # direction and damp excess yaw, instead of demanding more path force.
            front_flow = math.atan2(number(car.get("vy")) + 1.7 * number(car.get("yaw_rate")),
                                    max(6.0, number(car.get("vx"), speed)))
            recovery_angle = front_flow - 2 * yaw_gain * yaw_error
            angle += stability * (recovery_angle - angle)
        # Respect the published mechanical slew, using measured wheel angle.
        actual = number(car.get("steer"), self.last_steer * 0.3)
        desired = clip(angle, -0.3, 0.3)
        steer = clip(desired, actual - 1.6 * dt, actual + 1.6 * dt) / 0.3
        steer = clip(steer, -1.0, 1.0)
        self.last_steer = steer
        error = target - speed
        # Follow a falling braking envelope immediately. A proportional-only
        # controller reacts late when the envelope itself is falling quickly.
        target_rate = ((target - self.last_control_target) / dt
                       if self.last_control_target is not None else 0.0)
        self.last_control_target = target
        # A changing engine-force estimate is not an approaching road hazard.
        # Only follow target deceleration when a route/pose/traffic constraint
        # is binding, rather than the freely reachable reference on a straight.
        braking_rate = min(0.0, target_rate) if target < self.free_target - 1e-6 else 0.0
        accel = error * 1.7 + braking_rate
        mass = max(300.0, number(car.get("effective_mass_kg"), 1000))
        drag = max(0.0, number(car.get("drag_n"))) + max(0.0, number(car.get("rolling_resistance_n")))
        force = mass * (accel + 9.81 * grade) + drag
        grip_force = longitudinal_grip(observation, geometry)
        if stability > 0:
            # Mild state-proportional recovery braking, limited below by the
            # remaining friction circle. No timer or persistent reduced target.
            recovery_force = mass * .30 * tyre_mu(observation) * 9.81 * stability
            force = min(force, -recovery_force)
        wet = number((observation.get("weather") or {}).get("track_wetness"))
        soc = number(car.get("ers_soc_mj"))
        # Amplitude hysteresis, never a minimum holding time: a newly required
        # slowdown or emergency enters braking immediately on this callback.
        if emergency or error < -0.5 or force < -mass * 0.15:
            self.braking = True
        elif error >= -0.15 and force >= 0:
            self.braking = False
        self.in_straight = straight
        power_safe = (abs(heading) < 0.2
                      and abs(sideslip) < 0.25 and stability == 0 and not emergency)
        # Corner exits remain eligible immediately; choose the power tier using
        # wheel-force demand and the lateral load, rather than error alone.
        boost_error = 0.5 if self.boosting else 1.5
        eligible = bool(error > boost_error and soc > 0.0 and power_safe
                        and not self.braking)
        mode = self.energy_mode(observation, geometry, force, braking_rate, eligible)
        self.boosting = mode in (2, 3)
        boost = self.boosting
        drives = car.get("drive_force_n") or []
        drive = number(drives[mode]) if len(drives) > mode else 0.0
        brake_capacity = max(1.0, number(car.get("brake_force_max_n"), mass * 12))
        if self.braking:
            throttle = 0.0
            brake = clip(max(-force, mass * max(0.0, -error * 1.7)) / brake_capacity, 0, 1)
        else:
            brake = 0.0
            throttle = clip(force / drive, 0, 1) if drive > 100 else float(force > 0)
        # Braking and propulsion share the same remaining tyre-force budget.
        # An overspeeding car already using all lateral grip must coast while
        # unwinding, rather than demand another full longitudinal tyre force.
        brake = min(brake, grip_force / brake_capacity)
        if drive > 100:
            throttle = min(throttle, grip_force / drive)
        if emergency:
            throttle, brake, mode = 0.0, max(brake, 0.75), 0
        if saving:
            throttle *= self.fuel_power_scale
        aid = bool(observation.get("phase") == "race" and power_safe
                   and boost and brake < 0.05 and wet < 0.5
                   and not (car.get("front_sliding") or car.get("rear_sliding"))
                   and (car.get("aid_available") or car.get("override_available")))
        remaining = aero_remaining(number(observation.get("track_length_m")), number(car.get("s")))
        aero = int(remaining is not None and remaining > 45 and straight
                   and brake < 0.05 and power_safe and speed > 20)
        return {"throttle": float(throttle), "brake": float(brake), "steer": float(steer),
                "ers_mode": mode, "aero_mode": aero, "aid": aid, "override": False,
                "pit_request": bool(pit), "pit_compound": compound}


_driver = Driver()


def init(context):
    global _driver
    _driver = Driver()


def act(observation):
    return _driver.act(observation)
