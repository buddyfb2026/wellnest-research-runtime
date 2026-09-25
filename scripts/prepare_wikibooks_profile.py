"""Prepare three qualified Wikibooks pages for the existing worker; never install or run.

Keep the existing roster history and denials. Only these three exact URLs receive
collection grants in the generated allowlist. Output must be a new directory.
"""
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSE = 'https://creativecommons.org/licenses/by-sa/4.0/'
TERMS = 'https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content'
ASSESSED_AT = '2026-09-21T19:38:55Z'
PAGES = ('Kid-Friendly_Pasta', 'Chicken_Fajitas', 'Tuna_Casserole')
URLS = tuple('https://en.wikibooks.org/wiki/Cookbook:' + page for page in PAGES)
PUBLISHER = 'wikibooks_cookbook'
BASIS = (
    'First-party page footer and Wikimedia Terms of Use section 7: recipe text under CC BY-SA 4.0. '
    'Product Fetcher observed HTTP 200, robots allowed, one hop for each exact URL '
    '2026-09-21T19:38:54Z–19:38:55Z. Identified contact-bearing user agent. '
    'Recipe text only; no image grant. Source qualification, not editorial approval. '
    'Receipts: docs/WEL-49-wikibooks-pilot.md.'
)


def attribution(url):
    # This existing field is copied verbatim into evidence, recipe documents and
    # recipe-pack documents; do not hide required license notices in notes alone.
    return ('Wikibooks Cookbook contributors; source and contributor history: ' + url +
            '; CC BY-SA 4.0: ' + LICENSE +
            '; Changes: recipe fields extracted and formatting/units normalized by WellNest. '
            'Adapted recipe text is provided under CC BY-SA 4.0. Images excluded.')


def build_profile():
    roster = copy.deepcopy(json.loads((ROOT / 'sources/roster.json').read_text()))
    assert not any(p['publisher_id'] == PUBLISHER for p in roster['publishers'])
    assert not any(s['url'] in URLS for s in roster['surfaces'])
    roster['publishers'].append({
        'publisher_id': PUBLISHER, 'canonical_name': 'Wikibooks Cookbook contributors',
        'official_url': 'https://en.wikibooks.org/wiki/Cookbook:Recipes', 'parent_publisher': None,
        'identity_basis': 'English Wikibooks Cookbook, hosted by Wikimedia Foundation. '
                          'Three recipe pages are one publisher, not three independent sources.',
        'assessed_at': ASSESSED_AT, 'assessed_by': 'agent:codex-wel49-wikibooks',
    })
    sources = []
    for url in URLS:
        sources.append({
            'url': url, 'source_type': 'recipe_site', 'attribution': attribution(url),
            'access_basis': BASIS, 'fetch': True,
            'usage_constraints': 'COLLECTION, TEXT RETENTION AND LOCAL INFERENCE: permitted for this '
                'exact page. CC BY-SA 4.0 source text; preserve the entire attribution notice, '
                'source URL, license URL and change notice on every displayed copy. License adapted '
                'recipe text under CC BY-SA 4.0; inspect any future page-level imported-content notice '
                'before reuse. EXCLUSIONS: no images, logos or endorsement. EDITORIAL APPROVAL: none; '
                'pending research only. Do not publish automatically or infer popularity, parent '
                'endorsement, nutrition, safe temperatures, quantities, servings or missing times. '
                'Terms receipt: ' + TERMS,
            'discovery_origin': 'WEL-49 bounded first-party Wikibooks dinner pilot; '
                'Kid-friendly category and Easy Dinners index; agent:codex-wel49-wikibooks',
        })
        roster['surfaces'].append({
            'url': url, 'publisher_id': PUBLISHER, 'surface_kind': 'site_article',
            'topics': ['recipe_supply'], 'roster_status': 'retain',
            'roster_reason': 'Practical dinner-shaped recipe input selected from first-party Cookbook '
                'indexes; no popularity, testing by parents, or editorial approval claimed. '
                'Baseline locator v6 produces no recipe for the Procedure heading layout; '
                'candidate yield requires the separately reviewed locator correction.',
            'access_status': 'permitted', 'access_basis': BASIS,
            'assessed_at': ASSESSED_AT, 'assessed_by': 'agent:codex-wel49-wikibooks',
            'cadence_seconds': None, 'cadence_reason': 'One observation does not establish cadence.',
            'equivalent_urls': [],
        })
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
