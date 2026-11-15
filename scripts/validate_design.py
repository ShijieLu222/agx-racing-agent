"""Local check of published rsi-racing-4.4 design constraints, not admission."""
import json
import math
from pathlib import Path

FIELDS = {
    'aero.front_wing': (10, 30, .5), 'aero.rear_wing': (10, 32, .5),
    'ride_height_mm.front': (25, 55, 1), 'ride_height_mm.rear': (50, 100, 1),
    'suspension.spring_front_n_per_mm': (120, 420, 5),
    'suspension.spring_rear_n_per_mm': (100, 380, 5),
    'suspension.arb_front': (1, 10, 1), 'suspension.arb_rear': (1, 10, 1),
    'suspension.camber_front_deg': (-3.25, -1, .05),
    'suspension.camber_rear_deg': (-2, -.5, .05),
    'suspension.toe_front_deg': (-.3, .1, .01),
    'suspension.toe_rear_deg': (0, .6, .01),
    'mass.ballast_kg': (20, 60, .5), 'mass.weight_front_pct': (44, 46, .1),
    'gearbox.final_drive': (4.4, 6.6, .01),
    'brakes.bias_front_pct': (50, 64, .1), 'brakes.duct': (.2, 1, .05),
    'cooling.radiator_opening': (.25, 1, .05),
    'power_unit.fuel_load_kg': (5, 100, .5),
    'power_unit.ers_harvest_level': (0, 5, 1),
    'tyres.pressure_front_psi': (24, 32, .1),
    'tyres.pressure_rear_psi': (24, 32, .1),
}
ENUMS = {'schema': ('formula-v4-design-1',),
         'suspension.damping': ('soft', 'medium', 'stiff'),
         'tyres.start_compound': ('soft', 'medium', 'hard')}
INTEGERS = {'suspension.arb_front', 'suspension.arb_rear',
            'power_unit.ers_harvest_level'}
RATIO_MIN = (3.4, 2.45, 1.95, 1.6, 1.35, 1.15, 1, .86)
RATIO_MAX = (4.8, 3.5, 2.7, 2.2, 1.85, 1.55, 1.3, 1.12)
# Effective pressure floors from the three official public mapdata files.
TRACK_LIMITS = {'parkland': (26, 26, -3, -2),
                'highland': (28, 28, -2.75, -1.5),
                'crossover': (28, 26, -2.75, -1.5)}


def strict_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON value: ' + value)
    return json.loads(Path(path).read_text(), object_pairs_hook=unique,
                      parse_constant=invalid)


def flatten(row, prefix=''):
    if not isinstance(row, dict):
        raise ValueError('Design sections must be objects')
    out = {}
    for key, value in row.items():
        path = prefix + key
        if isinstance(value, dict):
            if not value:
                raise ValueError('Empty design section: ' + path)
            out.update(flatten(value, path + '.'))
        else:
            out[path] = value
    return out


def number(value, low, high, step, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number, not bool')
    if not low - 1e-9 <= value <= high + 1e-9:
        raise ValueError(name + ' outside published bounds')
    if abs((value - low) / step - round((value - low) / step)) > 1e-7:
        raise ValueError(name + ' is not on the published step grid')


def validate_book(book):
    if len(json.dumps(book, ensure_ascii=False).encode()) > 4096:
        raise ValueError('Design book exceeds 4096 bytes')
    values = flatten(book)
    expected = set(FIELDS) | set(ENUMS) | {'gearbox.ratios'}
    if set(values) != expected:
        raise ValueError('Missing/unknown design fields: ' + str(set(values) ^ expected))
    for key, bounds in FIELDS.items():
        number(values[key], *bounds, key)
        if key in INTEGERS and type(values[key]) is not int:
            raise ValueError(key + ' must be an integer')
    for key, choices in ENUMS.items():
        if values[key] not in choices:
            raise ValueError('Invalid enum: ' + key)
    ratios = values['gearbox.ratios']
    if not isinstance(ratios, list) or len(ratios) != 8:
        raise ValueError('Exactly eight gear ratios are required')
    for i, value in enumerate(ratios):
        number(value, RATIO_MIN[i], RATIO_MAX[i], .001, 'gearbox.ratios')
    if any(not 1.08 - 1e-9 <= a / b <= 1.45 + 1e-9
           for a, b in zip(ratios, ratios[1:])):
        raise ValueError('Adjacent gear ratio constraint')
    if ratios[0] * values['gearbox.final_drive'] > 25.1 + 1e-9:
        raise ValueError('First gear total ratio constraint')
    ballast, front = values['mass.ballast_kg'], values['mass.weight_front_pct']
    mass = 748 + ballast
    if (mass < 768 or mass * front / 100 < 768 * .44 - 1e-9
            or mass * (100 - front) / 100 < 768 * .54 - 1e-9
            or ballast < 20 + 8.2 * abs(front - 45) - 1e-9):
        raise ValueError('Mass/axle/ballast cross-field constraint')
    if not 0 <= values['ride_height_mm.rear'] - values['ride_height_mm.front'] <= 70:
        raise ValueError('Ride height difference constraint')
    for track, (pf, pr, cf, cr) in TRACK_LIMITS.items():
        if (values['tyres.pressure_front_psi'] < pf
                or values['tyres.pressure_rear_psi'] < pr
                or values['suspension.camber_front_deg'] < cf
                or values['suspension.camber_rear_deg'] < cr):
            raise ValueError('Event pressure/camber constraint: ' + track)


def validate(envelope):
    if not isinstance(envelope, dict) or 'design' not in envelope:
        raise ValueError('Top-level design is required')
    if set(envelope) - {'design', 'rain_design'}:
        raise ValueError('Unknown top-level design field')
    for book in envelope.values():
        validate_book(book)
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default='design.json')
    args = parser.parse_args()
    validate(strict_json(args.path))
    print('Published field, grid, cross-field and all-three-track checks passed.')
