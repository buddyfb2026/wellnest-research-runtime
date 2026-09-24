"""Reviewed source identity and restrictive policy (WEL-49).

The roster projects atomically into three tables. It never grants collection authority.
Exact aliases affect denial only, never evidence identity or publisher counts.
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

MIN_CADENCE_S = 21600
MIN_INDEX_CADENCE_S = 10800
MAX_CADENCE_S = 2592000
TOPICS = frozenset(('recipe_supply', 'weekend_methods', 'weekend_activities', 'seasonal_ideas',
                    'household_systems', 'product_discovery', 'parenting', 'family_operations'))
SEEDS_PATH = Path(__file__).resolve().parent.parent / 'seeds/scour_discovery_playbook.json'
PUBLISHER_FIELDS = ('publisher_id', 'canonical_name', 'official_url', 'parent_publisher',
                    'identity_basis', 'assessed_at', 'assessed_by', 'notes')
SURFACE_FIELDS = ('url', 'publisher_id', 'surface_kind', 'topics', 'roster_status', 'roster_reason',
                  'access_status', 'access_basis', 'assessed_at', 'assessed_by', 'cadence_seconds', 'cadence_reason')


def historical_handles():
    data = json.loads(SEEDS_PATH.read_text())
    return {handle: cluster['name'] for cluster in data['clusters'] for handle in cluster['seed_accounts']}


def _text(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError('%s must be a non-empty string' % field)
    return value


def _provenance(row):
    _text(row, 'assessed_at')
    if not re.fullmatch(r'(agent|human):\S.*', _text(row, 'assessed_by')):
        raise ValueError('assessed_by requires agent:<name> or human:<name>')


def _unique(rows, key):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('%s records must be a list of objects' % key)
    ids = [_text(row, key) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate %s' % key)
    return set(ids)


def validate(roster):
    """File-local validation; effective graph and alias collisions checked in the transaction."""
    if not isinstance(roster, dict) or type(roster.get('version')) is not int or roster['version'] != 1:
        raise ValueError('roster version must be 1')
    pubs, surfaces, seeds = (roster.get(k) for k in ('publishers', 'surfaces', 'historical_seeds'))
    _unique(pubs, 'publisher_id')
    urls = _unique(surfaces, 'url')
    handles = _unique(seeds, 'handle')
    expected = historical_handles()
    if len(seeds) != 25 or handles != set(expected):
        raise ValueError('historical_seeds must cover exactly the 25 playbook handles')
    for p in pubs:
        for key in ('canonical_name', 'identity_basis'):
            _text(p, key)
        if p.get('official_url') is not None:
            _text(p, 'official_url')
        _provenance(p)
        if p.get('parent_publisher') is not None:
            _text(p, 'parent_publisher')
    aliases = set()
    for s in surfaces:
        for key in ('roster_reason', 'access_basis'):
            _text(s, key)
        _provenance(s)
        if s.get('surface_kind') not in ('site_article', 'site_index', 'social_profile', 'video_channel'):
            raise ValueError('invalid surface_kind')
        if s.get('roster_status') not in ('retain', 'replace', 'defer', 'candidate'):
            raise ValueError('invalid roster_status')
        if s.get('access_status') not in ('permitted', 'hint_only', 'denied', 'unknown'):
            raise ValueError('invalid access_status')
        topics = s.get('topics')
        if not isinstance(topics, list) or not topics or any(not isinstance(t, str) or t not in TOPICS for t in topics):
            raise ValueError('topics must be a non-empty list from the closed vocabulary')
        cadence = s.get('cadence_seconds')
        if cadence is not None:
            minimum = MIN_INDEX_CADENCE_S if s['surface_kind'] == 'site_index' else MIN_CADENCE_S
            if type(cadence) is not int or not minimum <= cadence <= MAX_CADENCE_S:
                raise ValueError('cadence_seconds must be an integer in [%d, 2592000]' % minimum)
            _text(s, 'cadence_reason')
        equivalent = s.get('equivalent_urls', [])
        if not isinstance(equivalent, list):
            raise ValueError('equivalent_urls must be a list')
        for a in equivalent:
            if not isinstance(a, dict):
                raise ValueError('alias must be an object')
            alias = _text(a, 'alias_url')
            _text(a, 'alias_reason')
            if alias in aliases or alias in urls:
                raise ValueError('alias is duplicate or also a surface')
            aliases.add(alias)
    for s in seeds:
        if s.get('assessment') not in ('retain', 'replace', 'defer'):
            raise ValueError('invalid historical seed assessment')
        _text(s, 'reason')
        if s.get('cluster') != expected[s['handle']]:
            raise ValueError('historical seed cluster differs from playbook')
        if s.get('alias_of') is not None and s['alias_of'] not in handles:
            raise ValueError('unknown historical seed alias')
        if not isinstance(s.get('surface_urls'), list) or any(u not in urls for u in s['surface_urls']):
            raise ValueError('seed surface_urls must name declared surfaces')
    working = roster.get('working_set')
    if not isinstance(working, list) or any(not isinstance(u, str) or u not in urls for u in working):
        raise ValueError('working_set must name declared surfaces')
    if len(working) != len(set(working)):
        raise ValueError('duplicate working_set URL')


def _validate_graph(conn):
    graph = {r['publisher_id']: r['parent_publisher'] for r in conn.execute('SELECT * FROM publishers')}
    for start in graph:
        seen, current, depth = set(), start, 0
        while current is not None:
            if current not in graph:
                raise ValueError('unknown parent publisher: %s' % current)
            if current in seen:
                raise ValueError('publisher cycle')
            if depth > 4:
                raise ValueError('publisher chain deeper than 4')
            seen.add(current)
            current = graph[current]
            depth += 1


def project(conn, roster):
    """Whole-file atomic upsert. Omitted rows retain their last valid policy, never delete-to-enable."""
    conn.execute('BEGIN')
    try:
        validate(roster)
        # Parent references may point forward in this same projection or reverse an old relation.
        conn.execute('PRAGMA defer_foreign_keys = ON')
        for table, fields, rows, key in (
            ('publishers', PUBLISHER_FIELDS, roster['publishers'], 'publisher_id'),
            ('source_surfaces', SURFACE_FIELDS, roster['surfaces'], 'url'),
        ):
            sql = 'INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(%s) DO UPDATE SET %s' % (
                table, ','.join(fields), ','.join('?' for _ in fields), key,
                ','.join('%s=excluded.%s' % (f, f) for f in fields if f != key))
            for row in rows:
                conn.execute(sql, tuple(json.dumps(row[f]) if f == 'topics' else row.get(f) for f in fields))
        for s in roster['surfaces']:
            for a in s.get('equivalent_urls', []):
                conn.execute('INSERT INTO surface_aliases(alias_url,url,alias_reason) VALUES(?,?,?) '
                             'ON CONFLICT(alias_url) DO UPDATE SET url=excluded.url,alias_reason=excluded.alias_reason',
                             (a['alias_url'], s['url'], a['alias_reason']))
        _validate_graph(conn)
        if conn.execute('SELECT 1 FROM surface_aliases a JOIN source_surfaces s ON s.url=a.alias_url LIMIT 1').fetchone():
            raise ValueError('alias cannot also be a surface')
        for seed in roster['historical_seeds']:
            if seed.get('publisher_id') is not None and not conn.execute(
                    'SELECT 1 FROM publishers WHERE publisher_id=?', (seed['publisher_id'],)).fetchone():
                raise ValueError('unknown seed publisher')
        conn.execute('COMMIT')
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    return {'historical_seed_count': len(roster['historical_seeds']),
            'publisher_count': conn.execute('SELECT COUNT(*) FROM publishers').fetchone()[0],
            'surface_count': conn.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0],
            'deferred_count': sum(s['roster_status'] == 'defer' for s in roster['surfaces']),
            'working_set': list(roster['working_set'])}


def load(conn, path):
    try:
        raw = Path(path).read_text()
    except FileNotFoundError:
        return {'status': 'absent', 'reason': 'roster: absent; last valid configuration retained'}
    roster = json.loads(raw)
    summary = project(conn, roster)
    return dict(summary, status='loaded', reason='roster: valid configuration projected')


def effective_denied(conn, url) -> Optional[str]:
    row = conn.execute('SELECT roster_status,access_status,roster_reason FROM source_surfaces WHERE url=? '
                       'OR url=(SELECT url FROM surface_aliases WHERE alias_url=?)', (url, url)).fetchone()
    if row and not (row['access_status'] == 'permitted' and row['roster_status'] == 'retain'):
        return 'registry: effective-denied (%s/%s): %s' % (row['roster_status'], row['access_status'], row['roster_reason'])
    return None


def resolve(conn, url):
    row = conn.execute('SELECT * FROM source_surfaces WHERE url=?', (url,)).fetchone()
    if not row:
        return {'publisher_id': None, 'root_publisher_id': None, 'cadence_seconds': None}
    publisher = row['publisher_id']
    root = publisher
    while root is not None:
        p = conn.execute('SELECT parent_publisher FROM publishers WHERE publisher_id=?', (root,)).fetchone()
        if not p or p['parent_publisher'] is None:
            break
        root = p['parent_publisher']
    return {'publisher_id': publisher, 'root_publisher_id': root,
            'cadence_seconds': row['cadence_seconds'] if publisher is not None else None}


def independent_publishers(conn):
    roots, unattributed = set(), []
    for r in conn.execute('SELECT DISTINCT url FROM evidence ORDER BY url'):
        identity = resolve(conn, r['url'])
        if identity['root_publisher_id'] is None:
            unattributed.append(r['url'])
        else:
            roots.add(identity['root_publisher_id'])
    return {'independent_publisher_count': len(roots), 'root_publisher_ids': sorted(roots),
            'unattributed_surfaces': unattributed}


def render_health(conn):
    rows = conn.execute('SELECT r.*,s.last_success_at,s.last_evidence_id,s.next_check_at '
                        'FROM source_surfaces r LEFT JOIN source_state s ON s.url=r.url ORDER BY r.url').fetchall()
    if not rows:
        return []
    counts = independent_publishers(conn)
    out = ['## Reviewed source registry', '',
           'Independent publishers with evidence: %d. Unattributed evidence URLs: %s.' % (
               counts['independent_publisher_count'], ', '.join(counts['unattributed_surfaces']) or 'none'), '',
           '| surface | publisher | assessment | effective policy | cadence (seconds) | last success / evidence version | next check |',
           '|---|---|---|---|---|---|---|']
    for r in rows:
        identity = resolve(conn, r['url'])
        evidence = conn.execute('SELECT version_no FROM evidence WHERE id=?', (r['last_evidence_id'],)).fetchone()
        policy = effective_denied(conn, r['url']) or 'registry silent; collection still requires a grant'
        out.append('| %s | %s | %s; %s by %s | %s | %s | %s / %s | %s |' % (
            r['url'], identity['root_publisher_id'] or 'unattributed', r['access_status'], r['assessed_at'],
            r['assessed_by'], policy.replace('|', '/'), identity['cadence_seconds'] or 604800,
            r['last_success_at'] or 'never', evidence['version_no'] if evidence else '-', r['next_check_at'] or 'not scheduled'))
    return out + ['']
