"""Deterministic shuffled passes: cover every training example before repeating."""
import random


def coverage_samples(examples,seed=23):
    if not examples or any(row.get('split')!='train' for row in examples):
        raise ValueError('Sampling requires nonempty training-only examples.')
    if len({row['id'] for row in examples})!=len(examples):
        raise ValueError('Training example IDs must be unique.')
    rng=random.Random(seed)
    while True:
        order=list(examples);rng.shuffle(order)
        yield from order
