"""Generic proposal requests must explicitly request final JSON without thinking.

The worker and persisted ledger are real; only the Ollama HTTP boundary is stubbed.
"""
import json

import pytest

from research import db, worker
from research.model import ModelClient
from tests.conftest import ARTICLE, entry, good_proposal, make_transport, write_allowlist

URL = 'https://fixture.example/household-method/'


def run(cfg, tmp_path, post):
    write_allowlist(tmp_path, [entry(URL)])
    return worker.run(
        cfg,
        transport=make_transport({URL: (200, URL, {'content-type': 'text/html'}, ARTICLE)}),
        model=ModelClient('ollama', 1, model='test-thinking-model', http_post=post),
        content_kind='fixture',
    )


def test_worker_requests_final_answer_with_bounded_recorded_context(cfg, tmp_path):
    payloads = []

    def post(url, payload, timeout):
        payloads.append(payload)
        # The controlled Qwen probe stopped without a final answer in default mode.
        if payload.get('think') is not False:
            return {'response': '', 'done': True, 'done_reason': 'stop', 'eval_count': 393}
        return {'response': json.dumps(good_proposal('', {})), 'done': True, 'done_reason': 'stop'}

    result = run(cfg, tmp_path, post)
    assert result.ok and result['inference_calls'] == 1
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload['think'] is False
    assert payload['options'] == {'temperature': 0, 'seed': 7, 'num_predict': 900, 'num_ctx': 8192}
    assert payload['format'] == 'json' and payload['stream'] is False
    conn = db.connect(cfg.db_path)
    call = conn.execute('SELECT * FROM inference_calls').fetchone()
    assert call['status'] == 'ok' and call['error'] is None and call['response_chars'] > 0
    assert call['context_tokens'] == payload['options']['num_ctx']
    candidate = conn.execute('SELECT * FROM candidates').fetchone()
    assert candidate['state'] == 'deferred' and candidate['publishable'] == 0
    assert candidate['state_reason'].startswith('unvalidated_free_text:')
    conn.close()


@pytest.mark.parametrize('raw', ['', '{"household_problem":', '[]', 'not JSON'])
def test_bad_final_answer_stays_failed_without_reasoning_fallback_or_retry(cfg, tmp_path, raw):
    payloads = []

    def post(url, payload, timeout):
        payloads.append(payload)
        # Valid JSON in another field is NOT a valid final model response.
        return {'response': raw, 'thinking': json.dumps(good_proposal('', {})),
                'done': True, 'done_reason': 'length'}

    first = run(cfg, tmp_path, post)
    assert first['inference_calls'] == 1 and len(payloads) == 1
    conn = db.connect(cfg.db_path)
    call = conn.execute('SELECT * FROM inference_calls').fetchone()
    assert call['status'] == 'error' and call['ok'] == 0 and call['error']
    assert call['response_chars'] == len(raw)
    candidate = conn.execute('SELECT * FROM candidates').fetchone()
    assert candidate['state'] == 'deferred' and candidate['publishable'] == 0
    conn.close()

    second = run(cfg, tmp_path, post)
    assert second['inference_calls'] == 0 and len(payloads) == 1
    conn = db.connect(cfg.db_path)
    assert conn.execute('SELECT COUNT(*) FROM inference_calls').fetchone()[0] == 1
    conn.close()
