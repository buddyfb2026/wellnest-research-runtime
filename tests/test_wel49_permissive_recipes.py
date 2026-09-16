"""WEL-49 permissive recipe sources: committed configuration checks.

The roster and allowlist are the real committed files. Page bodies are synthetic offline fixtures
shaped like the two sources' heading layout; they are not the retained live evidence, which stays
outside git. No network or model call is made.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from research import config, db, source_registry as registry, worker
from research.model import ModelClient
from tests.conftest import make_transport

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 9, 16, 16, tzinfo=timezone.utc)
ORZO = 'https://fossrecipes.com/recipes/orzo-chicken'
CASSEROLE = 'https://publicdomainrecipes.com/easy-chicken-and-rice-casserole/'
FOODISTA = 'https://www.foodista.com/'
NEW_PUBLISHERS = {'public_domain_recipes', 'foss_family_recipes', 'foodista'}
NEW_SURFACES = [ORZO, CASSEROLE, FOODISTA]
HTML = {'content-type': 'text/html'}

FIXTURE_ORZO = ('<html><head><title>Fixture Orzo</title></head><body><h1>Fixture Orzo</h1>'
                '<p>' + 'offline fixture context ' * 20 + '</p><h2>Ingredients</h2><ul>'
                '<li>1 cup uncooked orzo</li><li>2 cups water</li></ul><h2>Directions</h2><ol>'
                '<li>Bring the water to a boil.</li><li>Cook the orzo until tender.</li></ol></body></html>')
FIXTURE_CASSEROLE = ('<html><head><title>Fixture Casserole</title></head><body><h1>Fixture Casserole</h1>'
                     '<ul><li>⏲️ Prep time: 5 min</li><li>\U0001f37d️ Servings: 4</li></ul>'
                     '<p>' + 'offline fixture context ' * 20 + '</p><h2>Ingredients</h2><ul>'
                     '<li>2 cups cooked rice</li><li>1 cup peas</li></ul><h2>Directions</h2><ol>'
                     '<li>Stir everything together.</li><li>Bake until hot.</li></ol></body></html>')


def load():
    roster = json.loads((ROOT / 'sources' / 'roster.json').read_text())
    allow = worker.load_allowlist(ROOT / 'sources' / 'allowlist.json')
    return roster, allow


def projected(data):
    conn = db.connect(':memory:'); db.migrate(conn); registry.project(conn, data)
    return conn


def without_amendment(data):
    data = copy.deepcopy(data)
    data['publishers'] = [p for p in data['publishers'] if p['publisher_id'] not in NEW_PUBLISHERS]
    data['surfaces'] = [s for s in data['surfaces'] if s['url'] not in NEW_SURFACES]
    return data


def test_amendment_appends_and_preserves_every_existing_policy():
    data, allow = load()
    before, after = projected(without_amendment(data)), projected(data)
    old_urls = [s['url'] for s in without_amendment(data)['surfaces']]
    assert [s['url'] for s in data['surfaces']][-3:] == NEW_SURFACES
    assert [p['publisher_id'] for p in data['publishers']][-3:] == ['public_domain_recipes', 'foss_family_recipes', 'foodista']
    for url in old_urls:
        assert registry.effective_denied(after, url) == registry.effective_denied(before, url), url
        assert registry.resolve(after, url) == registry.resolve(before, url), url
    denied_before = [u for u in old_urls if registry.effective_denied(before, u)]
    assert len(denied_before) == 8 and all(registry.effective_denied(after, u) for u in denied_before)
    assert set(NEW_SURFACES).isdisjoint(data['working_set']) and len(data['working_set']) == 10
    assert all(s['assessment'] and s['publisher_id'] not in NEW_PUBLISHERS for s in data['historical_seeds'])
    assert not any(set(NEW_SURFACES) & set(s['surface_urls']) for s in data['historical_seeds'])
    for table in ('publishers', 'source_surfaces'):
        old = after.execute('SELECT COUNT(*) FROM %s' % table).fetchone()[0]
        assert old == before.execute('SELECT COUNT(*) FROM %s' % table).fetchone()[0] + 3
    # Existing grants keep their order, so the manual run's first ten are unchanged.
    assert [e['url'] for e in allow[-2:]] == [ORZO, CASSEROLE]
    manual = lambda conn, rows: [e['url'] for e in rows if e['fetch'] is True
                                 and registry.effective_denied(conn, e['url']) is None][:config.MAX_URLS_HARD_CAP]
    assert manual(after, allow) == manual(before, allow[:-2])
    assert ORZO not in manual(after, allow) and CASSEROLE not in manual(after, allow)


def test_permissive_surfaces_identity_provenance_and_foodista_pending():
    data, allow = load()
    conn = projected(data)
    for url, pid, basis in ((ORZO, 'foss_family_recipes', 'CC0'), (CASSEROLE, 'public_domain_recipes', 'Unlicense')):
        assert registry.resolve(conn, url) == dict(publisher_id=pid, root_publisher_id=pid, cadence_seconds=None)
        assert registry.effective_denied(conn, url) is None
        row = conn.execute('SELECT * FROM source_surfaces WHERE url=?', (url,)).fetchone()
        assert (row['surface_kind'], row['roster_status'], row['access_status']) == ('site_article', 'retain', 'permitted')
        assert json.loads(row['topics']) == ['recipe_supply']
        assert row['assessed_by'] == 'agent:claude-wel49-permissive-sources'
        assert basis in row['access_basis'] and 'not editorial approval' in row['access_basis']
        assert 'TEXT only' in row['access_basis']
        assert 'must not be derived' in row['roster_reason'] or 'none may be derived' in row['roster_reason']
    # Only the named pages are qualified; the site roots and siblings stay unattributed.
    for url in ('https://fossrecipes.com/', 'https://fossrecipes.com/recipes/chicken-stew',
                'https://publicdomainrecipes.com/', 'https://publicdomainrecipes.com/beef-and-broccoli/'):
        assert registry.resolve(conn, url)['publisher_id'] is None
    assert 'Unlicense' in next(p for p in data['publishers'] if p['publisher_id'] == 'public_domain_recipes')['identity_basis']
    assert not any('based' in p['publisher_id'] for p in data['publishers'])
    assert 'not conflated' in next(p for p in data['publishers'] if p['publisher_id'] == 'foss_family_recipes')['identity_basis']
    foodista = conn.execute('SELECT * FROM source_surfaces WHERE url=?', (FOODISTA,)).fetchone()
    assert (foodista['roster_status'], foodista['access_status']) == ('candidate', 'unknown')
    assert registry.effective_denied(conn, FOODISTA) is not None
    assert 'PENDING ACCESS VERIFICATION' in foodista['access_basis'] and 'CC BY 4.0' in foodista['access_basis']
    assert not any('foodista' in e['url'] for e in allow)
    by_url = {e['url']: e for e in allow}
    for url in (ORZO, CASSEROLE):
        e = by_url[url]
        assert e['fetch'] is True and e['source_type'] == 'recipe_site'
        for marker in ('COLLECTION:', 'TEXT RETENTION AND LOCAL INFERENCE:', 'EXCLUSIONS:', 'no images',
                       'EDITORIAL APPROVAL: none', 'do not derive'):
            assert marker in e['usage_constraints'], marker
        assert 'agent:claude-wel49-permissive-sources' in e['discovery_origin'] and 'human:' not in e['discovery_origin']


def test_worker_collects_qualified_pages_only_and_replays_without_duplicates(tmp_path):
    data, allow = load()
    by_url = {e['url']: e for e in allow}
    sibling = dict(by_url[ORZO], url='https://fossrecipes.com/recipes/chicken-stew', fetch=False)
    reasserted_foodista = dict(by_url[ORZO], url=FOODISTA, attribution='Foodista')
    (tmp_path / 'allowlist.json').write_text(json.dumps({'sources': [
        reasserted_foodista, sibling, by_url[ORZO], by_url[CASSEROLE]]}))
    (tmp_path / 'roster.json').write_text(json.dumps(data))
    cfg = config.Config(db_path=tmp_path / 'w.sqlite', allowlist_path=tmp_path / 'allowlist.json',
                        report_path=tmp_path / 'report.md', provider='none', recipe_extraction_enabled=True)
    pages = {ORZO: (200, ORZO, HTML, FIXTURE_ORZO), CASSEROLE: (200, CASSEROLE, HTML, FIXTURE_CASSEROLE)}

    def run():
        tr = make_transport(pages)
        result = worker.run(cfg, transport=tr, model=ModelClient('none', 0), content_kind='fixture',
                            clock=lambda: T0, due_only=False)
        return result, tr

    result, tr = run()
    assert result.ok and result['fetched_ok'] == 2 and result['evidence_new'] == 2
    assert result['registry_denied'] == 1 and result['inference_calls'] == 0
    assert not any('foodista' in u or 'chicken-stew' in u for u in tr.calls)
    conn = db.connect(cfg.db_path)
    rows = {r['url']: r for r in conn.execute('SELECT url, attribution, source_type, content_kind FROM evidence')}
    assert set(rows) == {ORZO, CASSEROLE} and all(r['content_kind'] == 'fixture' for r in rows.values())
    assert rows[CASSEROLE]['attribution'].endswith('contributor Joel Maxuel')
    roots = {registry.resolve(conn, u)['root_publisher_id'] for u in rows}
    assert roots == {'foss_family_recipes', 'public_domain_recipes'}
    assert result['publisher_evidence']['independent_publisher_count'] == 2
    manifests = [json.loads(r[0]) for r in conn.execute('SELECT manifest FROM locator_manifests ORDER BY id')]
    assert [m['recipes'][0]['tier'] for m in manifests] == ['heading', 'heading']
    assert [len(m['recipes'][0]['ingredient_units']) for m in manifests] == [2, 2]
    # No model: the existing path records only unavailable-inference placeholders, never approved.
    versions = [dict(r) for r in conn.execute('SELECT state, publishable, completeness, content FROM recipe_versions')]
    assert len(versions) == 2 and all((v['state'], v['completeness'], v['publishable']) == ('failed', 'failed', 0)
                                      for v in versions)
    assert all('inference_unavailable' in v['content'] for v in versions)
    counts = lambda: tuple(conn.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
                           for t in ('evidence', 'locator_manifests', 'recipe_versions', 'publishers',
                                     'source_surfaces', 'inference_calls'))
    before = counts()
    conn.close()
    again, tr = run()
    conn = db.connect(cfg.db_path)
    assert again.ok and again['evidence_existing'] == 2 and again['evidence_new'] == 0
    assert again['registry_denied'] == 1 and not any('foodista' in u for u in tr.calls)
    assert counts() == before
