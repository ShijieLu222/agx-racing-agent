"""AGX Formula Racing v2: separate route planning from brief traction events.

Contract: rsi-racing-4.4. Public geometry and legal observations only.
Control/grip constants below are conservative engineering hypotheses, not the
private engine model or a claim of measured race performance. See docs/rules.md.
"""
import math

try:
    from track_data import geometry_at, pit_distance, aero_remaining
except ImportError:
    def geometry_at(length, station):
        return None
    def pit_distance(length, station):
        return None
    def aero_remaining(length, station):
        return None


COLUMNS = ("distance_m", "curvature_1pm", "grade", "half_width_left_m",
           "half_width_right_m", "aero_zone")
COMPOUNDS = ("soft", "medium", "hard")
DRY_LATERAL_ACCEL = 11.0
DRY_SPEED_CAP = 58.0


def clip(value, low, high):
    return max(low, min(high, value))


def number(value, default=0.0):
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return default


def maximum(values, default=0.0):
    return max((number(v, default) for v in (values or [])), default=default)


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
        self.grip_scale = 1.0
        self.slip_exposure = 0.0
        self.last_target = None
        self.braking = False
        self.boosting = False
        self.power_clear_time = 0.20
        self.in_straight = False
        self.energy_reserve = 1.1
        self.fuel_sample = None
        self.fuel_per_m = None
        self.previous_preview = None

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
        wet = clip(number((observation.get("weather") or {}).get("track_wetness")), 0, 1)
        wear = clip(maximum(car.get("tyre_wear")), 0, 1)
        hot = max(0.0, maximum(car.get("tyre_temp_c"), 85) - 118)
        sliding = bool(car.get("front_sliding") or car.get("rear_sliding"))
        # A one-callback lockup must not permanently reduce the route plan.
        # Accumulate sustained/high-duty slip, while isolated pulses decay in
        # two clear callbacks. Alternating slip/clear still accumulates risk.
        self.slip_exposure = clip(self.slip_exposure
                                  + (1.0 if sliding else -0.5) * dt, 0.0, 0.6)
        persistent_slip = self.slip_exposure >= 0.20
        grip_loss = persistent_slip and sliding
        self.grip_scale = clip(self.grip_scale + (-0.23 if grip_loss else 0.018) * dt,
                               0.68, 1.0)
        grip = (1 - 0.55 * wet) * max(0.66, 1 - 0.35 * wear)
        grip *= max(0.76, 1 - hot * 0.008) * self.grip_scale
        lateral = DRY_LATERAL_ACCEL * grip
        braking = 7.2 * grip
        speed = max(0.0, number(car.get("speed_mps")))
        cap = DRY_SPEED_CAP - 15.0 * wet
        curve, grade, width_left, width_right = geometry
        target = min(cap, math.sqrt(lateral / max(abs(curve), 0.00001)))
        planning = list(rows)
        # Preview samples are 15 m apart. The public ~6 m geometry can reveal
        # a narrow bend between them, so also check the near braking horizon.
        length = number(observation.get("track_length_m"))
        station = number(car.get("s"))
        for distance in range(6, 181, 6):
            sample = geometry_at(length, station + distance)
            if sample is None:
                break
            planning.append([distance, *sample, 0.0])
        planning.sort(key=lambda r: r[0])
        if not planning:
            target = min(target, 12.0)
        else:
            # Backward braking envelope across every preview sample. Variable
            # slope reduces available deceleration downhill. Safety distance
            # covers a control reaction and the finite 15 m preview sampling.
            envelope = cap
            next_distance = planning[-1][0]
            for row in reversed(planning):
                distance, kappa, slope = row[:3]
                corner = min(cap, math.sqrt(lateral / max(abs(kappa), 0.00001)))
                decel = clip(braking + 9.81 * slope, 2.2, 11.0)
                envelope = min(corner, math.sqrt(envelope * envelope
                                  + 2 * decel * max(0.0, next_distance - distance)))
                approach_distance = max(0.0, distance - 4.0 - 0.22 * speed)
                target = min(target, math.sqrt(envelope * envelope
                                              + 2 * decel * approach_distance))
                next_distance = distance
        if number(car.get("pu_temp_c"), 90) > 125:
            target = min(target, 32.0)
        # Persist only the route/weather/vehicle plan. A temporary traction or
        # position intervention below must never become the next plan's ceiling:
        # v1 fed 0.88 * actual speed back here and ratcheted wet pace downward.
        # Route slowdowns remain immediate; planned acceleration stays bounded.
        if self.last_target is not None:
            target = min(target, self.last_target + 4.0 * dt)
        self.last_target = max(3.0, target)
        target = self.last_target
        margin = min(width_left - number(car.get("n")),
                     width_right + number(car.get("n")))
        heading = abs(number(car.get("heading_error")))
        sideslip = abs(math.atan2(number(car.get("vy")),
                                 max(6.0, number(car.get("vx"), speed))))
        if margin < 1.5:
            target = min(target, 11.0 + 5.0 * max(0.0, margin))
        elif heading > 0.30:
            target = min(target, 18.0)
        if heading > 0.65 or sideslip > 0.25:
            target = min(target, 8.0)
        if persistent_slip:
            target = min(target, max(7.0, speed * 0.88))
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
            desired_gap = (7.0 + 0.45 * speed) * lateral_overlap
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
        return fuel < 4 or (self.fuel_per_m is not None and
                           fuel < remaining * self.fuel_per_m * 1.12 + 1.0)

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
            self.power_clear_time = 0.0
            return neutral()
        target = self.speed_plan(observation, rows, geometry, dt)
        target, lane, emergency, straight = self.traffic_plan(observation, rows, target, dt)
        saving = self.fuel_saving(observation)
        if saving:
            target = min(target, 38.0)
        speed = max(0.0, number(car.get("speed_mps")))
        kappa, grade, _, _ = geometry
        heading = number(car.get("heading_error"))
        sideslip = math.atan2(number(car.get("vy")), max(6.0, number(car.get("vx"), speed)))
        desired_heading = -math.atan2(0.9 * (number(car.get("n")) - lane), speed + 7)
        yaw_error = number(car.get("yaw_rate")) - speed * kappa
        # Yaw response per radian of steer grows with speed. A fixed large
        # derivative gain can alternate wheel commands at the 30 Hz boundary.
        yaw_gain = 0.06 / (1.0 + speed / 25.0)
        angle = (math.atan(3.4 * kappa) + 0.66 * (desired_heading - heading)
                 - 0.18 * sideslip - yaw_gain * yaw_error)
        # Respect the published mechanical slew, using measured wheel angle.
        actual = number(car.get("steer"), self.last_steer * 0.3)
        desired = clip(angle, -0.3, 0.3)
        steer = clip(desired, actual - 1.6 * dt, actual + 1.6 * dt) / 0.3
        steer = clip(steer, -1.0, 1.0)
        self.last_steer = steer
        error = target - speed
        wet = number((observation.get("weather") or {}).get("track_wetness"))
        slipping = bool(car.get("front_sliding") or car.get("rear_sliding"))
        soc = number(car.get("ers_soc_mj"))
        # Amplitude hysteresis, never a minimum holding time: a newly required
        # slowdown or emergency enters braking immediately on this callback.
        if emergency or error < -0.5:
            self.braking = True
        elif error >= -0.15:
            self.braking = False
        if straight and not self.in_straight:
            self.energy_reserve = max(0.8, soc * 0.38)
        self.in_straight = straight
        power_safe = (not slipping and abs(heading) < 0.2
                      and abs(sideslip) < 0.25 and not emergency)
        # Unsafe traction closes boost immediately. Only its re-enabling waits
        # for a short clear interval; braking and neutral drive never wait.
        self.power_clear_time = (min(0.20, self.power_clear_time + dt)
                                 if power_safe else 0.0)
        boost_error = 0.5 if self.boosting else 1.5
        boost_reserve = self.energy_reserve + (0.0 if self.boosting else 0.12)
        self.boosting = bool(straight and error > boost_error
                             and soc > boost_reserve and power_safe
                             and self.power_clear_time >= 0.20
                             and not self.braking)
        boost = self.boosting
        mode = 2 if boost else 1
        if self.braking or soc < 0.6:
            mode = 0
        mass = max(300.0, number(car.get("effective_mass_kg"), 1000))
        drag = max(0.0, number(car.get("drag_n"))) + max(0.0, number(car.get("rolling_resistance_n")))
        accel = clip(error * 1.7, -10.0, 4.8)
        force = mass * (accel + 9.81 * grade) + drag
        drives = car.get("drive_force_n") or []
        drive = number(drives[mode]) if len(drives) > mode else 0.0
        brake_capacity = max(1.0, number(car.get("brake_force_max_n"), mass * 12))
        if self.braking:
            throttle = 0.0
            brake = clip(max(-force, mass * min(10.0, -error * 1.7)) / brake_capacity, 0, 1)
        else:
            brake = 0.0
            throttle = clip(force / drive, 0, 1) if drive > 100 else clip(0.15 + error * 0.25, 0, 1)
        if emergency:
            throttle, brake, mode = 0.0, max(brake, 0.75), 0
        if abs(heading) > 0.65 or abs(sideslip) > 0.25 or slipping:
            throttle = min(throttle, 0.28)
        if saving or number(car.get("pu_temp_c"), 90) > 125:
            throttle = min(throttle, 0.65)
        aid = bool(observation.get("phase") == "race" and power_safe
                   and boost and brake < 0.05 and wet < 0.5
                   and (car.get("aid_available") or car.get("override_available")))
        remaining = aero_remaining(number(observation.get("track_length_m")), number(car.get("s")))
        aero = int(remaining is not None and remaining > 60 and straight
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
