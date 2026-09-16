"""Offline integration of the reviewed recipe and source-registry paths."""
import json

import pytest

from research import db, evidence, source_registry as registry, worker
from research.config import Config
from research.extract import extract
from research.model import ModelClient
from research.recipe_schema import cooking_content_usable
from tests.conftest import entry, good_proposal, make_transport, write_allowlist
from tests.test_wel49 import T0, publisher, roster, surface, write_roster


@pytest.mark.parametrize('prior_version', [0, 4, 5])
def test_combined_fresh_and_upgrade_preserve_history(tmp_path, monkeypatch, prior_version):
    path=tmp_path/'upgrade.sqlite'
    conn=db.connect(path)
    before=None
    if prior_version:
        with monkeypatch.context() as old:
            old.setattr(db, 'MIGRATIONS', [item for item in db.MIGRATIONS if item[0]<=prior_version])
            assert db.migrate(conn)==prior_version
        evidence.upsert_source_hint(conn,entry('https://fixture.example/legacy',fetch=False))
        conn.execute("INSERT INTO evidence(url,content_kind,content_hash,version_no,fetched_at,"
                     "published_at_basis,source_type,access_basis,excerpt,text_chars) "
                     "VALUES('https://fixture.example/legacy','fixture','legacy-hash',1,'2026-01-01',"
                     "'unknown','publication','fixture','Legacy text',11)")
        conn.execute("INSERT INTO evidence_text(evidence_id,text) VALUES(1,'Legacy text')")
        before={table:[tuple(row) for row in conn.execute('SELECT * FROM '+table)]
                for table in ('source_hints','evidence','evidence_text')}
    assert [v for v,_ in db.MIGRATIONS]==[1,2,3,4,5,6,7]
    assert db.migrate(conn)==7
    assert [row[0] for row in conn.execute('SELECT version FROM schema_version ORDER BY version')]==[1,2,3,4,5,6,7]
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'recipes','recipe_versions','locator_manifests','evidence_current_manifest',
            'publishers','source_surfaces','surface_aliases'}<=tables
    assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert db.migrate(conn)==7
    conn.close()
    conn=db.connect(path)
    assert db.migrate(conn)==7
    if before:
        assert before=={table:[tuple(row) for row in conn.execute('SELECT * FROM '+table)] for table in before}
    conn.close()


@pytest.mark.parametrize('due_only', [False, True])
def test_recipe_worker_and_registry_coexist_with_durable_replay(tmp_path,due_only):
    allowed='https://fixture.example/bean-supper'
    denied='https://denied.example/meal'
    html=('<html><head><title>Bean Supper</title></head><body><article>'
          '<h1>Bean Supper</h1><p>'+'context '*40+'</p>'
          '<h2>Ingredients</h2><p>1 cup\u00a0cooked beans</p><p>1 tsp oil</p>'
          '<h2>Directions</h2><ol><li>Warm the beans in oil.</li><li>Serve immediately.</li></ol>'
          '<h2>Prep Time</h2><p>5 minutes</p><h2>Cook Time</h2><p>10 minutes</p>'
          '<h2>Total Time</h2><p>15 minutes</p><h2>Yields</h2><p>4 servings</p>'
          '</article></body></html>')
    ex=extract(html)
    cfg=Config(db_path=tmp_path/'combined.sqlite',
               allowlist_path=write_allowlist(tmp_path,[entry(denied),entry(allowed)]),
               report_path=tmp_path/'report.md',provider='ollama',recipe_extraction_enabled=True)
    write_roster(cfg,roster([surface(denied,'p',access='denied'),surface(allowed,'p')],[publisher('p')]))
    response={'name':'Bean Supper','ingredients':['1 cup cooked beans','1 tsp oil'],
              'steps':['Warm the beans in oil.','Serve immediately.'],
              'servings':{'value':4,'quote':'4 servings'},
              'prep_minutes':{'value':5,'quote':'5 minutes'},
              'cook_minutes':{'value':10,'quote':'10 minutes'},
              'total_minutes':{'value':15,'quote':'15 minutes'},'unknowns':[]}
    posts=[]
    def post(url,payload,timeout):
        meta=json.loads(payload['prompt'].split('\n\n',1)[0].split(': ',1)[1])
        posts.append(meta)
        return {'response':json.dumps(response if 'recipe_extraction' in meta else good_proposal(ex.text,meta))}
    pages={allowed:(200,allowed,{'content-type':'text/html'},html)}
    transport=make_transport(pages)
    result=worker.run(cfg,transport=transport,model=ModelClient('ollama',10,model='stub',http_post=post),
                      content_kind='fixture',clock=lambda:T0,due_only=due_only)
    assert result.ok and result['recipe_versions_new']==1 and result['registry_denied']==1
    assert result['publisher_evidence']['independent_publisher_count']==1
    assert not any('denied.example' in url for url in transport.calls)
    conn=db.connect(cfg.db_path)
    row=dict(conn.execute('SELECT * FROM recipe_versions').fetchone())
    doc=json.loads(row['content'])
    assert cooking_content_usable(doc) and row['completeness']=='complete'
    assert doc['ingredients'][0]['source']['value']=='1 cup\u00a0cooked beans'
    assert (len(doc['ingredients']),len(doc['steps']))==(2,2)
    assert [doc['times'][r]['value'] for r in ('prep_time','cook_time','total_time')]==[5,10,15]
    assert row['state']=='pending' and row['publishable']==0
    assert registry.resolve(conn,allowed)['root_publisher_id']=='p'
    counts=lambda c:tuple(c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                          for t in ('evidence','recipe_versions','inference_calls','publishers'))
    before=counts(conn)
    assert before==(1,1,2,1) and len(posts)==2
    conn.close()
    again=worker.run(cfg,transport=make_transport(pages),
                     model=ModelClient('ollama',10,model='stub',http_post=post),
                     content_kind='fixture',clock=lambda:T0,due_only=due_only)
    assert again.ok
    conn=db.connect(cfg.db_path)
    assert counts(conn)==before and len(posts)==2
    assert dict(conn.execute('SELECT * FROM recipe_versions').fetchone())==row
    conn.close()
