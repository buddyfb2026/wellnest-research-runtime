"""Measure retained Wikibooks response replay in a NEW isolated database.

Source transport is offline: only the exact successful captured responses are replayed.
--model opts into at most three real local Ollama calls; omission makes zero calls.
This never publishes, touches a live store, or downloads a source again.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from research import db, recipe_schema, worker
from research.config import Config
from prepare_wikibooks_profile import build_profile, URLS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model')
    args = parser.parse_args()
    captured = json.loads((args.receipts / 'receipts.json').read_text())
    observations = {r['url']: r for r in captured['observations']}
    assert set(observations) == set(URLS)
    assert all(r['outcome'] == 'ok' and r['robots_status'] == 'allowed'
               and r['http_status'] == 200 for r in observations.values())
    responses = {}
    for receipt in captured['receipts']:
        raw = (args.receipts / receipt['body_file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == receipt['sha256']
        responses[receipt['url']] = (receipt['status'], receipt['final_url'], receipt['headers'], raw)
    args.output.mkdir(parents=True, exist_ok=False)
    allowlist, roster = build_profile()
    for name, value in [('allowlist.json', allowlist), ('roster.json', roster)]:
        (args.output / name).write_text(json.dumps(value, indent=2) + '\n')
    cfg = Config(db_path=args.output / 'research.sqlite', allowlist_path=args.output / 'allowlist.json',
                 report_path=args.output / 'worker-report.md', provider='ollama' if args.model else 'none',
                 ollama_model=args.model or '', max_urls=3, max_inference=3 if args.model else 0,
                 max_inference_per_day=3, recipe_extraction_enabled=True, meals_first=True)
    requests = []

    def retained_transport(url, *unused):
        requests.append(url)
        return responses[url]  # unknown URLs fail; no network fallback

    start = time.monotonic()
    result = worker.run(cfg, transport=retained_transport)
    conn = db.connect(cfg.db_path)
    versions = []
    for row in conn.execute('SELECT id,evidence_id,state,publishable,completeness,content FROM recipe_versions ORDER BY id'):
        value = dict(row)
        document = json.loads(value.pop('content'))
        value['schema_errors'] = recipe_schema.validate(document)
        value['cooking_content_usable'] = recipe_schema.cooking_content_usable(document)
        value['unknown_fields'] = document.get('unknown_fields')
        versions.append(value)
    report = dict(source_mode='offline replay of captured real first-party HTTP responses; no source requests',
                  captured_at=[r['attempted_at'] for r in captured['observations']],
                  elapsed_seconds=round(time.monotonic() - start, 3), model=args.model,
                  worker=dict(result), replay_requests=requests, versions=versions,
                  recipe_count=len(versions), usable_recipe_count=sum(v['cooking_content_usable'] for v in versions),
                  complete_recipe_count=sum(v['completeness'] == 'complete' for v in versions),
                  publications=conn.execute('SELECT COUNT(*) FROM recipe_publications').fetchone()[0])
    conn.close()
    (args.output / 'yield.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
