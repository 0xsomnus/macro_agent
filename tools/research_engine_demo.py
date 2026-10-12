"""Recorded compilation and morning synthesis in a disposable PostgreSQL database."""
import argparse
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import override_settings
from django.test.runner import DiscoverRunner
from django.utils import timezone
from macro_agent.desk import evidence, publication, service, synthesis
from macro_agent.domain.compilation import SECTIONS
from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.domain.daily_synthesis import SCHEMA_VERSION
from macro_agent.domain.models import canonical_json
from macro_agent.monitoring import capture
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import SourceRevision
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.positions import service as positions
from macro_agent.theses import compilation, service as theses

MODEL = 'fictional/recorded-response'
EXACT = '  The policy rate is now 3%.\r\nGold may benefit if real yields fall. Δ\r\n'


class RecordedProvider:
    """No network implementation. These conditional outputs are test fixtures."""
    def __init__(self, role):
        self.role, self.calls, self.catalog_calls = role, 0, 0
    def list_models(self):
        self.catalog_calls += 1
        return {'fetched_at': timezone.now().isoformat(), 'models': [{'id': MODEL,
            'name': 'Fictional recorded output', 'context_length': None,
            'input_price_usd_per_million': None, 'output_price_usd_per_million': None,
            'capabilities': {'chat_completions': True}}]}
    def complete(self, model_id, messages):
        assert not connection.in_atomic_block and connection.get_autocommit()
        self.calls += 1
        context = json.loads(messages[1]['content'])
        if self.role == 'compilation':
            report = context['evidence']['reports'][0]
            output = {'interpretation': {'drivers': ['Falling real yields may support gold.'],
                'horizon': None, 'invalidation_signposts': []},
                'grounding': [{'field': 'drivers', 'index': 0, 'input_id': 'thesis',
                    'exact_quote': 'Gold may benefit if real yields fall.'}],
                'refinement_issues': [{'kind': 'missing_detail', 'input_id': None, 'exact_quote': None,
                    'explanation': 'Horizon and invalidation are unspecified.',
                    'question': 'Over what period and under what failure condition?'},
                    {'kind': 'verification_needed', 'input_id': 'thesis',
                     'exact_quote': 'The policy rate is now 3%.',
                     'explanation': 'The fictional source names a different rate.',
                     'question': 'Which rate series and date does your premise refer to?'}],
                'agent_hypotheses': [], 'counter_case': 'Currency strength might offset the yield effect.',
                'review_card': {key: {'extracted': [], 'proposed': [], 'gap': 'Unresolved.'} for key in SECTIONS},
                'attributed_claims': [{'claim_id': 'rate', 'revision_id': report['revision_id'],
                    'field': 'content', 'exact_quote': 'The committee left the rate at 4%.'}],
                'factual_conflicts': [{'status': 'model_identified', 'input_id': 'thesis',
                    'exact_quote': 'The policy rate is now 3%.', 'claim_ids': ['rate'],
                    'explanation': 'The retained source names 4%; date or series may differ.',
                    'question': 'Which rate series and date does your premise refer to?'}],
                'evidence_assessment': {'summary': 'The fictional source challenges the numeric premise.',
                    'supporting_claim_ids': [], 'counter_claim_ids': ['rate'],
                    'gaps': ['Market expectations and current macro regime unavailable.']}}
        else:
            report = next(item for section in ('new', 'background') for item in context['review']['reports'][section])
            section = {'text': 'The policy-to-yields pathway remains conditional.', 'claim_ids': ['rate'],
                'prior_analysis_ids': [], 'uncertainty': 'Transmission and positioning are unknown.'}
            effect = {'effect': 'supports', 'reasoning': section['text'],
                **{key: section[key] for key in ('claim_ids', 'prior_analysis_ids', 'uncertainty')}}
            book = context['original_inputs']['approved_user']['exposure']['positions']
            output = {'schema_version': SCHEMA_VERSION,
                'attributed_claims': [{'claim_id': 'rate', 'source_revision_id': report['revision_id'],
                    'source_field': 'content', 'quote': 'The committee left the rate at 4%.'}],
                'overview': section, 'thesis_effect': effect,
                'trade_effects': [{**effect, 'position_id': row['position_id'], 'effect': 'potential_risk',
                    'reasoning': 'Funding or currency stress could hurt the trade before the thesis resolves.'}
                    for row in book if row['payload']['status'] == 'open'],
                'counter_case': deepcopy(section), 'watch_questions': ['Does policy transmit to real yields?'],
                'gaps': ['Current prices, funding and verified macro regime unavailable.']}
        return {'content': canonical_json(output), 'reported_model': model_id,
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
            'reported_cost_usd': None, 'latency_ms': 1}


def demonstrate():
    user = get_user_model().objects.create_user(username='fictional-research-trader')
    actor = str(user.pk)
    draft = theses.create_thesis(actor, str(uuid4()), EXACT,
        {'drivers': [], 'horizon': None, 'invalidation_signposts': []})['thesis']
    source_id = 'fixture-research-engine-trace'
    contract = {'kind': 'fictional_fixture', 'label': 'Fictional policy report', 'coverage': 'bounded_snapshot'}
    def capture_report(content):
        at = timezone.now()
        item = SourceItem('rate-report', 'Fictional policy report', 'https://example.invalid/rate',
            at - timedelta(days=1), content)
        return capture.capture(source_id, contract, lambda: SourceBatch((item,), timezone.now(),
            'bounded_snapshot', False, sha256(content.encode()).hexdigest()))
    capture_report('The committee left the rate at 4%.')
    revision = SourceRevision.objects.get(report__source_id=source_id)
    packet = evidence.prepare_evidence(actor, draft['id'], str(uuid4()), [str(revision.pk)])
    compiler, analyst = RecordedProvider('compilation'), RecordedProvider('synthesis')
    compiled = compilation.compile_thesis(actor, draft['id'], str(uuid4()), draft['revision'],
        MODEL, 'nanogpt', evidence_context_id=packet['evidence']['id'], provider=compiler)
    assert compiled['compilation']['status'] == 'compiled'
    proposed = compiled['thesis']
    text, meaning = proposed['draft']['text_version'], proposed['draft']['interpretation']
    approved = theses.approve_thesis(actor, draft['id'], str(uuid4()), text['id'], text['text_digest'],
        meaning['id'], meaning['digest'], proposed['revision'])['thesis']
    positions.create_position(actor, draft['id'], str(uuid4()), approved['approved']['approval']['id'],
        {'underlying': 'XAU', 'direction': 'long', 'quantity': None, 'quantity_unit': None,
         'horizon': None, 'product_id': None, 'venue': None, 'expiry': None, 'quote_currency': None})
    cutoff = timezone.now()
    review = service.create_review(actor, draft['id'], str(uuid4()), cutoff - timedelta(days=1), cutoff,
        [source_id], DailyReviewLimits(100, 100, 200, 300, 16, 2_000_000))
    preview = publication.preview_publication(actor, review['review']['id'], 10)
    published = publication.publish_review(actor, review['review']['id'], str(uuid4()),
        review['review']['digest'], preview['expected_generation'], 10)
    command = str(uuid4())
    fresh = synthesis.synthesize_review(actor, review['review']['id'], command, review['review']['digest'],
        MODEL, 'nanogpt', provider=analyst)
    assert fresh['synthesis']['status'] == 'synthesised'
    current = publication.get_current_brief(actor, draft['id'])
    assert current['current_synthesis']['synthesis'] == fresh['synthesis']
    connections.close_all()
    with override_settings(MACRO_MODEL_API_KEY='', SETTINGS_MODULE='macro_agent.web.local_settings'):
        recovered = synthesis.get_synthesis_command(actor, review['review']['id'], command)
    assert recovered['synthesis'] == fresh['synthesis'] and recovered['replayed']
    capture_report('Fictional correction: the numeric rate observation was withdrawn.')
    stale_packet = evidence.get_evidence(actor, draft['id'], packet['evidence']['id'])
    stale_synthesis = synthesis.inspect_synthesis(actor, fresh['synthesis']['id'])
    final = publication.get_current_brief(actor, draft['id'])
    assert stale_packet['current_disposition']['status'] == 'stale'
    assert stale_synthesis['current_disposition']['status'] == 'stale'
    assert final['current_publication'] is None and final['current_synthesis'] is None
    final_thesis = theses.get_thesis(actor, draft['id'])
    assert final_thesis['approved']['text_version']['exact_text'] == EXACT
    return {'scope': 'Fictional isolated recorded-provider research engine trace',
        'evidence': packet, 'source_compilation': compiled, 'approved_thesis': approved,
        'daily_review': review, 'digest_publication': published, 'fresh_synthesis': fresh,
        'current_before_correction': current, 'restart_receipt': recovered,
        'after_correction': {'evidence': stale_packet, 'synthesis': stale_synthesis,
                             'current_brief': final, 'thesis': final_thesis},
        'recorded_model_calls': {'compilation': compiler.calls, 'synthesis': analyst.calls},
        'real_model_calls': 0, 'real_network_calls': 0, 'real_model_spend_usd': '0',
        'limits': ['Recorded interpretation does not demonstrate live model usefulness.',
            'Fictional source only; no verified macro regime or live coverage.',
            'The naive premise remains exact trader text; conflict is separately model-identified.',
            'Connection restart demonstrates receipt recovery, not an operating-system crash.',
            'Internal notification intent only; no external delivery.']}


def isolated():
    require_local_proof(synthetic=True)
    service.gate()
    if connection.vendor != 'postgresql':
        raise RuntimeError('PostgreSQL is required')
    name = 'test_research_engine_demo_' + uuid4().hex[:16]
    connection.settings_dict['TEST']['NAME'] = name
    runner = DiscoverRunner(interactive=False, verbosity=0, keepdb=False)
    state = runner.setup_databases()
    try:
        with override_settings(MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER='nanogpt',
                MACRO_MODEL_API_KEY='fictional-unused-key', SETTINGS_MODULE='macro_agent.web.local_settings'), \
             patch.object(compilation, 'create_provider', side_effect=AssertionError('Real providers forbidden')), \
             patch.object(synthesis, 'create_provider', side_effect=AssertionError('Real providers forbidden')):
            result = demonstrate()
    finally:
        connections.close_all()
        runner.teardown_databases(state)
    result['database_isolation'] = {'temporary_database': name, 'dropped_after_trace': True,
                                    'existing_trader_records_used': False}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite an existing trace')
    result = isolated()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('Saved fictional research trace. Temporary database dropped; real model/network calls: 0.')
