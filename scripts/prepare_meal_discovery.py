"""Prepare the existing worker's meal discovery configuration; never install or run it.

Uses the incumbent allowlist/roster contracts. Output must be a new directory, so an
operator cannot accidentally overwrite the running pilot configuration.
"""
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = 'https://publicdomainrecipes.com/'
EXISTING = (
    'https://fossrecipes.com/recipes/orzo-chicken',
    'https://publicdomainrecipes.com/easy-chicken-and-rice-casserole/',
)
BASIS = (
    'First-party site states all recipes are public domain and its project uses the Unlicense. '
    'Index inspected 2026-09-16 through the product Fetcher: HTTP 200, robots allowed. '
    'The existing bounded same-origin discovery and per-link robots assessment apply. '
    'Recipe text retention and local processing only; not editorial approval.'
)


def build_profile():
    roster = copy.deepcopy(json.loads((ROOT / 'sources/roster.json').read_text()))
    source_rows = json.loads((ROOT / 'sources/allowlist.json').read_text())['sources']
    sources = [copy.deepcopy(s) for s in source_rows if s['url'] in EXISTING]
    assert {s['url'] for s in sources} == set(EXISTING)
    sources.append({
        'url': ROUTE, 'role': 'discovery_route', 'source_type': 'publication',
        'attribution': 'Public Domain Recipes; individual contributor credit remains in source evidence',
        'access_basis': BASIS, 'fetch': True,
        'usage_constraints': 'Recipe TEXT only. No photos, logos or donation links. '
                             'Keep source/contributor credit. No affiliate activation. '
                             'All extracted recipes remain pending; no automatic publication.',
        'discovery_origin': 'WEL-49: publisher-owned newest-recipes index',
    })
    assert not any(s['url'] == ROUTE for s in roster['surfaces'])
    roster['surfaces'].append({
        'url': ROUTE, 'publisher_id': 'public_domain_recipes', 'surface_kind': 'site_index',
        'topics': ['recipe_supply'], 'roster_status': 'retain',
        'roster_reason': 'Discover the newest linked recipes rather than repeatedly checking only one saved recipe.',
        'access_status': 'permitted', 'access_basis': BASIS,
        'assessed_at': '2026-09-16T23:25:00Z', 'assessed_by': 'agent:codex-wel49',
        'cadence_seconds': 86400,
        'cadence_reason': 'Operator-selected daily index check, not a claim of daily publisher activity. '
                          'Discovered recipe refresh retains the existing weekly default.',
        'equivalent_urls': [],
    })
    # Historical sources and denials are retained for provenance, not enabled for collection.
    return {'sources': sources}, roster


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    allowlist, roster = build_profile()
    from research.source_registry import validate
    validate(roster)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in [('allowlist.json', allowlist), ('roster.json', roster)]:
        (args.output / name).write_text(json.dumps(value, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
