"""Conservative collection planning and business-field matching for sample payloads."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import re
from difflib import SequenceMatcher


@_log_traced('app.transformations.structure.tokens', level=10)
def tokens(value):
    words = {w.lower().removesuffix('s') for w in re.sub(r'([a-z])([A-Z])', r'\1 \2', str(value)).replace('_', ' ').split()}
    synonyms = {'line':'item','entry':'item','record':'item','product':'item'}
    return {synonyms.get(word, word) for word in words}


@_log_traced('app.transformations.structure.collections', level=10)
def collections(value, xml=False, path=()):
    found = {}
    if isinstance(value, list):
        found[path] = path + (0,)
        if value:
            found.update(collections(value[0], xml, path + (0,)))
        return found
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (key,)
            # XML can show only one item in a plural wrapper; DOM still exposes a sequence.
            if xml and path and isinstance(child, (dict,str)) and tokens(key) & tokens(path[-1]) and str(path[-1]).lower() != str(key).lower():
                found[child_path] = child_path
            found.update(collections(child, xml, child_path))
    return found


@_log_traced('app.transformations.structure.plan_loops', level=10)
def plan_loops(target, source_collections, xml=False):
    plans, warnings = {}, []
    def walk(value, path=(), parent=None):
        is_list = isinstance(value, list)
        item_path = path + (0,) if is_list else path
        prototype = value[0] if is_list and value else value
        wrapper = isinstance(value, dict) and path and any(isinstance(v, (dict,list)) and tokens(k) & tokens(path[-1]) for k,v in value.items())
        if is_list or (xml and isinstance(value, (dict,str)) and len(path) > 1 and not wrapper):
            eligible = []
            for source, source_item in source_collections.items():
                owners = [p for p, item in source_collections.items() if p != source and source[:len(item)] == item]
                owner = max(owners, key=len) if owners else None
                if owner != parent:
                    continue
                name = path[-1] if path else ''
                score = len(tokens(name) & tokens(source[-1]))
                if score:
                    eligible.append((score, source, source_item))
            eligible.sort(key=lambda x:x[0], reverse=True)
            if eligible and (len(eligible) == 1 or eligible[0][0] > eligible[1][0]):
                if is_list and not value:
                    raise ValueError(f'Target list {".".join(map(str,path))} needs one example item to define the output fields.')
                _, source, source_item = eligible[0]
                plans[item_path] = {'source':source, 'prototype':source_item, 'variable':f'row{len(plans)}'}
                parent = source
            elif eligible:
                warnings.append(f'{".".join(map(str,path))}: multiple source collections match; no loop inferred. Rename the target collection to disambiguate.')
        if is_list:
            if value:
                walk_children(prototype, item_path, parent)
        else:
            walk_children(value, path, parent)
    def walk_children(value,path,parent):
        if isinstance(value,dict):
            for key,child in value.items():
                walk(child,path+(key,),parent)
    walk(target)
    return plans, warnings


ALIASES = {
    'fullname': {'fullname','name'},
    'name': {'name','fullname'},
    'code': {'productid','productcode','code','sku'},
    'description': {'productname','description','name'},
    'price': {'unitprice','price'},
    'msisdn': {'mobilenumber','msisdn','phone','phoneNumber'.lower()},
    'customerphone': {'mobilenumber','msisdn','phone','phonenumber'},
    'amount': {'amount','amt','value','total','4'},
    'currency': {'currency','currencycode','curr','49'},
    '4': {'4','amount'},
    '49': {'49','currency'},
    'currencycode': {'currency','currencycode'},
    'method': {'paymentmethod','method'},
    'value': {'amount','value'},
    'reference': {'transactionid','reference','referenceid'},
    'id': {'customerid','subscriberid','id'},
}


@_log_traced('app.transformations.structure.choose', level=10)
def choose(target_path, candidates):
    leaf = str(target_path[-1]).lower()
    aliases = ALIASES.get(leaf, {leaf})
    scored = []
    for name, (path, value) in candidates.items():
        source_leaf = str(path[-1]).lower()
        score = 1.0 if source_leaf == leaf else .94 if source_leaf in aliases else 0
        # Only close lexical matches; unrelated "id" fields must not win on a generic suffix.
        if not score:
            score = SequenceMatcher(None, leaf, source_leaf).ratio()
            if score < .82:
                continue
        context = set().union(*(tokens(p) for p in target_path[:-1]))
        source_context = set().union(*(tokens(p) for p in path[:-1]))
        if 'subscriber' in context:
            context.add('customer')
        score += .04 * len(context & source_context)
        scored.append((score, name))
    scored.sort(reverse=True)
    if not scored or (len(scored)>1 and abs(scored[0][0]-scored[1][0])<.02):
        return '', 0, 'No unambiguous field match'
    return scored[0][1], min(scored[0][0],1), 'Context-aware field match'
