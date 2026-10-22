"""JSON validity checks: never silently overwrite keys or accept NaN/infinity."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import math


@_log_traced('app.transformations.json_validation.finite_values', level=10)
def finite_values(value):
    if isinstance(value,float) and not math.isfinite(value):
        raise ValueError('JSON numbers must be finite.')
    if isinstance(value,dict):
        for item in value.values():finite_values(item)
    elif isinstance(value,list):
        for item in value:finite_values(item)
    return value


@_log_traced('app.transformations.json_validation.strict_json', level=10)
def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError(f'Duplicate JSON key: {key!r}.')
            result[key]=value
        return result
    def invalid_constant(value):
        raise ValueError('JSON numbers must be finite.')
    return finite_values(json.loads(text,object_pairs_hook=pairs,parse_constant=invalid_constant))
