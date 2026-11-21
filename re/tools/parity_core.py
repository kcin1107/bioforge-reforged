"""Pure helpers for the DOSBox-X/Python-port parity harness.

This module deliberately has no game or DOSBox dependency: runners produce JSONL traces
and pass them here for scheduling, alignment, comparison, and reporting.
"""
import json
import math
import os


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('%s must be an integer' % name)
    return value


def _scan(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16)
    raise ValueError('input scan must be an integer or hexadecimal string')


def load_scenario(path):
    """Load and validate the small JSON scenario contract used by both runners."""
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError('scenario root must be an object')
    for key in ('name', 'figures', 'fields', 'sample_period'):
        if key not in data:
            raise ValueError('scenario missing %s' % key)
    if not isinstance(data['name'], str) or not data['name']:
        raise ValueError('scenario name must be a non-empty string')
    if not isinstance(data['figures'], list) or not all(isinstance(x, str) for x in data['figures']):
        raise ValueError('figures must be a list of names')
    if not isinstance(data['fields'], list) or not all(isinstance(x, str) for x in data['fields']):
        raise ValueError('fields must be a list of names')
    if _integer(data['sample_period'], 'sample_period') <= 0:
        raise ValueError('sample_period must be positive')
    boot = data.get('boot', 'new_game')
    if boot != 'new_game':
        if not isinstance(boot, dict) or not isinstance(boot.get('save'), str) or not boot['save']:
            raise ValueError('boot must be new_game or a save object')
        if _integer(boot.get('slot'), 'save slot') not in range(1, 10):
            raise ValueError('save slot must be 1..9')
        if not isinstance(boot.get('keys'), str) or not boot['keys']:
            raise ValueError('save boot needs load-dialog keys')
    anchor = data.get('anchor')
    if anchor is not None:
        if not isinstance(anchor, dict) or anchor.get('type') not in ('control', 'motion'):
            raise ValueError('anchor type must be control or motion')
        if not isinstance(anchor.get('figure'), str):
            raise ValueError('anchor needs a figure')
        if anchor['type'] == 'motion' and not isinstance(anchor.get('motion'), str):
            raise ValueError('motion anchor needs a motion')
    for item in data.get('inputs', []):
        if not isinstance(item, dict) or 'scan' not in item or 'start' not in item or 'end' not in item:
            raise ValueError('each input needs scan, start, and end')
        item['scan'] = _scan(item['scan'])
        start, end = _integer(item['start'], 'input start'), _integer(item['end'], 'input end')
        if end < start:
            raise ValueError('input end precedes start')
    for poke in data.get('pokes', []):
        if not isinstance(poke, dict) or 'at' not in poke or 'type' not in poke:
            raise ValueError('each poke needs at and type')
        _integer(poke['at'], 'poke at')
    for key, value in data.get('tolerances', {}).items():
        if not isinstance(key, str) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError('tolerances must map names to non-negative numbers')
    return data


def clock_to_vm_tick(clock):
    """The game clock runs at 60 Hz; the prototype VM runs at 30 Hz."""
    return _integer(clock, 'clock') // 2


def scheduled_inputs(scenario, clock, anchor_clock=0):
    """Return scan codes held at absolute game-clock *clock*.

    Scenario input times are relative to the optional anchor.  End is exclusive,
    matching the prototype's per-tick control application.
    """
    relative = _integer(clock, 'clock') - _integer(anchor_clock, 'anchor_clock')
    return [event['scan'] for event in scenario.get('inputs', [])
            if event['start'] <= relative < event['end']]


def due_pokes(scenario, clock, anchor_clock=0):
    """Return scenario pokes due at this absolute clock."""
    relative = _integer(clock, 'clock') - _integer(anchor_clock, 'anchor_clock')
    return [poke for poke in scenario.get('pokes', []) if poke['at'] == relative]


def find_anchor(trace, anchor):
    """Find the first trace sample matching an event anchor, or ``None``."""
    if anchor is None:
        return trace[0]['clock'] if trace else None
    figure = anchor['figure']
    # In the opening, the collision flag can be clear before the scripted
    # OUT_OF_BED handoff.  Once that motion is observable, control means the
    # first collision-enabled sample after it ends.
    out_of_bed_seen = any(sample.get('figures', {}).get(figure, {}).get('motion', '').upper() == 'OUT_OF_BED'
                          for sample in trace)
    left_bed = not out_of_bed_seen
    for sample in trace:
        state = sample.get('figures', {}).get(figure)
        if state is None:
            continue
        if state.get('motion', '').upper() == 'OUT_OF_BED':
            left_bed = True
            continue
        if anchor['type'] == 'control' and left_bed and not (int(state.get('flags', 2)) & 2):
            return sample['clock']
        if anchor['type'] == 'motion' and state.get('motion', '').upper() == anchor['motion'].upper():
            return sample['clock']
    return None


def align_traces(original, port, anchor=None, clock_tolerance=None):
    """Pair monotonic nearest samples after subtracting each trace's anchor clock.

    The DOS debugger observes a live clock between memory dumps, so its sampling
    cadence is not exact.  A port sample may therefore be up to half a configured
    sampling period away while still representing the same requested observation.
    """
    original_anchor = find_anchor(original, anchor)
    port_anchor = find_anchor(port, anchor)
    if original_anchor is None or port_anchor is None:
        return {'anchor': {'original': original_anchor, 'port': port_anchor}, 'pairs': []}
    if clock_tolerance is None:
        clock_tolerance = 0
    clock_tolerance = max(0, int(clock_tolerance))
    port_samples = sorted((sample['clock'] - port_anchor, sample) for sample in port
                          if sample['clock'] >= port_anchor)
    pairs = []
    port_index = 0
    for sample in original:
        relative = sample['clock'] - original_anchor
        if relative < 0:
            continue
        while port_index + 1 < len(port_samples) and port_samples[port_index + 1][0] <= relative:
            port_index += 1
        candidates = list(enumerate(port_samples[port_index:port_index + 2], start=port_index))
        if candidates:
            chosen, (port_relative, other) = min(candidates, key=lambda item: abs(item[1][0] - relative))
        else:
            chosen, port_relative, other = None, None, None
        if other is not None and abs(port_relative - relative) <= clock_tolerance:
            pairs.append({'clock': relative, 'original_clock': sample['clock'],
                          'port_clock': other['clock'], 'clock_delta': port_relative - relative,
                          'original': sample, 'port': other})
            port_index = chosen + 1
    return {'anchor': {'original': original_anchor, 'port': port_anchor}, 'pairs': pairs}


def _field_names(original, port, figures, fields):
    if figures is None:
        figures = sorted(set().union(*(s.get('figures', {}) for s in original + port)))
    if fields is None:
        fields = sorted(set().union(*(f for s in original + port for f in s.get('figures', {}).values()
                                      if isinstance(f, dict) for f in f)))
    return figures, fields


def _tolerance(tolerances, figure, field, component=None):
    names = []
    if component is not None:
        names += ['%s.%s.%s' % (figure, field, component), '%s.%s' % (field, component)]
    names += ['%s.%s' % (figure, field), field]
    return next((tolerances[name] for name in names if name in tolerances), 0)


def _difference(left, right, field):
    if left is None or right is None:
        return math.inf if left != right else 0.0
    if field == 'heading':
        return abs((float(left) - float(right) + 180.0) % 360.0 - 180.0)
    if field == 'motion' and isinstance(left, str) and isinstance(right, str):
        return 0.0 if left.upper() == right.upper() else math.inf
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right))
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            return math.inf
        if all(isinstance(x, (int, float)) for x in left + right):
            return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))
    return 0.0 if left == right else math.inf


def _components(field, left, right):
    """Yield comparable numeric vector components, otherwise one whole-field item."""
    if (isinstance(left, (list, tuple)) and isinstance(right, (list, tuple))
            and len(left) == len(right) and all(isinstance(x, (int, float)) for x in left + right)):
        labels = {'pos': ('x', 'y', 'z'),
                  'hull': ('min_x', 'min_y', 'min_z', 'max_x', 'max_y', 'max_z')}.get(field)
        for index, (a, b) in enumerate(zip(left, right)):
            yield (labels[index] if labels and index < len(labels) else str(index), a, b)
        return
    yield (None, left, right)


def compare_traces(original, port, figures=None, fields=None, tolerances=None, anchor=None):
    """Compare aligned figure fields and return first failures plus numeric drift."""
    # The runner deliberately passes the complete parsed scenario as the third
    # argument.  Keeping the explicit arguments also makes this useful in small
    # focused tests and ad-hoc investigations.
    scenario = figures if isinstance(figures, dict) else None
    if scenario is not None:
        figures = scenario.get('figures')
        fields = scenario.get('fields')
        tolerances = scenario.get('tolerances')
        anchor = scenario.get('anchor')
    tolerances = tolerances or {}
    clock_tolerance = max(1, int(scenario.get('sample_period', 1)) // 2) if scenario else 0
    aligned = align_traces(original, port, anchor, clock_tolerance)
    figures, fields = _field_names(original, port, figures, fields)
    first, drift = {}, {}
    for figure in figures:
        for field in fields:
            if field == 'camera':
                continue
            records = {}
            for pair in aligned['pairs']:
                left = pair['original'].get('figures', {}).get(figure, {}).get(field)
                right = pair['port'].get('figures', {}).get(figure, {}).get(field)
                for component, a, b in _components(field, left, right):
                    key = '%s.%s%s' % (figure, field, '' if component is None else '.' + component)
                    record = records.setdefault(key, {'component': component, 'deltas': []})
                    delta = _difference(a, b, field if component is None else '')
                    if math.isfinite(delta):
                        record['deltas'].append(delta)
                    tolerance = _tolerance(tolerances, figure, field, component)
                    if key not in first and delta > tolerance:
                        first[key] = {'figure': figure, 'field': field, 'component': component,
                                      'clock': pair['clock'], 'original_clock': pair['original_clock'],
                                      'port_clock': pair['port_clock'], 'original': a, 'port': b,
                                      'delta': delta, 'tolerance': tolerance}
            for key, record in records.items():
                deltas = record['deltas']
                if deltas:
                    drift[key] = {'max': max(deltas), 'mean': sum(deltas) / len(deltas),
                                  'rms': math.sqrt(sum(x * x for x in deltas) / len(deltas)), 'samples': len(deltas)}
    if 'camera' in fields:
        key, deltas, tolerance = 'WORLD.camera', [], tolerances.get('camera', 0)
        for pair in aligned['pairs']:
            left, right = pair['original'].get('camera'), pair['port'].get('camera')
            delta = _difference(left, right, 'camera')
            if math.isfinite(delta):
                deltas.append(delta)
            if key not in first and delta > tolerance:
                first[key] = {'figure': 'WORLD', 'field': 'camera', 'clock': pair['clock'],
                              'original_clock': pair['original_clock'], 'port_clock': pair['port_clock'],
                              'original': left, 'port': right, 'delta': delta, 'tolerance': tolerance}
        if deltas:
            drift[key] = {'max': max(deltas), 'mean': sum(deltas) / len(deltas),
                          'rms': math.sqrt(sum(x * x for x in deltas) / len(deltas)), 'samples': len(deltas)}
    no_samples = not aligned['pairs']
    return {'anchor': aligned['anchor'], 'samples': len(aligned['pairs']), 'first_divergence': first,
            'drift': drift, 'diverged': bool(first) or no_samples, 'divergent': bool(first) or no_samples,
            'error': 'no aligned samples' if no_samples else None, 'timeline': aligned['pairs']}


def report_markdown(summary, scenario):
    lines = ['# Parity report: %s' % scenario, '',
             'Aligned samples: %d. Anchor clocks: original %r, port %r.' %
             (summary['samples'], summary['anchor']['original'], summary['anchor']['port']), '']
    if summary.get('error'):
        lines += ['**Comparison failed:** %s.' % summary['error'], '']
    lines += [
             '## First divergence', '', '| Figure.field | Clock | Delta | Tolerance | Original | Port |',
             '|---|---:|---:|---:|---|---|']
    if summary['first_divergence']:
        for key, entry in sorted(summary['first_divergence'].items()):
            lines.append('| %s | %s | %s | %s | `%s` | `%s` |' %
                         (key, entry['clock'], entry['delta'], entry['tolerance'],
                          entry['original'], entry['port']))
    else:
        lines.append('| none | — | — | — | — | — |')
    lines += ['', '## Drift', '', '| Figure.field | Max | Mean | RMS | Samples |', '|---|---:|---:|---:|---:|']
    for key, entry in sorted(summary['drift'].items()):
        lines.append('| %s | %.3f | %.3f | %.3f | %d |' %
                     (key, entry['max'], entry['mean'], entry['rms'], entry['samples']))
    return '\n'.join(lines) + '\n'


def _plot_positions(summary, path):
    """Write position coordinates against relative game clock, when Pillow is installed."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    paths = {}
    for pair in summary['timeline']:
        for label, sample in (('original', pair['original']), ('port', pair['port'])):
            for figure, state in sample.get('figures', {}).items():
                pos = state.get('pos')
                if isinstance(pos, list) and len(pos) >= 2:
                    paths.setdefault(figure, {}).setdefault(label, []).append((pair['clock'], [float(v) for v in pos[:3]]))
    values = [value for figure in paths.values() for trace in figure.values()
              for _, position in trace for value in position]
    clocks = [clock for figure in paths.values() for trace in figure.values() for clock, _ in trace]
    if not values or not clocks:
        return False
    width, panel, margin = 900, 170, 50
    height = margin + panel * len(paths) + 35
    xmin, xmax = min(clocks), max(clocks)
    ymin, ymax = min(values), max(values)
    span_x, span_y = max(1.0, xmax - xmin), max(1.0, ymax - ymin)
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    colors = {'original': ('#1769aa', '#16803c', '#673ab7'), 'port': ('#e85d04', '#b23a48', '#9d4edd')}
    for index, (figure, traces) in enumerate(sorted(paths.items())):
        top, bottom = margin + panel * index, margin + panel * (index + 1) - 25
        draw.rectangle((margin, top, width - margin, bottom), outline='#999999')
        for label, trace in traces.items():
            for axis, axis_name in enumerate(('x', 'y', 'z')):
                pixels = [(margin + (clock - xmin) / span_x * (width - 2 * margin),
                           bottom - (position[axis] - ymin) / span_y * (bottom - top))
                          for clock, position in trace]
                if len(pixels) > 1:
                    draw.line(pixels, fill=colors[label][axis], width=2)
        draw.text((margin + 4, top + 4), '%s  original: x/y/z; port: x/y/z' % figure, fill='black')
        draw.text((width - margin - 115, top + 4), '%d..%d clock' % (xmin, xmax), fill='black')
    draw.text((margin, 15), 'Position over relative game clock — original (blue/green/purple), port (orange/red/violet)', fill='black')
    image.save(path)
    return True


def _json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return 'infinite'
    if isinstance(value, list):
        return [_json_value(v) for v in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def write_report(summary, out_dir, scenario):
    """Write the JSON summary, Markdown report, and optional PNG position plot."""
    os.makedirs(out_dir, exist_ok=True)
    clean = dict(summary)
    clean.pop('timeline', None)
    with open(os.path.join(out_dir, 'report.json'), 'w', encoding='utf-8') as handle:
        json.dump(_json_value(clean), handle, indent=2, sort_keys=True, allow_nan=False)
    with open(os.path.join(out_dir, 'report.md'), 'w', encoding='utf-8') as handle:
        handle.write(report_markdown(summary, scenario['name'] if isinstance(scenario, dict) else scenario))
    _plot_positions(summary, os.path.join(out_dir, 'positions.png'))
