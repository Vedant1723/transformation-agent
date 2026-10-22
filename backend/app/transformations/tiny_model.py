"""Random-initialized causal transformer for the local demo; no pretrained weights."""
import torch
from torch import nn
from app.transformations.training_bundle import BOS, SEP, EOS, encode, decode


class TinyTransformer(nn.Module):
    def __init__(self, vocab_size, width=128, layers=2, heads=4, context_length=1024):
        super().__init__()
        self.config = dict(vocab_size=vocab_size, width=width, layers=layers, heads=heads, context_length=context_length)
        self.tokens = nn.Embedding(vocab_size, width)
        self.positions = nn.Embedding(context_length, width)
        self.blocks = nn.ModuleList([nn.TransformerEncoderLayer(width, heads, width*4,
            dropout=0.0, batch_first=True, norm_first=True, activation='gelu') for _ in range(layers)])
        self.norm = nn.LayerNorm(width)
        self.output = nn.Linear(width, vocab_size, bias=False)

    def forward(self, ids):
        length = ids.shape[1]
        if length > self.config['context_length']:
            raise ValueError('Sequence exceeds model context; truncation is not allowed.')
        x = self.tokens(ids) + self.positions(torch.arange(length, device=ids.device))
        mask = torch.ones(length, length, device=ids.device, dtype=torch.bool).triu(1)
        for block in self.blocks:
            x = block(x, src_mask=mask)
        return self.output(self.norm(x))


def causal_loss(model, example, device):
    ids = torch.tensor([example['input_ids']], device=device)
    labels = torch.tensor(example['labels'][1:], device=device)
    logits = model(ids[:, :-1])[0]
    if 'loss_weights' in example:
        weights = torch.tensor(example['loss_weights'][1:], device=device)
        if weights.shape != labels.shape or not torch.isfinite(weights).all() or (weights < 0).any():
            raise ValueError('Invalid token loss weights.')
        weights = weights * (labels != -100)
        if weights.sum() <= 0: raise ValueError('No weighted target tokens.')
        losses = nn.functional.cross_entropy(logits, labels, ignore_index=-100, reduction='none')
        return (losses * weights).sum() / weights.sum()
    return nn.functional.cross_entropy(logits, labels, ignore_index=-100)


@torch.inference_mode()
def generate_template(model, prompt, tokenizer, device, max_new_tokens=640, beam_width=1, output_prefix=''):
    if output_prefix:
        if beam_width!=1:raise ValueError('Scaffolded decoding currently supports greedy decoding only.')
        return generate_scaffolded(model,prompt,tokenizer,device,max_new_tokens,output_prefix)
    if beam_width not in (1,2,4):raise ValueError('Beam width must be 1, 2 or 4.')
    if beam_width>1:return generate_beam(model,prompt,tokenizer,device,max_new_tokens,beam_width)
    model.eval()
    prefix = [BOS] + encode(prompt, tokenizer) + [SEP]
    if len(prefix) >= model.config['context_length']:
        return {'template':'', 'ended':False, 'reason':'Prompt exceeds context'}
    ids = prefix[:]
    generated = []
    ended = False
    for _ in range(min(max_new_tokens, model.config['context_length']-len(prefix))):
        logits = model(torch.tensor([ids], device=device))[0,-1].clone()
        logits[256:259] = -torch.inf  # Never generate PAD/BOS/SEP as template text.
        token = int(logits.argmax())
        if token == EOS:
            ended = True
            break
        generated.append(token); ids.append(token)
    try:
        text = decode(generated, tokenizer)
    except UnicodeDecodeError:
        return {'template':'', 'ended':False, 'reason':'Generated incomplete UTF-8'}
    return {'template':text, 'ended':ended, 'reason':'EOS' if ended else 'Token/context limit'}


@torch.inference_mode()
def generate_beam(model,prompt,tokenizer,device,max_new_tokens,beam_width):
    """Search the same model's predictions; no rules, target hints or repair."""
    model.eval()
    prefix=[BOS]+encode(prompt,tokenizer)+[SEP]
    if len(prefix)>=model.config['context_length']:
        return {'template':'','ended':False,'reason':'Prompt exceeds context'}
    active=[([],0.0)];completed=[]
    for _ in range(min(max_new_tokens,model.config['context_length']-len(prefix))):
        ids=torch.tensor([prefix+tokens for tokens,score in active],device=device)
        logits=model(ids)[:,-1].clone();logits[:,256:259]=-torch.inf
        probabilities=logits.log_softmax(-1)
        proposals=[]
        for row,(tokens,score) in enumerate(active):
            values,indices=probabilities[row].topk(beam_width)
            for value,index in zip(values.tolist(),indices.tolist()):
                total=score+value
                if index==EOS:completed.append((tokens,total))
                else:proposals.append((tokens+[index],total))
        active=sorted(proposals,key=lambda entry:entry[1],reverse=True)[:beam_width]
        if not active or len(completed)>=beam_width:break
    pool=completed or active
    if not pool:return {'template':'','ended':False,'reason':'No candidate'}
    tokens,score=max(pool,key=lambda entry:entry[1]/max(1,len(entry[0]))**.6)
    try:text=decode(tokens,tokenizer)
    except (UnicodeDecodeError,KeyError):return {'template':'','ended':False,'reason':'Invalid generated text'}
    return {'template':text,'ended':bool(completed),'reason':'EOS' if completed else 'Token/context limit','beam_width':beam_width}


@torch.inference_mode()
def generate_scaffolded(model,prompt,tokenizer,device,max_new_tokens,output_prefix):
    """Known setup is supplied externally; only the suffix is model generated."""
    model.eval()
    scaffold=encode(output_prefix,tokenizer)
    ids=[BOS]+encode(prompt,tokenizer)+[SEP]+scaffold
    if len(ids)>=model.config['context_length']:
        return {'template':'','ended':False,'reason':'Prompt plus scaffold exceeds context','scaffolded':True}
    generated=[];ended=False
    for _ in range(min(max_new_tokens,model.config['context_length']-len(ids))):
        logits=model(torch.tensor([ids],device=device))[0,-1].clone();logits[256:259]=-torch.inf
        token=int(logits.argmax())
        if token==EOS:ended=True;break
        generated.append(token);ids.append(token)
    try:suffix=decode(generated,tokenizer)
    except (UnicodeDecodeError,KeyError):
        return {'template':'','ended':False,'reason':'Invalid generated suffix','scaffolded':True}
    return {'template':output_prefix+suffix,'ended':ended,'reason':'EOS' if ended else 'Token/context limit','scaffolded':True,'supplied_prefix':output_prefix,'generated_suffix':suffix}
