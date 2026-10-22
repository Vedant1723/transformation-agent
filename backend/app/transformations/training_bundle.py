"""Small deterministic byte-BPE tokenizer and guided-generation dataset compiler.

No pretrained vocabulary, model weights, network calls or weight training.
"""
import json
import copy
from collections import Counter
from app.transformations.dataset import digest

PAD, BOS, SEP, EOS = 256, 257, 258, 259


def merge(tokens, pair, token):
    result, i = [], 0
    while i < len(tokens):
        if i + 1 < len(tokens) and (tokens[i], tokens[i + 1]) == pair:
            result.append(token); i += 2
        else:
            result.append(tokens[i]); i += 1
    return result


def fit_tokenizer(texts, max_merges=32):
    sequences = [list(text.encode('utf-8')) for text in texts]
    merges = []
    for step in range(max_merges):
        counts = Counter(pair for seq in sequences for pair in zip(seq, seq[1:]))
        if not counts:
            break
        pair, count = min(counts.items(), key=lambda item: (-item[1], item[0]))
        if count < 2:
            break
        token = 260 + step
        merges.append([pair[0], pair[1], token])
        sequences = [merge(seq, pair, token) for seq in sequences]
    return {'algorithm': 'byte-bpe-v1', 'encoding': 'utf-8', 'base_byte_ids': [0, 255],
        'special_tokens': {'pad': PAD, 'bos': BOS, 'separator': SEP, 'eos': EOS},
        'merges': merges, 'vocab_size': 260 + len(merges), 'fit_split': 'train'}


def encode(text, tokenizer):
    tokens = list(text.encode('utf-8'))
    for a, b, token in tokenizer['merges']:
        tokens = merge(tokens, (a, b), token)
    return tokens


def decode(tokens, tokenizer):
    vocab = {i: bytes([i]) for i in range(256)}
    for a, b, token in tokenizer['merges']:
        vocab[token] = vocab[a] + vocab[b]
    # Special tokens are not accepted silently: callers must strip sequence framing.
    return b''.join(vocab[token] for token in tokens).decode('utf-8')


def pair(record, normalize_model_prompt=False):
    example = record['example']
    context = example['context']
    if normalize_model_prompt:
        from app.transformations.model_prompt_contract import normalize_context
        context=normalize_context(context)
    # Never include assistant answers, old templates, outputs or feedback in the prompt.
    fields = ('direction', 'source', 'target', 'additionalProperties', 'headers', 'mappings', 'validations', 'filters')
    prompt = json.dumps({'task': 'Generate a FreeMarker transformation from these explicit requirements.',
        'context': {key: context[key] for key in fields if key in context}},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return {'id': record['id'], 'split': record['split'], 'prompt': prompt, 'target': example['template'],
        'provenance': record['provenance']}


def compile_bundle(manifest, max_merges=32, max_sequence_tokens=8192, frozen_tokenizer=None, normalize_model_prompt=False):
    records = manifest['records']
    if not 0 <= max_merges <= 64 or not 128 <= max_sequence_tokens <= 32768:
        raise ValueError('Tokenizer/sequence settings exceed supported bounds.')
    if not records or len(records) > 200:
        raise ValueError('Select a dataset of 1–200 examples for this checkpoint.')
    if {r['split'] for r in records} != {'train', 'evaluation'}:
        raise ValueError('Both training and evaluation examples are required.')
    if digest(records) != manifest['content_sha256']:
        raise ValueError('Dataset checksum mismatch.')
    pairs = [pair(r,normalize_model_prompt) for r in records]
    size = sum(len(p['prompt'].encode()) + len(p['target'].encode()) for p in pairs)
    if size > 200_000:
        raise ValueError('Combined prompt/target data exceeds the 200 KB preparation limit.')
    texts = [text for p in pairs if p['split'] == 'train' for text in (p['prompt'], p['target'])]
    tokenizer = copy.deepcopy(frozen_tokenizer) if frozen_tokenizer is not None else fit_tokenizer(texts, max_merges)
    examples = []
    for p in pairs:
        source_ids, target_ids = encode(p['prompt'], tokenizer), encode(p['target'], tokenizer)
        tokens = [BOS] + source_ids + [SEP] + target_ids + [EOS]
        if len(tokens) > max_sequence_tokens:
            raise ValueError(f"Example {p['id']} exceeds the sequence limit; no examples were truncated. Raise the limit or simplify the dataset.")
        examples.append({**p, 'input_ids': tokens,
            'labels': [-100] * (len(source_ids) + 2) + target_ids + [EOS],
            'token_count': len(tokens)})
    bundle = {'schema_version': 1, 'task': 'guided-freemarker-generation-v1',
        'dataset_sha256': manifest['content_sha256'], 'benchmark_id': manifest.get('benchmark_id'),
        'tokenizer': tokenizer, 'tokenizer_sha256': digest(tokenizer),
        'settings': {'max_merges': max_merges, 'max_sequence_tokens': max_sequence_tokens},
        'counts': {split: sum(p['split'] == split for p in examples) for split in ('train', 'evaluation')},
        'label_contract': 'Unshifted causal-LM labels. Training loop must shift logits/labels once; ignore -100. PAD=256, never byte 0.',
        'limitations': ['Prepared data only; no model weights trained.',
            'Tokenizer merges fitted only on train prompts/targets. Evaluation uses UTF-8 byte fallback.',
            'Guided generation includes explicit mappings/rules. It is not an unrestricted conversational dataset.',
            'No truncation, padding or model-training loop is implemented here.',
            'Human-approved examples and fixed benchmark protections remain required. Small datasets are not sufficient for useful language understanding.'],
        'examples': examples}
    if frozen_tokenizer is not None:
        bundle['settings']['tokenizer_mode']='frozen-existing-model'
        bundle['settings']['max_merges']=len(tokenizer['merges'])
        bundle['limitations'][1]='Existing model tokenizer reused unchanged; no fitting on feedback or evaluation.'
    if normalize_model_prompt:
        bundle['settings']['prompt_contract']='empty-optionals-v1'
    bundle['content_sha256'] = digest(bundle)
    return bundle
