"""WEL-54: opt-in local daily allowance and meals-first ordering in the existing worker.

Synthetic temporary stores, stubbed transport and a stubbed Ollama HTTP boundary only. These are
mechanism tests, not live Qwen throughput or quality evidence.
"""
import json
from datetime import datetime, timezone

import pytest

from research import config, db, worker
from research.config import Config
from research.extract import extract
from research.model import ModelClient
from research.recipe_extract import proposal_for_located
from research.recipe_schema import cooking_content_usable
from tests.conftest import ARTICLE, entry, good_proposal, make_transport, write_allowlist
from tests.wel48_helpers import recipe_html

T0 = datetime(2026, 9, 17, 9, tzinfo=timezone.utc)
DAY = '2026-09-17'
HTML = {'content-type': 'text/html'}
A = 'https://fixture.example/household-article'
R1 = 'https://fixture.example/recipe-one'
R2 = 'https://fixture.example/recipe-two'
PAGES = {A: ARTICLE,
         R1: recipe_html(name='Bean Supper', ingredient='1 cup beans', step='Warm the beans.'),
         R2: recipe_html(name='Rice Supper', ingredient='1 cup rice', step='Simmer the rice.')}
ENV = ('WN_RESEARCH_LOCAL_DAILY_BUDGET', 'WN_RESEARCH_MEALS_FIRST', 'WN_RESEARCH_MODEL_PROVIDER',
       'WN_RESEARCH_RECIPE_EXTRACTION', 'WN_RESEARCH_DB')


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


# ---- policy validation -------------------------------------------------------------------------

def test_default_bounds_unchanged_without_opt_in():
    cfg = Config.from_env()
    assert (cfg.max_urls, cfg.max_inference, cfg.max_inference_per_day) == (10, 10, 10)
    assert cfg.local_daily_budget is None and cfg.meals_first is False
    raised = Config.from_env(provider='ollama', max_urls=50, max_inference=50, max_inference_per_day=500)
    assert (raised.max_urls, raised.max_inference, raised.max_inference_per_day) == (10, 10, 10)


@pytest.mark.parametrize('budget,per_day,expected', [
    ('50', None, 50), (50, None, 50), ('100', None, 100), ('1', None, 1),
    ('50', 20, 20), ('50', 500, 50), (' 12 ', None, 12)])
def test_local_allowance_is_the_daily_ceiling_and_per_run_bounds_stay(budget, per_day, expected):
    cfg = Config.from_env(provider='ollama', local_daily_budget=budget, max_inference_per_day=per_day,
                          max_urls=50, max_inference=50)
    assert cfg.max_inference_per_day == expected and isinstance(cfg.local_daily_budget, int)
    assert (cfg.max_urls, cfg.max_inference) == (config.MAX_URLS_HARD_CAP, config.MAX_INFERENCE_HARD_CAP) == (10, 10)


@pytest.mark.parametrize('budget', ['0', '-1', '101', '1000', 'abc', '', '1e2', 'nan', 'inf', '5.0', '+5',
                                    '٥', 0, -3, 101, 5.0, float('inf'), float('nan'), True, None.__class__])
def test_malformed_or_out_of_range_allowance_is_refused(budget):
    with pytest.raises(ValueError):
        Config.from_env(provider='ollama', local_daily_budget=budget)


@pytest.mark.parametrize('provider', ['none', 'fixture'])
def test_allowance_is_local_ollama_only(provider):
    with pytest.raises(ValueError):
        Config.from_env(provider=provider, local_daily_budget='20')


def test_budget_is_cli_only_and_does_not_break_auxiliary_report(monkeypatch, tmp_path):
    # A stale variable from the initial draft must not affect ordinary operator commands.
    monkeypatch.setenv('WN_RESEARCH_LOCAL_DAILY_BUDGET', '30')
    monkeypatch.setenv('WN_RESEARCH_MEALS_FIRST', 'true')
    cfg = Config.from_env()
    assert (cfg.provider, cfg.max_inference_per_day, cfg.meals_first) == ('none', 10, True)
    assert cfg.local_daily_budget is None
    monkeypatch.setenv('WN_RESEARCH_LOCAL_DAILY_BUDGET', 'unbounded')
    store, report = tmp_path / 'operator.sqlite', tmp_path / 'report.md'
    assert worker.main(['report', '--db', str(store), '--report', str(report)]) == 0
    assert report.exists() and report.read_text()
    conn = db.connect(store)
    assert conn.execute('SELECT COUNT(*) FROM inference_calls').fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize('name', ['max_urls', 'max_inference', 'max_inference_per_day'])
@pytest.mark.parametrize('value', [0, -1, '0', '-1', 'abc', '1.5', 1.5, float('nan'), float('inf'), True])
def test_opt_in_rejects_invalid_effective_limits(name, value):
    with pytest.raises(ValueError, match='positive whole number'):
        Config.from_env(provider='ollama', local_daily_budget=40, **{name: value})


@pytest.mark.parametrize('flag', ['--max-urls', '--max-inference', '--max-inference-per-day'])
@pytest.mark.parametrize('value', ['0', '-1'])
def test_invalid_opt_in_cli_limits_fail_before_opening_store(tmp_path, flag, value):
    store = tmp_path / 'must-not-exist.sqlite'
    assert worker.main(['cycle', '--provider', 'ollama', '--local-daily-budget', '40',
                        flag, value, '--db', str(store)]) == 2
    assert not store.exists()


def test_legacy_limit_handling_is_not_redefined():
    cfg = Config.from_env(max_urls=0, max_inference=-1, max_inference_per_day=0)
    assert (cfg.max_urls, cfg.max_inference, cfg.max_inference_per_day) == (0, -1, 0)


def test_cli_parses_opt_in_and_refuses_invalid_before_any_store(tmp_path):
    import argparse
    ns = argparse.Namespace(db=None, allowlist=None, report=None, provider='ollama', max_urls=None,
                            max_inference=None, max_inference_per_day=None, local_daily_budget='40',
                            meals_first=True)
    cfg = worker._run_config(ns)
    assert (cfg.max_inference_per_day, cfg.max_inference, cfg.max_urls, cfg.meals_first) == (40, 10, 10, True)
    store = tmp_path / 'never.sqlite'
    for bad in (['--provider', 'ollama', '--local-daily-budget', '101'],
                ['--provider', 'ollama', '--local-daily-budget', '-5'],
                ['--provider', 'none', '--local-daily-budget', '20']):
        assert worker.main(['run', '--db', str(store), '--report', str(tmp_path / 'r.md')] + bad) == 2
    assert not store.exists()


# ---- worker ordering -----------------------------------------------------------------------------

def _stub_post(calls, fail_recipe=None):
    located = {url: extract(html) for url, html in PAGES.items()}

    def post(url, payload, timeout):
        meta = json.loads(payload['prompt'].split('\n\n', 1)[0].split(': ', 1)[1])
        calls.append(('recipe_extraction' if 'recipe_extraction' in meta else 'candidate_proposal', meta['url']))
        if 'recipe_extraction' in meta:
            if meta['url'] == fail_recipe:
                return {'response': '{not valid JSON'}
            ex = located[meta['url']]
            body = proposal_for_located(ex.text, ex.locators['recipes'][0])
        else:
            body = good_proposal(meta.get('url'), meta)
        return {'response': json.dumps(body)}
    return post


def _run(tmp_path, cfg, cap, calls, urls=(A, R1, R2), fail_recipe=None):
    write_allowlist(tmp_path, [entry(u) for u in urls])
    model = ModelClient('ollama', cfg.max_inference, model='stub',
                        http_post=_stub_post(calls, fail_recipe), daily_cap=cap)
    pages = {u: (200, u, HTML, PAGES[u]) for u in urls}
    return worker.run(cfg, transport=make_transport(pages), model=model, content_kind='fixture',
                      clock=lambda: T0)


def _cfg(tmp_path, meals_first, recipes=True):
    return Config(db_path=tmp_path / 'w.sqlite', allowlist_path=tmp_path / 'allowlist.json',
                  report_path=tmp_path / 'r.md', provider='ollama', recipe_extraction_enabled=recipes,
                  meals_first=meals_first)


def _ledger(cfg):
    conn = db.connect(cfg.db_path)
    return [(r['purpose'], r['status']) for r in conn.execute('SELECT purpose, status FROM inference_calls ORDER BY id')]


def _placeholders(conn):
    return conn.execute("SELECT COUNT(*) FROM candidates WHERE state_reason LIKE 'inference_budget_exhausted%'").fetchone()[0]


def test_default_mode_keeps_generic_first_order(tmp_path):
    cfg = _cfg(tmp_path, meals_first=False); calls = []
    result = _run(tmp_path, cfg, 4, calls)
    assert result.ok and result['meals_first'] is False
    assert [p for p, _ in _ledger(cfg)] == ['candidate_proposal'] * 3 + ['recipe_extraction']
    conn = db.connect(cfg.db_path)
    # Legacy behaviour under a constrained day: one recipe waits behind generic work.
    assert conn.execute("SELECT COUNT(*) FROM recipe_versions WHERE completeness='complete'").fetchone()[0] == 1


def test_meals_first_reserves_recipe_calls_before_generic_and_generic_uses_the_rest(tmp_path):
    cfg = _cfg(tmp_path, meals_first=True); calls = []
    result = _run(tmp_path, cfg, 4, calls)
    assert result.ok and result['meals_first'] is True and result['inference_calls'] == 4
    assert _ledger(cfg) == [('recipe_extraction', 'ok')] * 2 + [('candidate_proposal', 'ok')] * 2
    assert [c for c in calls] == [('recipe_extraction', R1), ('recipe_extraction', R2),
                                  ('candidate_proposal', A), ('candidate_proposal', R1)]
    conn = db.connect(cfg.db_path)
    rows = conn.execute("SELECT content, completeness, state, publishable FROM recipe_versions ORDER BY id").fetchall()
    assert len(rows) == 2 and all(r['completeness'] == 'complete' and r['state'] == 'pending'
                                  and r['publishable'] == 0 for r in rows)
    assert all(cooking_content_usable(json.loads(r['content'])) for r in rows)
    generic = conn.execute("SELECT evidence_id, state_reason FROM candidates WHERE generator='ollama:stub' "
                           "ORDER BY evidence_id").fetchall()
    assert len(generic) == 3 and _placeholders(conn) == 1 and result['budget_deferred'] == 1
    assert ModelClient.used_today(conn, DAY) == 4
    conn.close()

    # Same UTC day, more local allowance: only the deferred generic work runs; recipes replay without calls.
    calls.clear()
    again = _run(tmp_path, cfg, 5, calls)
    assert again.ok and calls == [('candidate_proposal', R2)]
    conn = db.connect(cfg.db_path)
    assert _placeholders(conn) == 0 and ModelClient.used_today(conn, DAY) == 5
    assert conn.execute('SELECT COUNT(*) FROM recipe_versions').fetchone()[0] == 2
    conn.close()

    # Exhausted day: nothing dispatched, nothing refunded, no duplicate rows.
    calls.clear()
    third = _run(tmp_path, cfg, 5, calls)
    assert third.ok and calls == [] and len(_ledger(cfg)) == 5


def test_meals_first_without_eligible_recipe_runs_generic_normally(tmp_path):
    outputs = {}
    for mode in (False, True):
        path = tmp_path / str(mode); path.mkdir()
        cfg = _cfg(path, meals_first=mode); calls = []
        result = _run(path, cfg, 10, calls, urls=(A,))
        conn = db.connect(cfg.db_path)
        outputs[mode] = (result['inference_calls'], _ledger(cfg), [tuple(r) for r in conn.execute(
            'SELECT generator, state, state_reason FROM candidates ORDER BY id')])
    assert outputs[True] == outputs[False]
    assert outputs[True][1] == [('candidate_proposal', 'ok')]


def test_failed_recipe_is_charged_and_generic_work_uses_remaining_capacity(tmp_path):
    cfg = _cfg(tmp_path, meals_first=True); calls = []
    result = _run(tmp_path, cfg, 3, calls, urls=(A, R1), fail_recipe=R1)
    assert result['inference_calls'] == 3
    assert calls == [('recipe_extraction', R1), ('candidate_proposal', A), ('candidate_proposal', R1)]
    assert _ledger(cfg) == [('recipe_extraction', 'error'), ('candidate_proposal', 'ok'),
                            ('candidate_proposal', 'ok')]
    conn = db.connect(cfg.db_path)
    assert ModelClient.used_today(conn, DAY) == 3
    assert [tuple(r) for r in conn.execute(
        'SELECT completeness,state,publishable FROM recipe_versions')] == [('failed', 'failed', 0)]
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE generator='ollama:stub'").fetchone()[0] == 2
    assert _placeholders(conn) == 0
    conn.close()

    # A failed settled attempt is neither refunded nor retried on the next entrance.
    calls.clear()
    again = _run(tmp_path, cfg, 3, calls, urls=(A, R1), fail_recipe=R1)
    assert again['inference_calls'] == 0 and calls == []
    assert _ledger(cfg) == [('recipe_extraction', 'error'), ('candidate_proposal', 'ok'),
                            ('candidate_proposal', 'ok')]


def test_meals_first_with_extraction_disabled_is_legacy(tmp_path):
    cfg = _cfg(tmp_path, meals_first=True, recipes=False); calls = []
    result = _run(tmp_path, cfg, 10, calls)
    assert result.ok and [p for p, _ in _ledger(cfg)] == ['candidate_proposal'] * 3
    assert db.connect(cfg.db_path).execute('SELECT COUNT(*) FROM recipe_versions').fetchone()[0] == 0


def test_local_allowance_above_ten_uses_the_same_persisted_ledger(tmp_path):
    cfg = Config.from_env(db_path=tmp_path / 'w.sqlite', allowlist_path=tmp_path / 'allowlist.json',
                          report_path=tmp_path / 'r.md', provider='ollama', local_daily_budget='12',
                          meals_first=True)
    cfg.recipe_extraction_enabled = True
    assert (cfg.max_inference_per_day, cfg.max_inference) == (12, 10)
    conn = db.connect(cfg.db_path); db.migrate(conn)
    for i in range(10):   # ten calls already charged today by earlier runs (any provider, any status)
        conn.execute("INSERT INTO inference_calls(run_id, provider, model, purpose, evidence_id, prompt_hash, "
                     "called_at, ok, error, response_chars, day, status) VALUES(?,?,?,?,NULL,?,?,0,NULL,0,?,?)",
                     ('earlier', 'ollama', 'earlier', 'candidate_proposal', 'h%d' % i, DAY + 'T01:00:00Z', DAY,
                      'ambiguous' if i == 0 else 'ok'))
    conn.commit(); conn.close()
    calls = []
    result = _run(tmp_path, cfg, cfg.max_inference_per_day, calls)
    assert result.ok and result['inference_used_today'] == 12
    assert calls == [('recipe_extraction', R1), ('recipe_extraction', R2)]
    conn = db.connect(cfg.db_path)
    assert conn.execute('SELECT COUNT(*) FROM inference_calls').fetchone()[0] == 12
    assert _placeholders(conn) == 3
    # The fixed default would have refused every call on this day.
    default_cfg = Config.from_env(provider='ollama')
    assert default_cfg.max_inference_per_day == 10 <= ModelClient.used_today(conn, DAY)
