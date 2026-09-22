"""Bounded first-party transport receipts; no model, publication, or live database.

Run from the repository with PYTHONPATH=. and a new --output directory.
Raw responses are local audit artifacts, not committed or displayed recipe products.
"""
import argparse
import hashlib
import json
from pathlib import Path

from research.config import USER_AGENT
from research.extract import extract
from research.fetch import Fetcher, urllib_transport

PAGES = ('Kid-Friendly_Pasta', 'Chicken_Fajitas', 'Tuna_Casserole')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipts = []

    def record(url, user_agent, timeout, max_bytes):
        result = urllib_transport(url, user_agent, timeout, max_bytes)
        status, final_url, headers, body = result
        name = hashlib.sha256(url.encode()).hexdigest()
        (args.output / (name + '.body')).write_bytes(body)
        receipts.append(dict(url=url, status=status, final_url=final_url, headers=headers,
                             body_file=name + '.body', sha256=hashlib.sha256(body).hexdigest()))
        return result

    fetcher = Fetcher(transport=record, user_agent=USER_AGENT)
    observations = []
    for page in PAGES:
        result = fetcher.fetch('https://en.wikibooks.org/wiki/Cookbook:' + page)
        row = {key: value for key, value in vars(result).items() if key not in ('html', 'headers')}
        if result.html:
            evidence = extract(result.html)
            (args.output / (page + '.txt')).write_text(evidence.text)
            row.update(title=evidence.title, content_hash=evidence.content_hash,
                       text_chars=len(evidence.text), manifest=evidence.locators)
        observations.append(row)
        if result.http_status in (403, 429) or result.outcome == 'blocked':
            break
    report = dict(user_agent=USER_AGENT, receipts=receipts, observations=observations,
                  source_requests=fetcher.requests_made, robots_requests=fetcher.robots_requests)
    (args.output / 'receipts.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'receipts'}, indent=2))


if __name__ == '__main__':
    main()
