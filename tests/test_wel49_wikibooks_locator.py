"""Real retained first-party HTML and adversarial closed-boundary regressions."""
import hashlib
import json
from pathlib import Path

import pytest

from research import recipe_locate as locator
from research.extract import extract

FIXTURES = Path(__file__).parent / 'fixtures/wel49_wikibooks'
PROVENANCE = json.loads((FIXTURES / 'PROVENANCE.json').read_text())
PAGES = PROVENANCE['pages']


def _retained(page):
    return ((FIXTURES / (page['url_hash'] + '.body')).read_bytes(),
            (FIXTURES / (page['page'] + '.txt')).read_bytes())


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p['page'])
def test_fixture_integrity_and_unchanged_retained_text(page):
    body, text = _retained(page)
    assert hashlib.sha256(page['url'].encode()).hexdigest() == page['url_hash']
    assert hashlib.sha256(body).hexdigest() == page['body_hash']
    assert page['body_hash'] != page['url_hash']
    assert hashlib.sha256(text).hexdigest() == page['text_hash']
    extracted = extract(body.decode('utf-8'))
    assert extracted.text.encode('utf-8') == text
    assert extracted.content_hash == page['text_hash']


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p['page'])
def test_v6_step_heading_pair_locates_zero_recipes(page, monkeypatch):
    body, _ = _retained(page)
    monkeypatch.setattr(locator, 'STEP_HEADINGS', ('instructions', 'directions'))
    assert extract(body.decode('utf-8')).locators['recipes'] == []


@pytest.mark.parametrize('page', PAGES, ids=lambda p: p['page'])
def test_corrected_exact_inventory_names_spans_exclusions_and_scalar_unknowns(page):
    body, retained = _retained(page)
    text = retained.decode('utf-8')
    manifest = extract(body.decode('utf-8')).locators
    assert manifest['locator_version'] == 'wel48_locator_v7'
    assert len(manifest['recipes']) == 1
    recipe = manifest['recipes'][0]
    assert recipe['tier'] == 'heading'
    # Independent literal oracle from the retained section lines, not locator output.
    expected_ingredients = text.split('\nIngredients\n[edit | edit source]\n', 1)[1].split('\nProcedure\n', 1)[0].splitlines()
    expected_steps = text.split('\nProcedure\n[edit | edit source]\n', 1)[1]
    expected_steps = expected_steps.split('\nNotes, tips, and variations\n', 1)[0]
    expected_steps = expected_steps.split('\nRetrieved from "', 1)[0].splitlines()
    assert len(expected_ingredients) == page['ingredients']
    assert len(expected_steps) == page['steps']
    for field, expected in [('ingredient_units', expected_ingredients), ('step_units', expected_steps)]:
        actual = [text[u['start']:u['end']] for u in recipe[field]]
        assert actual == expected
        for unit, literal in zip(recipe[field], expected):
            assert 0 <= unit['start'] < unit['end'] <= len(text)
            assert recipe['bounds']['start'] <= unit['start'] < unit['end'] <= recipe['bounds']['end']
            assert literal == literal.strip()
            assert literal != '[edit | edit source]'
            assert not literal.startswith(('Retrieved from', 'Categories:', 'Search', 'Cookbook:'))
            assert literal not in ('Add languages', 'Add topic')
    name = page['page'].replace('_', ' ')
    span = recipe['name']
    assert text[span['start']:span['end']] == name
    assert 0 < span['start'] < span['end'] <= len(text)
    assert text[span['start'] - 1] == '\n'
    assert recipe['slot'] == 'name:' + hashlib.sha256(name.casefold().encode()).hexdigest()[:16]
    assert recipe['slot_disambiguated'] == 0
    assert recipe['bounds']['end'] == recipe['step_units'][-1]['end']
    assert recipe['roles'] == {}


def _steps(steps, title='Soup', heading='Instructions'):
    text = title + '\nIngredients\n1 cup water\n' + heading + '\n' + '\n'.join(steps)
    recipe = locator.locate('', text, title)['recipes'][0]
    return [text[u['start']:u['end']] for u in recipe['step_units']]


def test_procedure_inside_prose_is_not_a_heading():
    steps = ['Follow the same procedure for the second batch.', 'Serve.']
    assert _steps(steps) == steps


def test_first_step_heading_still_wins_without_mediawiki_boundary_marker():
    steps = ['Stir.', 'Procedure', 'Serve.']
    assert _steps(steps) == steps


def test_exact_edit_control_only_and_no_prose_lookahead_truncation():
    steps = ['Stir the soup.', '[edit | edit source]', 'Simmer until soft.',
             'Press [edit | edit source] to change the label.', '[Edit | Edit Source]', 'Serve.']
    assert _steps(steps) == [s for s in steps if s != '[edit | edit source]']


def test_footer_like_cooking_prose_stays_and_exact_footer_ends():
    steps = ['Retrieved from the oven, rest the casserole for 5 minutes.',
             'Categories: choose mild or hot salsa.', 'Serve.']
    assert _steps(steps + ['Retrieved from "https://example.test/recipe"', 'Search']) == steps


@pytest.mark.parametrize('label', ['Ingredients', 'Instructions', 'Directions', 'Procedure', 'Notes, tips, and variations'])
def test_closed_mediawiki_heading_requires_edit_control(label):
    assert _steps(['Stir.', label, '[edit | edit source]', 'Non-recipe tail.']) == ['Stir.']


def test_notes_variations_without_edit_marker_is_not_new_boundary():
    steps = ['Stir.', 'Notes, tips, and variations', 'Serve.']
    assert _steps(steps) == steps


@pytest.mark.parametrize('name_lines', ['X\nX', 'Longer X line'])
def test_wikibooks_name_requires_unique_whole_line(name_lines):
    title = 'Cookbook:X - Wikibooks, open books for an open world'
    text = title + '\n' + name_lines + '\nIngredients\n1 cup water\nProcedure\nBoil.'
    recipe = locator.locate('', text, title)['recipes'][0]
    assert recipe['name']['start'] == -1
    assert recipe['slot'] is None


def test_non_wikibooks_title_keeps_incumbent_grounding():
    title = 'Cookbook: Soup | Fixture'
    text = title + '\nIngredients\n1 cup water\nDirections\nBoil.'
    recipe = locator.locate('', text, title)['recipes'][0]
    assert recipe['name']['start'] == 0
    assert recipe['name']['end'] == len(title)


def test_procedure_markup_keeps_existing_tip_membership_rule():
    html = '<h2>Procedure</h2><ol><li>Boil.</li><li>Tip: Stir.</li></ol>'
    text = 'Soup\nIngredients\n1 cup water\nProcedure\nBoil.\nTip: Stir.\nNotes\nTail'
    recipe = locator.locate(html, text, 'Soup')['recipes'][0]
    assert [text[u['start']:u['end']] for u in recipe['step_units']] == ['Boil.', 'Tip: Stir.']
