"""Configuration proof using the real worker; synthetic transport is explicitly labelled."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research import db, discovery, source_registry, worker
from research.config import Config
from conftest import make_transport

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('meal_profile', ROOT / 'scripts/prepare_meal_discovery.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def test_profile_preserves_history_and_only_enables_meal_sources():
    allow, roster = profile.build_profile()
    original = json.loads((ROOT / 'sources/roster.json').read_text())
    assert roster['surfaces'][:-1] == original['surfaces']
    for key in ('publishers', 'historical_seeds', 'working_set'):
        assert roster[key] == original[key]
    source_registry.validate(roster)
    assert [s['url'] for s in allow['sources']] == list(profile.EXISTING) + [profile.ROUTE]
    assert [s['url'] for s in allow['sources'] if s.get('role') == 'discovery_route'] == [profile.ROUTE]
    assert roster['surfaces'][-1]['cadence_seconds'] == 10800


def test_new_recipe_discovered_collected_and_replay_preserves_evidence(tmp_path):
    allow, roster = profile.build_profile()
    # Isolate the route, so the assertion cannot succeed from manually seeded recipe URLs.
    allow['sources'] = [s for s in allow['sources'] if s.get('role') == 'discovery_route']
    (tmp_path / 'allowlist.json').write_text(json.dumps(allow))
    (tmp_path / 'roster.json').write_text(json.dumps(roster))
    recipe = profile.ROUTE + 'fixture-new-dinner/'
    index = '<html><a href="/fixture-new-dinner/">Dinner</a><a href="https://other.example/x">No</a></html>'
    article = '<html><h1>Fixture dinner</h1><p>' + 'Explicit synthetic recipe fixture. ' * 20 + '</p><h2>Ingredients</h2><ul><li>1 cup rice</li></ul><h2>Directions</h2><ol><li>Cook the rice.</li></ol></html>'
    transport = make_transport({profile.ROUTE: (200, profile.ROUTE, {}, index), recipe: (200, recipe, {}, article)})
    cfg = Config(db_path=tmp_path / 'research.sqlite', allowlist_path=tmp_path / 'allowlist.json',
                 report_path=tmp_path / 'report.md', provider='none', max_urls=2)
    now = datetime(2026, 9, 16, 23, 30, tzinfo=timezone.utc)
    first = worker.run(cfg, transport=transport, content_kind='fixture', due_only=True, clock=lambda: now)
    assert first['routes_fetched'] == 1 and first['discovered_hints'] == 1
    assert first['assessed_permitted'] == 1 and first['evidence_new'] == 0
    second = worker.run(cfg, transport=transport, content_kind='fixture', due_only=True, clock=lambda: now + timedelta(minutes=1))
    assert second['evidence_new'] == 1 and second['fetched_ok'] == 1
    third = worker.run(cfg, transport=transport, content_kind='fixture', due_only=True, clock=lambda: now + timedelta(minutes=2))
    assert third['evidence_new'] == 0 and third['source_requests'] == 0
    conn = db.connect(cfg.db_path)
    assert conn.execute('select count(*) from evidence').fetchone()[0] == 1
    assert conn.execute('select discovery_route from source_hints where url=?', (recipe,)).fetchone()[0] == profile.ROUTE
    assert conn.execute('select count(*) from recipe_publications').fetchone()[0] == 0
    assert conn.execute('select next_check_at from source_state where url=?', (profile.ROUTE,)).fetchone()[0] == '2026-09-17T02:30:00Z'
    assert all('other.example' not in url for url in transport.calls)
    conn.close()
    # A later publisher update is found on the next due poll, without editing configuration.
    newer = profile.ROUTE + 'fixture-next-dinner/'
    changed = make_transport({profile.ROUTE: (200, profile.ROUTE, {},
                            '<html><a href="/fixture-next-dinner/">New</a>' + index + '</html>'),
                            newer: (200, newer, {}, article.replace('Fixture dinner', 'Next fixture dinner'))})
    fourth = worker.run(cfg, transport=changed, content_kind='fixture', due_only=True,
                        clock=lambda: now + timedelta(days=1))
    assert fourth['routes_fetched'] == 1 and fourth['discovered_hints'] == 1
    fifth = worker.run(cfg, transport=changed, content_kind='fixture', due_only=True,
                       clock=lambda: now + timedelta(days=1, minutes=1))
    assert fifth['evidence_new'] == 1
    conn = db.connect(cfg.db_path)
    assert conn.execute('select count(*) from evidence').fetchone()[0] == 2
    conn.close()


def test_index_advances_past_first_twenty_without_duplicates_or_model_calls(tmp_path):
    allow, roster = profile.build_profile()
    allow['sources'] = [s for s in allow['sources'] if s.get('role') == 'discovery_route']
    (tmp_path / 'allowlist.json').write_text(json.dumps(allow))
    (tmp_path / 'roster.json').write_text(json.dumps(roster))
    urls = [profile.ROUTE + 'fixture-dinner-%02d/' % n for n in range(25)]
    index = '<html>' + ''.join('<a href="%s">Dinner</a>' % u for u in urls) + '</html>'
    article = ('<html><h1>Fixture dinner</h1><p>' + 'Explicit synthetic recipe fixture. ' * 20
               + '</p><h2>Ingredients</h2><ul><li>1 cup rice</li></ul>'
               + '<h2>Directions</h2><ol><li>Cook the rice.</li></ol></html>')
    transport = make_transport({profile.ROUTE: (200, profile.ROUTE, {}, index),
                                **{u: (200, u, {}, article) for u in urls}})
    cfg = Config(db_path=tmp_path / 'research.sqlite', allowlist_path=tmp_path / 'allowlist.json',
                 report_path=tmp_path / 'report.md', provider='none', max_urls=10)
    now = datetime(2026, 9, 16, 23, 30, tzinfo=timezone.utc)
    first = worker.run(cfg, transport=transport, content_kind='fixture', due_only=True, clock=lambda: now)
    conn = db.connect(cfg.db_path)
    assert first['discovered_hints'] == 20 and first['inference_calls'] == 0
    assert conn.execute('SELECT COUNT(*) FROM source_hints WHERE discovery_route=?', (profile.ROUTE,)).fetchone()[0] == 20
    conn.close()
    second = worker.run(cfg, transport=transport, content_kind='fixture', due_only=True,
                        clock=lambda: now + timedelta(hours=3))
    conn = db.connect(cfg.db_path)
    assert second['discovered_hints'] == 5 and second['inference_calls'] == 0
    assert conn.execute('SELECT COUNT(*) FROM source_hints WHERE discovery_route=?', (profile.ROUTE,)).fetchone()[0] == 25
    assert conn.execute('SELECT COUNT(*) FROM inference_calls').fetchone()[0] == 0
    conn.close()
    third = worker.run(cfg, transport=transport, content_kind='fixture', due_only=True,
                       clock=lambda: now + timedelta(hours=6))
    conn = db.connect(cfg.db_path)
    assert third['discovered_hints'] == 0 and third['inference_calls'] == 0
    assert conn.execute('SELECT COUNT(*) FROM source_hints WHERE discovery_route=?', (profile.ROUTE,)).fetchone()[0] == 25
    conn.close()


def test_protocol_change_is_not_silently_accepted():
    assert discovery.extract_hints('https://fossrecipes.com/recipes',
                                  '<a href="http://fossrecipes.com/recipes/chicken">Chicken</a>', 20) == []
