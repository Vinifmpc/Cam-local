"""Read-only modal G0/G1 audit for the supplied MeshCAM reference programs.

This is an analysis tool, not a machine interpreter or a postprocessor.
Missing G90/G94 are explicit assumptions. Unknown initial coordinates stay null.
Unsupported coordinate-changing G codes reject the input rather than inventing
geometry. Source comments are data and are never executed.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from pathlib import Path
import re

WORD = re.compile(r'([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))', re.I)
# This audit deliberately implements only the linear subset it can replay.
# Like GRBL, reject conflicting modes and repeated value words per block.
G_GROUPS = {0:'motion',1:'motion',17:'plane',20:'units',21:'units',
            90:'distance',91:'distance',94:'feed',40:'compensation',
            49:'tool_length',54:'work_offset'}
M_GROUPS = {0:'flow',1:'flow',2:'flow',30:'flow',3:'spindle',4:'spindle',
            5:'spindle',7:'coolant',8:'coolant',9:'coolant'}


@dataclass
class Move:
    line: int
    mode: int
    start: list
    end: list
    feed: float | None
    spindle: float | None
    length: float | None
    xy_length: float | None


def audit(path, diameter=3.175):
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig', errors='replace')
    position = [None, None, None]
    absolute, unit_scale, mode = True, None, None
    feed, spindle = None, None
    moves, events, errors, comments = [], [], [], []
    seen_g = Counter()
    explicit_z = Counter()
    distance_mode_explicit = False
    feed_mode_explicit = False
    distance_mode_assumed = False
    feed_mode_assumed = False
    for number, original in enumerate(text.splitlines(), 1):
        comments.extend({'line':number,'text':item}
                        for item in re.findall(r'\(([^)]*)\)', original))
        code = re.sub(r'\([^)]*\)', '', original).split(';',1)[0].strip().upper()
        if not code or code == '%':
            continue
        tokens = [(letter.upper(), float(value)) for letter,value in WORD.findall(code)]
        residual = WORD.sub('', code).strip()
        if residual:
            errors.append({'line':number,'unparsed':residual})
        seen_words,groups=set(),set()
        for letter,value in tokens:
            if not math.isfinite(value):
                raise ValueError(f'{path.name}:{number}: non-finite {letter}')
            if letter in ('G','M'):
                table=G_GROUPS if letter=='G' else M_GROUPS
                if value not in table:
                    raise ValueError(f'{path.name}:{number}: unsupported {letter}{value:g}')
                group=(letter,table[value])
                if group in groups:
                    raise ValueError(f'{path.name}:{number}: conflicting {letter} modal group')
                groups.add(group)
            else:
                if letter not in 'XYZFSNT':
                    raise ValueError(f'{path.name}:{number}: unsupported word {letter}')
                if letter in seen_words:
                    raise ValueError(f'{path.name}:{number}: repeated word {letter}')
                seen_words.add(letter)
                if letter in 'FSNT' and value<0:
                    raise ValueError(f'{path.name}:{number}: negative {letter}')
                if letter in 'NT' and not value.is_integer():
                    raise ValueError(f'{path.name}:{number}: non-integer {letter}')
        values = {letter:value for letter,value in tokens if letter not in 'GMN'}
        for letter,value in tokens:
            if letter == 'G':
                seen_g[f'G{value:g}'] += 1
                if value in (0,1): mode = int(value)
                elif value in (20,21): unit_scale = 25.4 if value == 20 else 1.0
                elif value in (90,91):
                    absolute = value == 90
                    distance_mode_explicit = True
                elif value == 94: feed_mode_explicit = True
                elif value not in (17,40,49,54):
                    raise ValueError(f'{path.name}:{number}: unsupported G{value:g}')
            elif letter == 'M':
                events.append({'line':number,'code':f'M{value:g}'})
        if 'S' in values: spindle = values['S']
        if 'F' in values:
            if unit_scale is None: raise ValueError('Feed before units')
            feed = values['F'] * unit_scale
        axes = [axis for axis in 'XYZ' if axis in values]
        if not axes: continue
        if unit_scale is None: raise ValueError('Motion before units')
        if mode is None: raise ValueError('Motion before G0/G1')
        distance_mode_assumed |= not distance_mode_explicit
        feed_mode_assumed |= mode==1 and not feed_mode_explicit
        if mode==1 and feed is not None and feed<=0:
            raise ValueError(f'{path.name}:{number}: G1 requires a positive feed')
        start = position.copy()
        for index,axis in enumerate('XYZ'):
            if axis not in values: continue
            value = values[axis] * unit_scale
            position[index] = value if absolute else (
                position[index] + value if position[index] is not None else None)
        if 'Z' in axes and position[2] is not None:
            explicit_z[round(position[2],6)] += 1
        end = position.copy()
        complete = all(value is not None for value in start+end)
        xy_complete = all(value is not None for value in start[:2]+end[:2])
        length = math.dist(start,end) if complete else None
        xy_length = math.dist(start[:2],end[:2]) if xy_complete else None
        moves.append(Move(number, mode, start, end, feed, spindle, length, xy_length))
    if errors: raise ValueError(errors)

    bounds = {}
    for index,axis in enumerate('XYZ'):
        vals = [point[index] for move in moves for point in (move.start,move.end)
                if point[index] is not None]
        bounds[axis] = [min(vals),max(vals)] if vals else None
    plateaus, horizontal_ys = defaultdict(lambda:{'segments':0,'length_mm':0.0}), defaultdict(set)
    active, runs = [], []
    for move in moves:
        if move.mode == 0:
            if active: runs.append(active); active=[]
        else:
            active.append(move)
        if (move.mode != 1 or move.length is None or not move.xy_length or
                move.start[2] != move.end[2] or move.end[2] >= 0):
            continue
        z = round(move.end[2],6)
        plateaus[z]['segments'] += 1
        plateaus[z]['length_mm'] += move.length
        if abs(move.end[1]-move.start[1]) < 1e-8 and abs(move.end[0]-move.start[0]) > diameter:
            horizontal_ys[z].add(round(move.end[1],6))
    if active: runs.append(active)

    run_summary=[]
    for run in runs:
        points=[move.end for move in run]
        known_z=[point[2] for point in points if point[2] is not None]
        xy_bounds=[]
        for axis in range(2):
            known=[point[axis] for point in points if point[axis] is not None]
            xy_bounds.append([min(known),max(known)] if known else None)
        run_summary.append({'first_line':run[0].line,'last_line':run[-1].line,
            'moves':len(run),'start':run[0].start,'end':run[-1].end,
            'z_min':min(known_z) if known_z else None,
            'xy_bounds':xy_bounds,
            'length_mm':sum(move.length or 0 for move in run)})
    feed_moves=[move for move in moves if move.mode==1]
    assumptions=[]
    if distance_mode_assumed or not distance_mode_explicit:
        assumptions.append('G90 absolute coordinates assumed before an explicit distance mode')
    if feed_mode_assumed or not feed_mode_explicit:
        assumptions.append('G94 units/min feed assumed before an explicit feed mode')
    summary={'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),
        'bytes':len(raw),'lines':len(text.splitlines()),'g_codes':dict(seen_g),
        'assumptions':assumptions,'bounds_mm':bounds,
        'motion_counts':dict(Counter(f'G{move.mode}' for move in moves)),
        'unknown_start_moves':sum(move.length is None for move in moves),
        'feedrates_mm_min':sorted({move.feed for move in feed_moves if move.feed is not None}),
        'spindle_commands':sorted({move.spindle for move in moves if move.spindle is not None}),
        'known_feed_length_mm':sum(move.length or 0 for move in feed_moves),
        'known_rapid_length_mm':sum(move.length or 0 for move in moves if move.mode==0),
        'ideal_feed_minutes':sum(move.length/move.feed for move in feed_moves
                                  if move.length is not None and move.feed and move.feed>0),
        'time_exclusions':['rapid time','acceleration/deceleration','operator pause M0','controller behavior'],
        'missing_feed_moves':sum(move.feed is None for move in feed_moves),
        'explicit_z_values':dict(sorted(explicit_z.items())),
        'flat_feed_levels':[{'z':z,**row} for z,row in sorted(plateaus.items(),reverse=True)],
        'raster_rows':[{'z':z,'y_values':sorted(ys),
                        'y_spacings':[round(b-a,6) for a,b in zip(sorted(ys),sorted(ys)[1:])]}
                       for z,ys in sorted(horizontal_ys.items(),reverse=True)],
        'feed_runs':run_summary,'events':events,'comments':comments,
        'limitations':['G0/G1 geometry only','centerline bounds, not swept tool volume',
                       'initial machine position and work offset unknown',
                       'Z0 is treated as nominal top for classification; stock model not supplied']}
    return summary, moves


def segment_signature(move):
    return (move.mode,tuple(move.start),tuple(move.end),move.feed)


def compare(reference, edited):
    base = Counter(segment_signature(move) for move in reference if move.mode==1)
    new = Counter(segment_signature(move) for move in edited if move.mode==1)
    return {'comparison':'directed G1 segment multisets including start/end and modal feed',
            'reference_segments':sum(base.values()),'edited_segments':sum(new.values()),
            'identical_multiset':base==new,'reference_only_count':sum((base-new).values()),
            'edited_only_count':sum((new-base).values()),
            'reference_only_examples':list((base-new).items())[:5],
            'edited_only_examples':list((new-base).items())[:5],
            'scope':'Does not establish equivalence of rapid travel, startup, machining order or stock support'}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Inspect NC files without executing machine commands.')
    parser.add_argument('files',type=Path,nargs='+')
    parser.add_argument('--compare',action='store_true',help='Compare two supplied files')
    parser.add_argument('--report',type=Path,help='Optional JSON destination')
    args=parser.parse_args()
    if args.compare and len(args.files)!=2:parser.error('--compare requires exactly two files')
    rows=[audit(path) for path in args.files]
    result={'summaries':[row[0] for row in rows]}
    if args.compare:result['comparison']=compare(rows[0][1],rows[1][1])
    text=json.dumps(result,indent=2,ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(text,encoding='utf8')
    print(text)
