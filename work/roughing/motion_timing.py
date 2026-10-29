"""Independent acceleration estimate for the linear moves emitted by CAM Local.

This is a kinematic estimate, not a controller or a hardware interface.  Path
speeds and acceleration are projected through the configured XYZ limits.  A
junction-deviation corner bound and a rolling finite look-ahead window provide
continuous entry/exit speeds; every committed block has an exact triangular or
trapezoidal speed profile.  The implementation is original Python using the
standard constant-acceleration equations (no firmware source is incorporated).

The model resembles GRBL's junction-deviation planner, but does not reproduce
its ISR, segment preparation, buffer refill timing, or step pulses.  The rolling
window assumes rest just beyond its currently visible blocks and replenishes
one block after each commitment.  This can be conservative on many tiny blocks.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import math


NC_COORD_DECIMALS = 5
RAPID_KINDS = frozenset(('travel', 'retract', 'clearance_adjust',
                         'approach_rapid', 'rapid', 'G0', 'g0'))
_PROFILE_FIELDS = ('entry_speed_mm_s', 'exit_speed_mm_s', 'peak_speed_mm_s',
                   'acceleration_mm_s2', 'length_mm', 'accel_distance_mm',
                   'cruise_distance_mm', 'decel_distance_mm', 'accel_time_s',
                   'cruise_time_s', 'decel_time_s', 'duration_s')


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f'{name} must be a finite number')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f'{name} must be a finite number') from error
    if not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')
    if nonnegative and value < 0:
        raise ValueError(f'{name} must be nonnegative')
    return value


def _xyz(values, name, *, positive=False):
    if isinstance(values, (str, bytes)):
        raise ValueError(f'{name} must contain three numbers')
    if isinstance(values, Mapping):
        try:
            values = [values[axis] if axis in values else values[axis.lower()]
                      for axis in 'XYZ']
        except KeyError as error:
            raise ValueError(f'{name} must contain X, Y and Z') from error
    try:
        values = tuple(values)
    except TypeError as error:
        raise ValueError(f'{name} must contain three numbers') from error
    if len(values) != 3:
        raise ValueError(f'{name} must contain three numbers')
    return tuple(_number(value, f'{name}.{axis}', positive=positive)
                 for axis, value in zip('XYZ', values))


def _step_position(point, steps_per_mm, name):
    """Match NC formatting, then C lround's half-away-from-zero step target."""
    point = _xyz(point, name)
    steps = []
    for coordinate, scale in zip(point, steps_per_mm):
        nc_coordinate = float(f'{coordinate:.{NC_COORD_DECIMALS}f}')
        scaled = _number(nc_coordinate * scale, f'{name} step position')
        steps.append(math.floor(scaled + .5) if scaled >= 0 else
                     -math.floor(-scaled + .5))
    return tuple(steps)


def _project(limits, direction):
    return min(limit / abs(component)
               for limit, component in zip(limits, direction) if component)


def _sum(values, name):
    try:
        result = math.fsum(values)
    except OverflowError as error:
        raise ValueError(f'{name} exceeds the finite numeric range') from error
    return _number(result, name, nonnegative=True)


@dataclass(slots=True)
class _Block:
    source: int
    length: float
    direction: tuple
    speed: float
    acceleration: float
    reach_sq: float
    junction_sq: float = 0.


def _junction_sq(previous, current, accelerations, deviation):
    cap_sq = min(previous.speed, current.speed) ** 2
    cosine = max(-1., min(1., sum(a * b for a, b in
                                 zip(previous.direction, current.direction))))
    # The limits avoid cancellation at exactly straight/reversed junctions.
    if cosine >= 1. - 1e-12:
        return cap_sq
    if cosine <= -1. + 1e-12 or deviation == 0:
        return 0.
    change = tuple(b - a for a, b in zip(previous.direction, current.direction))
    magnitude = math.hypot(*change)
    normal = tuple(value / magnitude for value in change)
    corner_acceleration = _project(accelerations, normal)
    half_cosine = math.sqrt((1. + cosine) * .5)
    bound = corner_acceleration * deviation * half_cosine / (1. - half_cosine)
    return min(cap_sq, _number(bound, 'junction speed squared', nonnegative=True))


def _profile(block, entry_sq, exit_sq):
    length, acceleration, speed = block.length, block.acceleration, block.speed
    entry = math.sqrt(max(0., entry_sq))
    exit_speed = math.sqrt(max(0., exit_sq))
    # Equating acceleration and deceleration distances gives the triangular
    # peak; clipping it to the nominal speed adds a constant-speed section.
    peak_sq = min(speed * speed,
                  acceleration * length + .5 * entry_sq + .5 * exit_sq)
    peak_sq = max(entry_sq, exit_sq, peak_sq)
    peak = math.sqrt(peak_sq)
    accel_distance = max(0., (peak_sq - entry_sq) / (2. * acceleration))
    decel_distance = max(0., (peak_sq - exit_sq) / (2. * acceleration))
    cruise_distance = max(0., length - accel_distance - decel_distance)
    accel_time = max(0., (peak - entry) / acceleration)
    decel_time = max(0., (peak - exit_speed) / acceleration)
    cruise_time = cruise_distance / peak
    duration = _number(accel_time + cruise_time + decel_time,
                       'move duration', nonnegative=True)
    return dict(zip(_PROFILE_FIELDS, (entry, exit_speed, peak, acceleration,
                length, accel_distance, cruise_distance, decel_distance,
                accel_time, cruise_time, decel_time, duration)))


def estimate_acceleration(moves, *, max_rates_mm_min,
                          accelerations_mm_s2, junction_deviation_mm=.01,
                          steps_per_mm=(400, 400, 400), planner_blocks=15):
    """Return JSON-serializable timing and one playback profile per input move.

    XYZ limits can be triples or dictionaries with X/Y/Z keys.  ``moves`` must
    be a continuous iterable of mappings containing ``start``, ``end``,
    ``kind``, and (for non-rapid moves) positive ``feed_mm_min``.  G0 uses the
    machine's projected maximum rates, independently of its display feed.
    G1 feed is rounded to the same five decimal places as exported NC.

    All calculations use mm/s and mm/s².  The first and final physical blocks
    start/end at rest.  Zero-step NC movements retain their source index with
    a zero-duration profile and do not consume a look-ahead block.  Positions
    assume work zero is aligned to step phase zero on each axis.

    ``planner_blocks`` is the number of usable physical blocks; the default 15
    corresponds to the usable slots in a 16-slot GRBL ring buffer.

    The rolling planner performs a reverse braking pass and a forward reachable
    speed pass on at most ``planner_blocks`` upcoming physical blocks, commits
    the first block, and advances the window.  Cost is O(moves * planner_blocks)
    with O(moves) storage.  There is no motor, sender, or hardware connection.
    """
    rates = _xyz(max_rates_mm_min, 'max_rates_mm_min', positive=True)
    accelerations = _xyz(accelerations_mm_s2, 'accelerations_mm_s2', positive=True)
    steps = _xyz(steps_per_mm, 'steps_per_mm', positive=True)
    deviation = _number(junction_deviation_mm, 'junction_deviation_mm', nonnegative=True)
    if (isinstance(planner_blocks, bool) or not isinstance(planner_blocks, int)
            or not 1 <= planner_blocks <= 128):
        raise ValueError('planner_blocks must be an integer from 1 to 128')
    rates_s = tuple(value / 60. for value in rates)
    if any(value == 0 for value in rates_s):
        raise ValueError('max_rates_mm_min is too small')
    try:
        iterator = iter(moves)
    except TypeError as error:
        raise ValueError('moves must be an iterable of movement mappings') from error

    blocks, profiles, operations, kinds = [], [], [], []
    previous_end = None
    ideal_parts = []
    for source, move in enumerate(iterator):
        if not isinstance(move, Mapping):
            raise ValueError(f'moves[{source}] must be a mapping')
        try:
            start = _step_position(move['start'], steps, f'moves[{source}].start')
            end = _step_position(move['end'], steps, f'moves[{source}].end')
        except KeyError as error:
            raise ValueError(f'moves[{source}] requires start and end') from error
        if previous_end is not None and start != previous_end:
            raise ValueError(f'moves[{source}] is discontinuous after step quantization')
        previous_end = end
        kind = move.get('kind', 'cut')
        if not isinstance(kind, str):
            raise ValueError(f'moves[{source}].kind must be text')
        operation = move.get('operation', '')
        if not isinstance(operation, str):
            raise ValueError(f'moves[{source}].operation must be text')
        rapid = kind in RAPID_KINDS
        feed = None
        if not rapid:
            feed = _number(move.get('feed_mm_min'), f'moves[{source}].feed_mm_min',
                           positive=True)
            feed = float(f'{feed:.{NC_COORD_DECIMALS}f}') / 60.
            if feed == 0:
                raise ValueError(f'moves[{source}].feed_mm_min loses NC precision')
        start_mm = [value / scale for value, scale in zip(start, steps)]
        end_mm = [value / scale for value, scale in zip(end, steps)]
        try:
            delta = tuple((b - a) / scale for a, b, scale in zip(start, end, steps))
        except OverflowError as error:
            raise ValueError('Step-quantized displacement exceeds the finite numeric range') from error
        length = _number(math.hypot(*delta), 'step-quantized move length', nonnegative=True)
        profile = {key: 0. for key in _PROFILE_FIELDS}
        profile.update(source_index=source, start=start_mm, end=end_mm,
                       nominal_speed_mm_s=0., ideal_duration_s=0.)
        profiles.append(profile)
        operations.append(operation)
        kinds.append(kind)
        if length == 0:
            continue
        direction = tuple(value / length for value in delta)
        speed = _number(_project(rates_s, direction), 'projected speed', positive=True)
        if feed is not None:
            speed = min(speed, feed)
        acceleration = _number(_project(accelerations, direction),
                               'projected acceleration', positive=True)
        _number(speed * speed, 'nominal speed squared', positive=True)
        reach_sq = _number(2. * acceleration * length,
                           'reachable speed squared', positive=True)
        block = _Block(source, length, direction, speed, acceleration, reach_sq)
        if blocks:
            block.junction_sq = _junction_sq(blocks[-1], block, accelerations, deviation)
        blocks.append(block)
        profile['nominal_speed_mm_s'] = speed
        profile['ideal_duration_s'] = _number(length / speed, 'ideal move duration', positive=True)
        ideal_parts.append(profile['ideal_duration_s'])

    entry_sq = 0.
    for first, block in enumerate(blocks):
        end = min(len(blocks), first + planner_blocks)
        count = end - first
        planned = [0.] * (count + 1)  # terminal rest at this window's horizon
        # Reverse: every entry must be able to brake to the following entry.
        for offset in range(count - 1, -1, -1):
            upcoming = blocks[first + offset]
            planned[offset] = min(upcoming.junction_sq,
                                  planned[offset + 1] + upcoming.reach_sq)
        # The previous committed block fixed this entry.  A newly appended
        # horizon block cannot invalidate the earlier, more restrictive plan.
        planned[0] = entry_sq
        # Forward: entry speeds must also be reachable by accelerating from
        # the fixed current entry, and cannot exceed the previous block's rate.
        for offset in range(1, count):
            previous = blocks[first + offset - 1]
            planned[offset] = min(planned[offset], previous.speed ** 2,
                                  planned[offset - 1] + previous.reach_sq)
        exit_sq = planned[1]
        profiles[block.source].update(_profile(block, entry_sq, exit_sq))
        entry_sq = exit_sq

    # A no-step block leaves physical velocity unchanged, including when it
    # changes operation or modal feed in the source program.
    carried_speed = 0.
    for profile in profiles:
        if profile['length_mm']:
            carried_speed = profile['exit_speed_mm_s']
        else:
            profile['entry_speed_mm_s'] = carried_speed
            profile['exit_speed_mm_s'] = carried_speed
            profile['peak_speed_mm_s'] = carried_speed
    by_operation, by_kind = {}, {}
    for profile, operation, kind in zip(profiles, operations, kinds):
        duration = profile['duration_s']
        by_operation[operation] = by_operation.get(operation, 0.) + duration
        by_kind[kind] = by_kind.get(kind, 0.) + duration
    duration = _sum((profile['duration_s'] for profile in profiles), 'total duration')
    ideal = _sum(ideal_parts, 'total ideal duration')
    return {
        'available': True,
        'model': 'acceleration_junction_deviation_finite_lookahead',
        'duration_s': duration,
        'ideal_duration_s': ideal,
        'profiles': profiles,
        'by_operation_s': by_operation,
        'by_kind_s': by_kind,
        'physical_blocks': len(blocks),
        'zero_step_moves': len(profiles) - len(blocks),
        'settings': {'max_rates_mm_min': list(rates),
                     'accelerations_mm_s2': list(accelerations),
                     'junction_deviation_mm': deviation,
                     'steps_per_mm': list(steps), 'planner_blocks': planner_blocks},
        'approximation': True,
        'scope': 'Linear G0/G1 kinematic estimate with rolling finite block look-ahead',
        'assumptions': [
            'Starts and ends at rest; continuous ideal buffer replenishment',
            'NC coordinates rounded to 5 decimals, then absolute axis step targets',
            'Known work zero aligned with step phase zero on every axis',
            'Look-ahead horizon assumes rest; one block committed per refill',
            'Junction deviation limits speed; source geometry remains unblended'],
        'excludes': ['streaming starvation', 'spindle spin-up and dwell',
                     'operator pauses', 'firmware segment timing',
                     'step pulse scheduling', 'mechanical and cutting-load effects',
                     'startup positioning before the first calculated move'],
    }
