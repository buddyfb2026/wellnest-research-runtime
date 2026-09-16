"""Binding WEL-49 mechanics: offline source/clock fixtures, real SQLite projection and request gates.

Fixture provenance says agent:fixture, never claims a real source assessment. Production roster
and live three-publisher evidence remain a separate acceptance artifact.
"""
import copy
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research import config, db, discovery, evidence, schedule, source_registry as registry, worker
from research.fetch import Fetcher
from research.model import ModelClient
from tests.conftest import ARTICLE, ARTICLE_CHANGED, entry, good_proposal, make_transport, write_allowlist
from tests.test_recurring import Clock

T0 = datetime(2026, 9, 15, tzinfo=timezone.utc)
H = timedelta(hours=1)
D = timedelta(days=1)
U = 'https://fixture.example/article'
V = 'https://fixture.example/second'
HTML = {'content-type': 'text/html'}


def publisher(pid='p', parent=None):
    return dict(publisher_id=pid, canonical_name='Fixture '+pid, official_url='https://fixture.example/'+pid,
                parent_publisher=parent, identity_basis='Offline fixture, not a real assessment',
                assessed_at=schedule.iso(T0), assessed_by='agent:fixture')


def surface(url=U, pid='p', status='retain', access='permitted', cadence=21600, **extra):
    return dict(url=url, publisher_id=pid, surface_kind='site_article', topics=['household_systems'],
                roster_status=status, roster_reason='Offline fixture policy', access_status=access,
                access_basis='fixture only', assessed_at=schedule.iso(T0), assessed_by='agent:fixture',
                cadence_seconds=cadence, cadence_reason='Offline six-hour scenario' if cadence else None, **extra)


def roster(surfaces=None, pubs=None):
    return dict(version=1, publishers=pubs if pubs is not None else [publisher()],
                surfaces=surfaces if surfaces is not None else [surface()],
                historical_seeds=[dict(handle=h, cluster=c, assessment='defer', reason='Unassessed offline fixture',
                                       alias_of=None, publisher_id=None, surface_urls=[])
                                  for h,c in registry.historical_handles().items()], working_set=[])


def store(path=':memory:'):
    conn=db.connect(path); db.migrate(conn); return conn


def write_roster(cfg, data):
    path=cfg.allowlist_path.parent/'roster.json'; path.write_text(json.dumps(data)); return path


def run(cfg, entries=None, data=None, pages=None, now=T0, due_only=True, model=None, transport=None, **kw):
    if entries is not None: write_allowlist(cfg.allowlist_path.parent, entries)
    if data is not None: write_roster(cfg,data)
    tr=transport or make_transport(pages if pages is not None else {U:(200,U,HTML,ARTICLE)})
    result=worker.run(cfg, transport=tr, model=model or ModelClient('none',0), content_kind='fixture',
                      clock=now if callable(now) else lambda:now, due_only=due_only, **kw)
    return result,tr


def snapshot(conn):
    return {table:[tuple(r) for r in conn.execute('SELECT * FROM '+table+' ORDER BY 1')]
            for table in ['publishers','source_surfaces','surface_aliases']}


def prime(conn,urls,attempts=0):
    for u in urls:
        evidence.upsert_source_hint(conn,entry(u))
        schedule.ensure_state(conn,u,T0)
        conn.execute('UPDATE source_state SET attempts=? WHERE url=?',(attempts,u))


def test_historical_seeds_cover_all_25():
    c=store(); r=roster(); assert len(r['historical_seeds'])==25
    assert {x['handle'] for x in r['historical_seeds']}==set(registry.historical_handles())
    assert all(x['assessment'] and x['reason'] for x in r['historical_seeds'])
    r['historical_seeds'].pop()
    with pytest.raises(ValueError): registry.project(c,r)
    assert c.execute('SELECT COUNT(*) FROM publishers').fetchone()[0]==0


def test_seed_counts_are_independent():
    r=roster([surface(U,'busy_toddler'),surface(V,'playing_preschool')],
             [publisher('busy_toddler'),publisher('playing_preschool','busy_toddler')])
    seed=next(x for x in r['historical_seeds'] if x['handle']=='playingpreschool')
    seed.update(alias_of='busytoddler',publisher_id='playing_preschool',surface_urls=[V])
    c=store(); summary=registry.project(c,r)
    assert summary['historical_seed_count']==25
    assert summary['publisher_count']==2 and summary['surface_count']==2
    assert registry.resolve(c,V)['root_publisher_id']=='busy_toddler'


def test_working_set_is_ordered_and_declared(cfg):
    data=roster([surface(U),surface(V,status='defer')]); data['working_set']=[V,U]
    r,_=run(cfg,[entry(U)],data)
    assert r['roster']['working_set']==[V,U] and r['roster']['deferred_count']==1
    c=db.connect(cfg.db_path)
    assert c.execute('SELECT COUNT(*) FROM source_state WHERE url=?',(V,)).fetchone()[0]==0


def test_working_set_entries_must_be_declared_surfaces():
    c=store(); r=roster(); r['working_set']=[V]
    with pytest.raises(ValueError): registry.project(c,r)
    assert c.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0]==0


@pytest.mark.parametrize('field',['url','surface_kind','topics','roster_status','roster_reason','access_status','access_basis','assessed_at','assessed_by'])
def test_surface_requires_all_recorded_fields(field):
    c=store(); r=roster(); del r['surfaces'][0][field]
    with pytest.raises(ValueError): registry.project(c,r)
    assert c.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0]==0


@pytest.mark.parametrize('value,valid',[('agent:fixture',True),('human:fixture',True),('fixture',False),('agent:',False)])
def test_assessed_by_requires_honest_prefix(value,valid):
    c=store(); r=roster(); r['surfaces'][0]['assessed_by']=value
    if valid: registry.project(c,r); assert c.execute('SELECT assessed_by FROM source_surfaces').fetchone()[0]==value
    else:
        with pytest.raises(ValueError): registry.project(c,r)
        assert c.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0]==0


def test_roster_never_grants_permission(cfg):
    r,tr=run(cfg,[entry(U,fetch=False)],roster())
    c=db.connect(cfg.db_path)
    assert c.execute('SELECT fetch_permitted FROM source_hints').fetchone()[0]==0
    assert c.execute('SELECT COUNT(*) FROM source_state').fetchone()[0]==0
    assert r['source_requests']==0 and r['robots_requests']==0
    assert tr.calls==[]


@pytest.mark.parametrize('due_only',[False,True])
def test_granted_to_hint_only_denies_all_modes(cfg,due_only):
    run(cfg,[entry(U)],roster())
    data=roster([surface(access='hint_only')])
    r,tr=run(cfg,data=data,now=T0+7*D,due_only=due_only,pages={})
    assert r['source_requests']==0 and r['robots_requests']==0 and tr.calls==[]
    assert r['registry_denied']==1


@pytest.mark.parametrize('due_only',[False,True])
def test_denied_surface_not_requested_manual_and_cycle(cfg,due_only):
    r,tr=run(cfg,[entry(U)],roster([surface(access='denied')]),due_only=due_only)
    assert r['source_requests']==0 and r['robots_requests']==0 and tr.calls==[]


@pytest.mark.parametrize('status,access',[('retain','unknown'),('candidate','permitted'),('replace','permitted'),('defer','permitted')])
def test_unknown_and_candidate_deny_existing_grant(cfg,status,access):
    run(cfg,[entry(U)],roster())
    r,tr=run(cfg,data=roster([surface(status=status,access=access)]),now=T0+7*D)
    assert r['source_requests']==0 and tr.calls==[]


def test_sibling_surface_unaffected_by_hint_only(cfg):
    r,tr=run(cfg,[entry(U),entry(V)],roster([surface(access='hint_only'),surface(V)]),pages={V:(200,V,HTML,ARTICLE)})
    assert r['fetched_ok']==1 and U not in tr.calls and V in tr.calls


def test_allowlist_reassertion_cannot_override_denial(cfg):
    run(cfg,[entry(U)],roster([surface(access='denied')]))
    r,tr=run(cfg,entries=[entry(U)],due_only=False)
    assert db.connect(cfg.db_path).execute('SELECT fetch_permitted FROM source_hints').fetchone()[0]==1
    assert r['source_requests']==0 and r['robots_requests']==0


def test_registration_failure_does_not_bypass_denial(cfg):
    run(cfg,[entry(U)],roster([surface(access='denied')]))
    c=db.connect(cfg.db_path)
    c.execute("CREATE TRIGGER fail_registration BEFORE UPDATE ON source_hints BEGIN SELECT RAISE(ABORT,'injected registration failure'); END")
    c.close()
    r,tr=run(cfg,due_only=False)
    assert r['status']=='failed' and r['source_requests']==0 and tr.calls==[]


def test_denied_rows_do_not_starve_active_sources():
    c=store(); denied=['https://fixture.example/a%d'%i for i in range(12)]; active=['https://fixture.example/z%d'%i for i in range(4)]
    prime(c,denied+active); registry.project(c,roster([surface(u,access='denied') for u in denied]))
    selected=schedule.select_cycle_urls(c,T0,10)['selected']
    assert len(selected)==4 and selected==active and len(set(selected)&set(denied))==0


def test_exploration_formula_unchanged_over_pool():
    c=store(); active=['https://fixture.example/a%d'%i for i in range(8)]; new=['https://fixture.example/z%d'%i for i in range(5)]
    prime(c,active,2); prime(c,new); before=schedule.select_cycle_urls(c,T0,6)
    denied=['https://fixture.example/000']; prime(c,denied); registry.project(c,roster([surface(denied[0],access='denied')]))
    assert schedule.select_cycle_urls(c,T0,6)==before
    assert before['reserved_slots']==2 and len(before['selected'])==6


def test_redirect_into_denied_is_blocked():
    c=store(); dest='https://other.example/denied'; registry.project(c,roster([surface(dest,access='denied')]))
    tr=make_transport({U:(302,U,{'location':dest},'')})
    f=Fetcher(tr,clock=lambda:T0,deny_fn=lambda u:registry.effective_denied(c,u)); result=f.fetch(U)
    assert result.outcome=='blocked' and f.requests_made==1 and f.robots_requests==1
    assert dest not in tr.calls and 'https://other.example/robots.txt' not in tr.calls
    assert 'registry: effective-denied' in result.reason


def test_denied_hint_costs_zero_robots():
    c=store(); registry.project(c,roster([surface(access='denied')]))
    route=entry('https://fixture.example/'); discovery.record_hint(c,U,route,schedule.iso(T0))
    tr=make_transport({}); f=Fetcher(tr); hint=c.execute('SELECT * FROM source_hints').fetchone()
    ok,reason=discovery.assess(c,f,hint,schedule.iso(T0))
    assert ok is False and f.robots_requests==0 and f.requests_made==0 and tr.calls==[]
    assessment=json.loads(c.execute('SELECT access_assessment FROM source_hints').fetchone()[0])
    assert assessment['status']=='denied' and assessment['reason']==reason


def test_declared_alias_is_denied(cfg):
    alias=U+'/'
    data=roster([surface(access='denied',equivalent_urls=[dict(alias_url=alias,alias_reason='fixture spelling')])])
    r,tr=run(cfg,[entry(alias)],data,pages={})
    assert r['source_requests']==0 and r['robots_requests']==0 and tr.calls==[]


def test_denial_is_not_host_wide(cfg):
    r,tr=run(cfg,[entry(V)],roster([surface(access='denied')]),pages={V:(200,V,HTML,ARTICLE)})
    assert r['fetched_ok']==1 and V in tr.calls


def test_aliases_do_not_change_evidence_identity(cfg):
    alias=U+'/'
    data=roster([surface(equivalent_urls=[dict(alias_url=alias,alias_reason='fixture spelling')])])
    r,_=run(cfg,[entry(U),entry(alias)],data,pages={u:(200,u,HTML,ARTICLE) for u in [U,alias]})
    c=db.connect(cfg.db_path)
    assert [x[0] for x in c.execute('SELECT url FROM evidence ORDER BY id')]==[U,alias]
    assert c.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==2
    assert registry.resolve(c,alias)['publisher_id'] is None


@pytest.mark.parametrize('cadence,expected',[(21600,6*H),(None,7*D)])
def test_cadence_respected_on_success(cfg,cadence,expected):
    run(cfg,[entry(U)],roster([surface(cadence=cadence)]))
    c=db.connect(cfg.db_path)
    assert c.execute('SELECT next_check_at FROM source_state').fetchone()[0]==schedule.iso(T0+expected)


@pytest.mark.parametrize('cadence',[60,2592001,True,21600.0])
def test_roster_rejects_out_of_range_cadence(cadence):
    c=store()
    with pytest.raises(ValueError): registry.project(c,roster([surface(cadence=cadence)]))
    assert c.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0]==0


def test_cadence_does_not_shorten_backoff(cfg):
    run(cfg,[entry(U)],roster(),pages={U:(500,U,HTML,'failure')})
    assert db.connect(cfg.db_path).execute('SELECT next_check_at FROM source_state').fetchone()[0]==schedule.iso(T0+H)


def test_cadence_does_not_revive_stalled(cfg):
    run(cfg,[entry(U)],roster())
    c=db.connect(cfg.db_path); c.execute('UPDATE source_state SET stalled=1')
    r,tr=run(cfg,data=roster(),now=T0+400*D,pages={})
    assert r['source_requests']==0 and schedule.due_urls(c,T0+400*D,10)==[] and tr.calls==[]


def retry_run(cfg,raw):
    clock=Clock(T0)
    tr=make_transport({U:(429,U,dict(HTML,**{'retry-after':raw}),'rate limit')})
    def slow(url,*args):
        value=tr(url,*args)
        if url==U: clock.at(T0+H)
        return value
    r,_=run(cfg,[entry(U)],roster(),now=clock,transport=slow)
    c=db.connect(cfg.db_path); return dict(c.execute('SELECT * FROM source_state').fetchone()),c,r


def test_sixty_day_retry_after_is_honoured(cfg):
    row,_,_=retry_run(cfg,'5184000')
    assert row['next_check_at']==schedule.iso(T0+H+60*D)


@pytest.mark.parametrize('raw',['999999999999999999999999999999999999999','Fri, 31 Dec 10000 23:59:59 GMT'])
def test_unrepresentable_retry_after_stalls_for_review(cfg,raw):
    row,c,_=retry_run(cfg,raw)
    assert row['stalled']==1 and raw in row['last_reason']
    assert schedule.due_urls(c,datetime.max.replace(tzinfo=timezone.utc),10)==[]


def test_retry_after_delta_is_a_floor(cfg):
    row,_,_=retry_run(cfg,'7200'); assert row['next_check_at']==schedule.iso(T0+3*H)


def test_retry_after_http_date_is_a_floor(cfg):
    row,_,_=retry_run(cfg,'Wed, 16 Sep 2026 00:00:00 GMT'); assert row['next_check_at']==schedule.iso(T0+D)


@pytest.mark.parametrize('raw',['nonsense','-3','','Mon, 14 Sep 2026 00:00:00 GMT'])
def test_unparseable_retry_after_falls_back(cfg,raw):
    row,_,_=retry_run(cfg,raw); assert row['next_check_at']==schedule.iso(T0+H)


def test_transport_exception_has_no_retry_after(cfg):
    def fail(url,*a):
        if url.endswith('/robots.txt'): return 200,url,{},b'User-agent: *\nAllow: /'
        raise TimeoutError('fixture')
    run(cfg,[entry(U)],roster(),transport=fail)
    row=db.connect(cfg.db_path).execute('SELECT * FROM source_state').fetchone()
    assert row['next_check_at']==schedule.iso(T0+H)


def test_unchanged_refetch_adds_no_candidate(cfg):
    run(cfg,[entry(U)],roster())
    r,_=run(cfg,now=T0+6*H)
    assert r['evidence_new']==0 and r['candidates_new']==0
    assert db.connect(cfg.db_path).execute('SELECT COUNT(*) FROM fetch_attempts').fetchone()[0]==2


def test_three_publishers_persist_evidence_and_schedule(cfg):
    urls=['https://fixture-%d.example/article'%i for i in range(3)]
    r,_=run(cfg,[entry(u) for u in urls],roster([surface(u,str(i)) for i,u in enumerate(urls)],
              [publisher(str(i)) for i in range(3)]),pages={u:(200,u,HTML,ARTICLE) for u in urls})
    assert r['publisher_evidence']['independent_publisher_count']==3
    for row in db.connect(cfg.db_path).execute('SELECT * FROM source_state'):
        assert row['last_success_at']==schedule.iso(T0) and row['next_check_at']==schedule.iso(T0+6*H)


def test_new_item_collected_on_next_allowed_poll(cfg):
    run(cfg,[entry(U)],roster())
    r,tr=run(cfg,now=T0+6*H-timedelta(seconds=1),pages={U:(200,U,HTML,ARTICLE_CHANGED)})
    assert r['source_requests']==0 and tr.calls==[]
    r,_=run(cfg,now=T0+6*H,pages={U:(200,U,HTML,ARTICLE_CHANGED)})
    rows=db.connect(cfg.db_path).execute('SELECT * FROM evidence ORDER BY id').fetchall()
    assert r['evidence_new']==1 and len(rows)==2 and rows[1]['version_no']==2 and rows[1]['supersedes_id']==rows[0]['id']


def test_failing_source_does_not_block_cycle(cfg):
    r,_=run(cfg,[entry(U),entry(V)],roster([surface(),surface(V)]),pages={U:(500,U,HTML,'no'),V:(200,V,HTML,ARTICLE)})
    assert r['source_requests']==2 and r['errors']==1 and r['fetched_ok']==1


def test_discovered_hint_is_not_a_roster_entry():
    c=store(); registry.project(c,roster()); before=registry.independent_publishers(c)
    discovery.record_hint(c,V,entry('https://fixture.example/'),schedule.iso(T0))
    assert registry.resolve(c,V)['publisher_id'] is None and registry.independent_publishers(c)==before


def test_model_output_cannot_add_a_surface(cfg):
    def malicious(text,meta):
        proposal=good_proposal(text,meta); proposal['source_url']='https://untrusted.example/article'; return proposal
    r,tr=run(cfg,[entry(U)],roster(),model=ModelClient('fixture',10,fixture_fn=malicious))
    c=db.connect(cfg.db_path)
    assert c.execute('SELECT COUNT(*) FROM source_hints').fetchone()[0]==1
    assert c.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0]==1
    assert [x for x in tr.calls if 'untrusted.example' in x]==[]


def test_reset_source_cannot_re_enable_denied_surface(cfg):
    run(cfg,[entry(U)],roster())
    run(cfg,data=roster([surface(access='denied')]))
    c=db.connect(cfg.db_path); schedule.reset_source(c,U,'agent:fixture','fixture reset',T0)
    assert schedule.due_urls(c,T0,10)==[U]
    r,tr=run(cfg,due_only=False)
    assert r['source_requests']==0 and r['robots_requests']==0 and tr.calls==[]


def test_registry_survives_reopen_and_replay(tmp_path):
    path=tmp_path/'db'; c=store(path); data=roster(); registry.project(c,data); before=snapshot(c); c.close()
    c=db.connect(path); registry.project(c,data); assert snapshot(c)==before


@pytest.mark.parametrize('parent',[False,True])
def test_two_surfaces_one_publisher_and_program_count_once(cfg,parent):
    data=roster([surface(),surface(V,'child' if parent else 'p')],[publisher()]+([publisher('child','p')] if parent else []))
    r,_=run(cfg,[entry(U),entry(V)],data,pages={u:(200,u,HTML,ARTICLE) for u in [U,V]})
    assert r['publisher_evidence']['independent_publisher_count']==1


def test_unattributed_surface_not_counted(cfg):
    r,_=run(cfg,[entry(U)],roster([surface(pid=None)]))
    assert r['publisher_evidence']==dict(independent_publisher_count=0,root_publisher_ids=[],unattributed_surfaces=[U])
    assert db.connect(cfg.db_path).execute('SELECT next_check_at FROM source_state').fetchone()[0]==schedule.iso(T0+7*D)


def test_omitted_existing_node_cycle_is_rejected_and_rolls_back_all_upserts():
    c=store(); registry.project(c,roster(pubs=[publisher('p','b'),publisher('b')]))
    before=snapshot(c); incoming=roster([surface()],pubs=[publisher('b','p')])
    incoming['surfaces'][0]['roster_reason']='changed'
    with pytest.raises(ValueError,match='cycle'): registry.project(c,incoming)
    assert snapshot(c)==before


def test_relationship_reversal_crash_leaves_old_graph():
    c=store(); registry.project(c,roster(pubs=[publisher('p','b'),publisher('b')]))
    before=snapshot(c)
    c.execute("CREATE TRIGGER crash_second BEFORE UPDATE ON publishers WHEN NEW.publisher_id='b' BEGIN SELECT RAISE(ABORT,'crash boundary'); END")
    with pytest.raises(sqlite3.IntegrityError): registry.project(c,roster(pubs=[publisher('p'),publisher('b','p')]))
    assert snapshot(c)==before


def test_parent_publisher_cycle_rejects_whole_roster():
    c=store()
    with pytest.raises(ValueError,match='cycle'): registry.project(c,roster(pubs=[publisher('p','b'),publisher('b','p')]))
    assert snapshot(c)==dict(publishers=[],source_surfaces=[],surface_aliases=[])


def test_unknown_publisher_rejects_whole_roster():
    c=store()
    with pytest.raises(sqlite3.IntegrityError): registry.project(c,roster([surface(pid='missing')]))
    assert snapshot(c)==dict(publishers=[],source_surfaces=[],surface_aliases=[])


def test_alias_cannot_also_be_a_surface():
    c=store(); registry.project(c,roster([surface(V)])); before=snapshot(c)
    with pytest.raises(ValueError): registry.project(c,roster([surface(equivalent_urls=[dict(alias_url=V,alias_reason='fixture')])]))
    assert snapshot(c)==before


@pytest.mark.parametrize('corrupt',[False,True])
def test_populated_then_missing_or_corrupt_retains_config(cfg,corrupt):
    run(cfg,[entry(U),entry(V)],roster([surface(access='denied'),surface(V)]),pages={V:(200,V,HTML,ARTICLE)})
    path=cfg.allowlist_path.parent/'roster.json'
    if corrupt: path.write_text('{bad')
    else: path.unlink()
    r,tr=run(cfg,now=T0+6*H,pages={V:(200,V,HTML,ARTICLE)})
    c=db.connect(cfg.db_path)
    assert c.execute('SELECT COUNT(*) FROM source_surfaces').fetchone()[0]==2
    assert U not in tr.calls and r['source_requests']==1
    assert c.execute('SELECT next_check_at FROM source_state WHERE url=?',(V,)).fetchone()[0]==schedule.iso(T0+12*H)
    assert 'last valid configuration retained' in r['roster']['reason']
    assert r['status']==('failed' if corrupt else 'ok')


def test_report_explains_checked_skipped_collected(cfg):
    denied=U+'/denied'; later=U+'/later'; stopped=U+'/stalled'
    sources=[entry(u) for u in [U,denied,later,stopped]]
    data=roster([surface(u,access='denied' if u==denied else 'permitted') for u in [U,denied,later,stopped]])
    run(cfg,sources,data,pages={u:(200,u,HTML,ARTICLE) for u in [U,later,stopped]})
    c=db.connect(cfg.db_path); c.execute('UPDATE source_state SET next_check_at=? WHERE url=?',(schedule.iso(T0),U))
    c.execute('UPDATE source_state SET stalled=1 WHERE url=?',(stopped,))
    r,_=run(cfg,pages={U:(200,U,HTML,ARTICLE)})
    decisions=r['source_decisions']; assert len(decisions)==4
    assert sorted(x['decision'] for x in decisions)==['checked','not_due','skipped','stalled']
    assert all(x['reason'] for x in decisions)
    report=cfg.report_path.read_text(); assert 'Latest cycle decisions' in report and 'registry: effective-denied' in report
    for item in decisions: assert item['url'] in report


def test_empty_registry_is_incumbent_behaviour(cfg):
    r,_=run(cfg,[entry(U)],data=None)
    c=db.connect(cfg.db_path)
    assert r['roster']['status']=='absent'
    assert c.execute('SELECT next_check_at FROM source_state').fetchone()[0]==schedule.iso(T0+7*D)
    assert schedule.select_cycle_urls(c,T0+7*D,10)['selected']==schedule.due_urls(c,T0+7*D,10)==[U]


def test_projection_process_death_retains_previous_graph(tmp_path):
    """Actual process death after the first relationship update, before the second/COMMIT."""
    import subprocess
    import sys
    path=tmp_path/'registry.sqlite'; c=store(path)
    registry.project(c,roster(pubs=[publisher('p','b'),publisher('b')]))
    before=snapshot(c); c.close()
    data=roster(pubs=[publisher('p'),publisher('b','p')]); payload=tmp_path/'incoming.json'; payload.write_text(json.dumps(data))
    script="""
import json,os,sys
from research import db,source_registry as registry
c=db.connect(sys.argv[1])
c.create_function('die_now',0,lambda:os._exit(91))
c.execute("CREATE TEMP TRIGGER die_after_first AFTER UPDATE ON publishers WHEN NEW.publisher_id='p' BEGIN SELECT die_now(); END")
registry.project(c,json.load(open(sys.argv[2])))
"""
    completed=subprocess.run([sys.executable,'-c',script,str(path),str(payload)],capture_output=True,text=True)
    assert completed.returncode==91,completed.stderr
    reopened=db.connect(path); assert snapshot(reopened)==before
    assert registry.resolve(reopened,U)['root_publisher_id']=='b'


def test_denial_survives_projection_process_death(tmp_path):
    import subprocess
    import sys
    path=tmp_path/'registry.sqlite'; c=store(path)
    registry.project(c,roster([surface(access='denied')]))
    c.close(); payload=tmp_path/'incoming.json'; payload.write_text(json.dumps(roster()))
    script="""
import json,os,sys
from research import db,source_registry as registry
c=db.connect(sys.argv[1]); c.create_function('die_now',0,lambda:os._exit(92))
c.execute("CREATE TEMP TRIGGER die_surface AFTER UPDATE ON source_surfaces BEGIN SELECT die_now(); END")
registry.project(c,json.load(open(sys.argv[2])))
"""
    completed=subprocess.run([sys.executable,'-c',script,str(path),str(payload)],capture_output=True,text=True)
    assert completed.returncode==92,completed.stderr
    c=db.connect(path); tr=make_transport({}); f=Fetcher(tr,deny_fn=lambda u:registry.effective_denied(c,u))
    assert f.fetch(U).outcome=='blocked' and f.requests_made==0 and f.robots_requests==0


def test_successful_relationship_reversal_is_atomic():
    c=store(); registry.project(c,roster(pubs=[publisher('p','b'),publisher('b')]))
    registry.project(c,roster(pubs=[publisher('p'),publisher('b','p')]))
    assert registry.resolve(c,U)['root_publisher_id']=='p'
    assert c.execute("SELECT parent_publisher FROM publishers WHERE publisher_id='b'").fetchone()[0]=='p'


def test_parent_chain_depth_rejects_whole_projection():
    c=store(); pubs=[publisher(str(i),str(i+1) if i<5 else None) for i in range(6)]
    with pytest.raises(ValueError,match='deeper than 4'): registry.project(c,roster([surface(pid='0')],pubs))
    assert snapshot(c)==dict(publishers=[],source_surfaces=[],surface_aliases=[])


def test_roster_only_surface_is_not_scheduled(cfg):
    r,tr=run(cfg,[],roster())
    c=db.connect(cfg.db_path)
    assert c.execute('SELECT COUNT(*) FROM source_hints').fetchone()[0]==0
    assert c.execute('SELECT COUNT(*) FROM source_state').fetchone()[0]==0
    assert registry.independent_publishers(c)['independent_publisher_count']==0
    assert tr.calls==[]


def test_fetch_result_received_at_and_retry_after_keep_response_clock():
    clock=Clock(T0); base=make_transport({U:(429,U,{'retry-after':'7200'},'limit')})
    def transport(url,*args):
        value=base(url,*args)
        if url==U: clock.at(T0+H)
        return value
    result=Fetcher(transport,clock=clock).fetch(U)
    assert result.attempted_at==schedule.iso(T0)
    assert result.received_at==schedule.iso(T0+H)
    assert result.retry_after_deadline==T0+3*H


def test_direct_permit_policy_hook_never_spends_robots():
    c=store(); registry.project(c,roster([surface(access='denied')]))
    tr=make_transport({}); f=Fetcher(tr,deny_fn=lambda u:registry.effective_denied(c,u))
    allowed,_,reason=f.permit(U,U)
    assert allowed is False and f.robots_requests==0 and tr.calls==[]
    assert 'registry: effective-denied' in reason


def test_evidence_and_cadence_rollback_together_before_commit(cfg):
    c=store(cfg.db_path)
    c.execute("CREATE TRIGGER fail_schedule BEFORE UPDATE ON source_state BEGIN SELECT RAISE(ABORT,'fixture commit boundary'); END")
    c.close()
    r,_=run(cfg,[entry(U)],roster())
    c=db.connect(cfg.db_path)
    assert r['status']=='failed'
    assert c.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==0
    assert c.execute('SELECT attempts FROM source_state').fetchone()[0]==0
    c.execute('DROP TRIGGER fail_schedule'); c.close()
    r,_=run(cfg)
    c=db.connect(cfg.db_path)
    assert r['evidence_new']==1 and c.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==1
    assert c.execute('SELECT next_check_at FROM source_state').fetchone()[0]==schedule.iso(T0+6*H)


def test_nullable_official_url_program_projects_and_counts_under_parent(cfg):
    parent=publisher('busy_toddler')
    program=publisher('playing_preschool','busy_toddler'); program['official_url']=None
    data=roster([surface(U,'busy_toddler'),surface(V,'playing_preschool')],[parent,program])
    result,_=run(cfg,[entry(U),entry(V)],data,pages={u:(200,u,HTML,ARTICLE) for u in [U,V]})
    assert result['status']=='ok'
    conn=db.connect(cfg.db_path)
    assert conn.execute("SELECT official_url FROM publishers WHERE publisher_id='playing_preschool'").fetchone()[0] is None
    assert registry.resolve(conn,V)['root_publisher_id']=='busy_toddler'
    assert result['publisher_evidence']['independent_publisher_count']==1


def test_committed_coverage_amendment_projects_exact_policies():
    """The reviewed coverage amendment expands collection without weakening no-crawl denials."""
    root=Path(__file__).resolve().parent.parent
    data=json.loads((root/'sources'/'roster.json').read_text()); conn=store(); summary=registry.project(conn,data)
    assert summary['historical_seed_count']==25 and summary['publisher_count']==14 and summary['surface_count']==22
    assert summary['working_set']==[
        NHLBI_PITA, NHLBI_RICE,
        'https://cookieandkate.com/', 'https://www.loveandlemons.com/',
        'https://www.goodhousekeeping.com/home/cleaning/', 'https://busytoddler.com/',
        'https://dayswithgrey.com/',
        'https://www.goodhousekeeping.com/home/cleaning/a71856702/how-to-clean-air-fryer-basket/',
        'https://www.goodhousekeeping.com/home/cleaning/a37462/how-often-you-should-clean-everything/',
        'https://www.cdc.gov/food-safety/prevention/index.html']
    assert registry.resolve(conn,'https://busytoddler.com/')['root_publisher_id']=='busy_toddler'
    assert conn.execute("SELECT official_url FROM publishers WHERE publisher_id='playing_preschool'").fetchone()[0] is None
    roots={registry.resolve(conn,url)['root_publisher_id'] for url in summary['working_set']}
    assert roots=={'nhlbi','cookie_and_kate','love_and_lemons','good_housekeeping','busy_toddler','days_with_grey','cdc'}
    withheld=['https://www.budgetbytes.com/','https://www.budgetbytes.com/poor-mans-burrito-bowls/',
              'https://www.mothercould.com/','https://www.thelazygeniuscollective.com/']
    assert all(registry.effective_denied(conn,url) is not None for url in withheld)
    assert set(withheld).isdisjoint(summary['working_set'])
    assert registry.effective_denied(conn,'https://busytoddler.com/') is None
    assert registry.effective_denied(conn,'https://dayswithgrey.com/') is None
    mother=conn.execute("SELECT access_status,roster_status,access_basis FROM source_surfaces WHERE url='https://www.mothercould.com/'").fetchone()
    assert tuple(mother[:2])==('denied','defer') and 'NO-CRAWL' in mother['access_basis']
    assert conn.execute('SELECT COUNT(*) FROM source_hints').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM source_state').fetchone()[0]==0

    allow=worker.load_allowlist(root/'sources'/'allowlist.json')
    assert len(allow)==18 and sum(entry['fetch'] is True for entry in allow)==13
    assert len({entry['url'] for entry in allow})==18
    by_url={entry['url']:entry for entry in allow}
    added={'https://cookieandkate.com/','https://www.loveandlemons.com/',
           'https://busytoddler.com/','https://dayswithgrey.com/'}
    assert added <= by_url.keys()
    assert all(by_url[url]['fetch'] is True for url in added-{'https://cookieandkate.com/'})
    assert by_url['https://cookieandkate.com/']['fetch'] is False
    assert 'INTEGRATION HOLD:' in by_url['https://cookieandkate.com/']['usage_constraints']
    for url in ('https://www.budgetbytes.com/poor-mans-burrito-bowls/',
                'https://www.loveandlemons.com/black-bean-soup/'):
        assert by_url[url]['fetch'] is False
        assert 'historical_internal_corpus_only' in by_url[url]['access_basis']
    assert all('COLLECTION:' in by_url[url]['usage_constraints'] and
               ('REUSE RESTRICTED' in by_url[url]['usage_constraints'] or 'REUSE:' in by_url[url]['usage_constraints'])
               for url in added)
    assert 'https://www.budgetbytes.com/' not in by_url
    assert 'https://www.mothercould.com/' not in by_url


NHLBI_PITA='https://www.nhlbi.nih.gov/health/heart-healthy-living/healthy-foods/healthy-eating-recipes/pita-pizzas'
NHLBI_RICE='https://www.nhlbi.nih.gov/health/heart-healthy-living/healthy-foods/healthy-eating-recipes/wiki-fast-rice'


def test_nhlbi_recipes_prepared_first_under_one_canonical_publisher(cfg):
    """Two recorded NHLBI recipe surfaces project under one root, come first in the working set and
    allowlist, keep cadence null (seven-day fallback), carry text-only constraints with agent provenance,
    and change nothing about the withheld sources. No request is made; the store is temporary."""
    root=Path(__file__).resolve().parent.parent
    data=json.loads((root/'sources'/'roster.json').read_text()); conn=store(cfg.db_path); summary=registry.project(conn,data)
    assert summary['working_set'][:2]==[NHLBI_PITA,NHLBI_RICE] and len(summary['working_set'])==10
    assert [p['publisher_id'] for p in data['publishers']].count('nhlbi')==1
    assert [s['url'] for s in data['surfaces'][:2]]==[NHLBI_PITA,NHLBI_RICE]
    assert [s['url'] for s in data['surfaces'] if s['publisher_id']=='nhlbi']==[NHLBI_PITA,NHLBI_RICE]
    for url in (NHLBI_PITA,NHLBI_RICE):
        identity=registry.resolve(conn,url)
        assert identity==dict(publisher_id='nhlbi',root_publisher_id='nhlbi',cadence_seconds=None)
        assert registry.effective_denied(conn,url) is None
        row=conn.execute('SELECT * FROM source_surfaces WHERE url=?',(url,)).fetchone()
        assert (row['surface_kind'],row['roster_status'],row['access_status'])==('site_article','retain','permitted')
        assert json.loads(row['topics'])==['recipe_supply']
        assert row['assessed_by'].startswith('agent:') and not row['assessed_by'].startswith('human:')
        assert 'seven-day fallback' in row['cadence_reason'] and 'public domain' in row['access_basis']
        assert 'not editorial approval' in row['access_basis']
    assert conn.execute("SELECT parent_publisher FROM publishers WHERE publisher_id='nhlbi'").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM surface_aliases WHERE url IN (?,?)",(NHLBI_PITA,NHLBI_RICE)).fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM source_hints').fetchone()[0]==0
    assert conn.execute('SELECT COUNT(*) FROM source_state').fetchone()[0]==0
    # Denials recorded before this amendment are untouched.
    for url in ['https://www.budgetbytes.com/','https://www.mothercould.com/','https://www.thelazygeniuscollective.com/',
                'https://www.cleanmama.com/','https://www.instagram.com/thebuyguide/']:
        assert registry.effective_denied(conn,url) is not None

    allow=worker.load_allowlist(root/'sources'/'allowlist.json')
    assert [e['url'] for e in allow[:2]]==[NHLBI_PITA,NHLBI_RICE]
    credit='Source: National Heart, Lung, and Blood Institute; National Institutes of Health; U.S. Department of Health and Human Services.'
    for e in allow[:2]:
        assert e['fetch'] is True and e['source_type']=='government'
        assert e['attribution']=='National Heart, Lung, and Blood Institute; National Institutes of Health; U.S. Department of Health and Human Services'
        assert credit in e['usage_constraints']
        for marker in ('COLLECTION:','TEXT RETENTION AND LOCAL INFERENCE:','EXCLUSIONS:','EDITORIAL APPROVAL: none',
                       'no photos','logos','endorsement','do not derive one'):
            assert marker in e['usage_constraints'],marker
        assert 'agent:claude-wel49-nhlbi-config' in e['discovery_origin'] and 'human:' not in e['discovery_origin']
    # A manual run attempts allowlist order under the hard cap, so both recipes sit inside the first ten grants.
    manual=[e['url'] for e in allow if e['fetch'] is True and registry.effective_denied(conn,e['url']) is None]
    assert manual[:2]==[NHLBI_PITA,NHLBI_RICE] and len(manual)>=config.MAX_URLS_HARD_CAP
    assert {NHLBI_PITA,NHLBI_RICE} <= set(manual[:cfg.max_urls]) and cfg.max_urls==config.MAX_URLS_HARD_CAP
