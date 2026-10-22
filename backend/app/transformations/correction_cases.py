"""Replay explicit expected-output scenarios without changing their format or direction."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy
import json


@_log_traced('app.transformations.correction_cases.validate_cases', level=10)
def validate_cases(cases, target_format):
    from app.transformations.scoring import canonical
    if len(cases) > 8 or len(json.dumps(cases).encode()) > 200_000:
        raise ValueError('At most eight additional scenarios and 200 KB are allowed.')
    for case in cases:
        if (case.get('expected_output') is None)==(case.get('expected_error') is None):
            raise ValueError('Exactly one output or validation-stop expectation is required.')
        if case.get('expected_error') is not None:
            if not isinstance(case['expected_error'],str) or not case['expected_error'].strip() or len(case['expected_error'])>500:
                raise ValueError('Expected validation message must be nonblank and at most 500 characters.')
        else:
            canonical(case['expected_output'], target_format)


@_log_traced('app.transformations.correction_cases.replay_cases', level=10)
def replay_cases(context, template, cases):
    from app.transformations.scoring import score_case
    results = []
    for index, case in enumerate(cases):
        variant = copy.deepcopy(context)
        variant['source']['payload'] = copy.deepcopy(case['input_payload'])
        result = score_case({'id': f'correction-scenario-{index}', 'example': {
            'context': variant, 'template': template,
            'test': {'output': case.get('expected_output','')}}}, 'replay')
        if result['status'] == 'infrastructure_error':
            raise ConnectionError('Renderer unavailable during correction scenarios.')
        expects_rejection=case.get('expected_error') is not None
        rejected=(expects_rejection and result['status']=='failed' and result['stage']=='runtime'
            and result.get('error_kind')=='validation_stop' and result.get('validation_message')==case['expected_error'])
        results.append({'name': case['name'], 'passed': rejected if expects_rejection else result['status'] == 'passed',
            'expected_rejection':expects_rejection,'rejection_matched':rejected,
            'render_passed': result['status'] in ('passed', 'mismatch'),
            'output': result['actual'], 'error': result['error'], 'stage': result['stage']})
    return results
