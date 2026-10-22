"""Conservative evidence summary, not a model promotion mechanism."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
@_log_traced('app.transformations.release_readiness.release_readiness', level=10)
def release_readiness(status,result):
    blockers=[]
    if status!='completed':blockers.append('Training has not completed successfully.')
    total=result.get('evaluation_tested')
    before=result.get('evaluation_before');after=result.get('evaluation_after')
    valid=all(type(n) is int for n in (total,before,after)) and total>0 and 0<=before<=total and 0<=after<=total
    comparison='unavailable'
    if not valid:blockers.append('Complete before/after evaluation counts are unavailable.')
    else:
        comparison='improved' if after>before else 'regressed' if after<before else 'unchanged'
        if after<before:blockers.append('Reviewed evaluation accuracy regressed.')
        if after<total:blockers.append('Some reviewed evaluation examples still fail.')
    # Worker reports are not substitutes for independent retention/release evidence.
    blockers.extend(['Independent full retention evaluation has not been attached.',
                     'Candidate integrity and release approval have not been verified.',
                     'Activation and rollback workflow is not implemented.'])
    return {'ready_to_activate':False,'comparison':comparison,
            'evaluation':{'tested':total,'before':before,'after':after} if valid else None,
            'blockers':blockers,'scope':'Small reviewed feedback dataset only; not general transformation accuracy.'}
