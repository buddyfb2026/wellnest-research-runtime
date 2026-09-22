"""Offline source configuration and retained attribution proofs; no live inference."""
import json

from research import db, source_registry, worker
from research.config import Config
from research.library import read_snapshot, render_detail
from research.model import ModelClient
from research.recipe_extract import proposal_for_located
from research.recipe_locate import locate
from scripts import prepare_wikibooks_profile as profile
from tests.conftest import make_transport


def test_profile_has_three_exact_grants_one_publisher_and_preserves_history():
    allow, roster = profile.build_profile()
    prior = json.loads((profile.ROOT / 'sources/roster.json').read_text())
    source_registry.validate(roster)
    assert roster['publishers'][:-1] == prior['publishers']
    assert roster['surfaces'][:-3] == prior['surfaces']
    assert roster['historical_seeds'] == prior['historical_seeds']
    assert roster['working_set'] == prior['working_set']
    assert tuple(s['url'] for s in allow['sources']) == profile.URLS
    assert all(s['fetch'] is True and 'role' not in s for s in allow['sources'])
    assert {s['publisher_id'] for s in roster['surfaces'][-3:]} == {profile.PUBLISHER}
    for source in allow['sources']:
        assert source['url'] in source['attribution']
        assert profile.LICENSE in source['attribution']
        assert 'Changes:' in source['attribution']
        assert 'CC BY-SA 4.0' in source['attribution']
        assert 'EDITORIAL APPROVAL: none' in source['usage_constraints']


def test_credit_license_and_change_notice_survive_worker_and_library(tmp_path):
    allow, roster = profile.build_profile()
    # Exercise the unchanged binding/display path with a synthetic supported layout;
    # this is not a Wikibooks locator test or a real-model yield claim.
    html = ('<html><title>Fixture dinner</title><h1>Fixture dinner</h1><p>' +
            'Synthetic offline attribution fixture context. ' * 8 +
            '</p><h2>Ingredients</h2><ul><li>1 cup rice</li><li>2 cups water</li></ul>'
            '<h2>Directions</h2><ol><li>Boil the water.</li><li>Cook rice until tender.</li></ol></html>')
    # Source-controlled prose stays text, never executable HTML or an injected link.
    allow['sources'][0]['attribution'] += ' <script>bad()</script>'
    for filename, value in [('allowlist.json', allow), ('roster.json', roster)]:
        (tmp_path / filename).write_text(json.dumps(value))
    transport = make_transport({u: (200, u, {'content-type': 'text/html'}, html) for u in profile.URLS})

    def proposal(text, meta):
        return proposal_for_located(text, locate(html, text, 'Fixture dinner')['recipes'][0])

    cfg = Config(db_path=tmp_path / 'research.sqlite', allowlist_path=tmp_path / 'allowlist.json',
                 report_path=tmp_path / 'report.md', provider='fixture', max_urls=3, max_inference=3,
                 recipe_extraction_enabled=True, meals_first=True)
    result = worker.run(cfg, transport=transport, content_kind='fixture',
                        model=ModelClient('fixture', 3, fixture_fn=proposal))
    assert result.ok and result['recipe_versions_new'] == 3
    conn = db.connect(cfg.db_path)
    rows = conn.execute('SELECT state,publishable,content FROM recipe_versions ORDER BY id').fetchall()
    assert len(rows) == 3
    assert all((r['state'], r['publishable']) == ('pending', 0) for r in rows)
    for row, source in zip(rows, allow['sources']):
        assert json.loads(row['content'])['evidence']['attribution'] == source['attribution']
    assert conn.execute('SELECT COUNT(*) FROM recipe_publications').fetchone()[0] == 0
    conn.close()
    cards = read_snapshot(cfg.db_path).recipes
    assert len(cards) == 3
    for card in cards:
        page = render_detail(card)
        assert profile.LICENSE in page and 'Changes:' in page
        assert card.source_url in page and 'Source credit and license' in page
        assert '<script>bad()</script>' not in page
    assert any('&lt;script&gt;bad()&lt;/script&gt;' in render_detail(card) for card in cards)
