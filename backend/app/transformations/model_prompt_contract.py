"""Versioned normalization for newly prepared existing-model feedback bundles.

Does not change saved reviews, bundles, tokenizer or model weights.
"""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import copy


@_log_traced('app.transformations.model_prompt_contract.normalize_context', level=10)
def normalize_context(context):
    result=copy.deepcopy(context)
    result.setdefault('validations',[])
    # Empty optional metadata is equivalent to absence at execution, but not at
    # token level. Preserve nonempty values and explicit mapping decisions.
    for key in ('additionalProperties','headers'):
        if result.get(key)=={}:result.pop(key)
    if result.get('filters')==[]:result.pop('filters')
    return result
