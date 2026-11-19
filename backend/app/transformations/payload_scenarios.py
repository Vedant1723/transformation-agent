"""Bounded static branch probes. These are not FreeMarker execution results."""
import ast
import copy
import itertools
import re
from app.transformations.template_tools import REFERENCE

MISSING = object()
MAX_SCENARIOS = 20
MAX_SEARCH = 512
TAG = re.compile(r'''</?#(?:if|elseif|else|list)\b(?:[^>"']|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')*>''')
TOKEN = re.compile(r'''\s*(?:(?P<ref>body(?:(?:\.[A-Za-z_]\w*)|(?:\[(?:\d+|"[^"\n]*"|'[^'\n]*')\]))+)|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<number>-?\d+(?:\.\d+)?)|(?P<op>\?has_content|\?number|\?string|\?trim|\?length|\?size|\?\?|&&|\|\||==|!=|>=|<=|[()!<>])|(?P<word>true\b|false\b|gte\b|lte\b|gt\b|lt\b|and\b|or\b))''')
TOKEN = re.compile(TOKEN.pattern.replace(r'\?has_content',r'\?matches|\?has_content'))
NUMERIC_PATTERN = r'[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?'


class Condition:
    def __init__(self, text):
        self.tokens=[]; self.refs=set(); self.values=[]; self.index=0
        position=0
        while position<len(text.strip()):
            token=TOKEN.match(text,position)
            if not token:raise ValueError('Unsupported condition expression')
            self.tokens.append((token.lastgroup,token.group(token.lastgroup)))
            position=token.end()
            if len(self.tokens)>128:raise ValueError('Condition too complex')
        self.tree=self.parse(0)
        if self.index!=len(self.tokens):raise ValueError('Unsupported condition suffix')

    def peek(self):
        return self.tokens[self.index][1] if self.index<len(self.tokens) else None

    def parse(self, depth, minimum=0):
        if depth>24 or self.index>=len(self.tokens):raise ValueError('Invalid or deep condition')
        kind,value=self.tokens[self.index];self.index+=1
        if value=='!':node=('not',self.parse(depth+1,4))
        elif value=='(':
            node=self.parse(depth+1)
            if self.peek()!=')':raise ValueError('Unclosed condition')
            self.index+=1
        elif kind=='ref':self.refs.add(value);node=('ref',value)
        elif kind=='string':
            literal=ast.literal_eval(value);self.values.append(literal);node=('value',literal)
        elif kind=='number':
            literal=float(value) if '.' in value else int(value)
            if abs(literal)>1e12:raise ValueError('Numeric scenario bound exceeded')
            self.values.extend([literal,literal-1,literal+1]);node=('value',literal)
        elif value in ('true','false'):node=('value',value=='true')
        else:raise ValueError('Unsupported condition token')
        while self.peek() and self.peek().startswith('?'):
            op=self.peek();self.index+=1
            if op=='?matches':
                if self.peek()!='(':raise ValueError('Unsupported matches expression')
                self.index+=1
                if self.index>=len(self.tokens) or self.tokens[self.index][0]!='string':raise ValueError('Regex must be literal')
                pattern=ast.literal_eval(self.tokens[self.index][1]);self.index+=1
                if pattern!=NUMERIC_PATTERN or self.peek()!=')':raise ValueError('Only compiler numeric regex guards are supported')
                self.index+=1;node=(op,node,pattern)
            else:node=(op,node)
        precedences={'||':1,'or':1,'&&':2,'and':2,'==':3,'!=':3,'>':3,'<':3,'>=':3,'<=':3,'gt':3,'lt':3,'gte':3,'lte':3}
        while self.peek() in precedences and precedences[self.peek()]>=minimum:
            op=self.peek();self.index+=1
            node=(op,node,self.parse(depth+1,precedences[op]+1))
        return node

    def evaluate(self, getter, source_format='JSON'):
        def visit(node):
            op=node[0]
            if op=='ref':return getter(node[1])
            if op=='value':return node[1]
            left=visit(node[1])
            xml_node=(source_format=='XML' and node[1][0]=='ref' and
                      not node[1][1].startswith(('body.headers.','body.header.','body.addProps.','body.headers[','body.header[','body.addProps[')))
            if xml_node and op in ('?size','?has_content'):
                count=0 if left is MISSING or left is None else len(left) if isinstance(left,list) else 1
                return count if op=='?size' else count>0
            if op=='??':return left is not MISSING and left is not None
            if op=='?has_content':return left is not MISSING and left is not None and left!='' and left!=[] and left!={}
            if op=='not':return not boolean(left)
            if op in ('&&','and'):return boolean(left) and boolean(visit(node[2]))
            if op in ('||','or'):return boolean(left) or boolean(visit(node[2]))
            if left is MISSING:raise ValueError('Missing field')
            if op=='?matches':return re.fullmatch(node[2],str(left)) is not None
            if op=='?number':return float(left)
            if op=='?string':return str(left).lower() if isinstance(left,bool) else str(left)
            if op=='?trim':return str(left).strip()
            if op in ('?length','?size'):return len(left)
            right=visit(node[2])
            if right is MISSING:raise ValueError('Missing field')
            compatible = type(left) == type(right) or (type(left) in (int,float) and type(right) in (int,float))
            if not compatible:raise ValueError('Incompatible comparison types')
            if op=='==':return left==right
            if op=='!=':return left!=right
            if op in ('>','gt'):return left>right
            if op in ('<','lt'):return left<right
            if op in ('>=','gte'):return left>=right
            if op in ('<=','lte'):return left<=right
            raise ValueError('Unsupported operator')
        def boolean(value):
            if not isinstance(value,bool):raise ValueError('Condition requires a boolean')
            return value
        return boolean(visit(self.tree))


def location(reference,direction):
    parts=[]
    for token in re.finditer(r'''\.([A-Za-z_]\w*)|\[(\d+)\]|\["([^"\n]*)"\]|\['([^'\n]*)'\]''',reference[4:]):
        parts.append(int(token[2]) if token[2] else token[1] or token[3] or token[4])
    root='payload'
    if direction=='REQUEST' and parts:
        if parts[0] in ('headers','header','addProps'):
            root='props' if parts[0]=='addProps' else 'headers';parts=parts[1:]
        elif parts[0]=='request':parts=parts[1:]
    return root,parts


def read(state,reference,direction):
    root,parts=location(reference,direction);node=state[root]
    try:
        for part in parts:node=node[part]
        return node
    except (KeyError,IndexError,TypeError):return MISSING


def write(state,reference,value,direction):
    root,parts=location(reference,direction)
    if not parts or len(parts)>20:raise ValueError('Unsupported scenario path')
    node=state[root]
    for index,part in enumerate(parts[:-1]):
        if isinstance(node,list):
            if not isinstance(part,int) or part>9:raise ValueError('Invalid list path')
            while len(node)<=part:node.append({})
        elif not isinstance(node,dict):raise ValueError('Conflicting path')
        absent = part not in node if isinstance(node,dict) else node[part] is None
        if absent:
            node[part]=[] if isinstance(parts[index+1],int) else {}
        node=node[part]
    key=parts[-1]
    if isinstance(node,list):
        if not isinstance(key,int) or key>9:raise ValueError('Invalid list index')
        while len(node)<=key:node.append(None)
        if value is MISSING:node[key]=None
        else:node[key]=copy.deepcopy(value)
    elif isinstance(node,dict):
        if value is MISSING:node.pop(key,None)
        else:node[key]=copy.deepcopy(value)
    else:raise ValueError('Conflicting scenario path')


def build_scenarios(template, data, headers, props, direction, serialize, loop_paths, regex_hints=None, source_format='JSON'):
    base={'payload':data,'headers':headers,'props':props}
    scenarios=[];uncovered=[];stack=[];targets=[];loop_depth=0;truncated=False
    clean=re.sub(r'<#--[\s\S]*?-->|<#noparse\b[^>]*>[\s\S]*?</#noparse>', '', template)
    def active():
        return [entry for frame in stack for entry in frame['active']]
    for tag in TAG.finditer(clean):
        text=tag[0];line=clean.count('\n',0,tag.start())+1
        if text.startswith('<#list'):loop_depth+=1;continue
        if text.startswith('</#list'):loop_depth=max(0,loop_depth-1);continue
        if text.startswith('</#if'):
            if stack:stack.pop()
            continue
        if text.startswith('<#if') or text.startswith('<#elseif'):
            elseif=text.startswith('<#elseif')
            expression=text[len('<#elseif') if elseif else len('<#if'):-1].strip()
            try:condition=Condition(expression) if not loop_depth else None
            except (ValueError,SyntaxError,RecursionError):condition=None
            if elseif:
                if not stack:continue
                frame=stack[-1]
                frame['previous'].append(frame['current'])
                frame['current']=condition
                frame['active']=[(c,False) for c in frame['previous']]+[(condition,True)]
            else:
                stack.append({'current':condition,'previous':[],'active':[(condition,True)]})
            targets.append((('elseif' if elseif else 'if'),line,expression,active()))
        elif text.startswith('<#else') and stack:
            frame=stack[-1]
            frame['active']=[(c,False) for c in frame['previous']+[frame['current']]]
            targets.append(('else',line,'All earlier conditions in this chain are false',active()))
        if len(targets)>=60:truncated=True;break

    def emit(state,kind,line,description):
        nonlocal truncated
        if len(scenarios)>=MAX_SCENARIOS:truncated=True;return False
        try:
            payload=serialize(state['payload'])
            if direction=='REQUEST':payload={'inputRequest':payload,'inputHeaders':state['headers'],'additionalProperties':state['props']}
        except (ValueError,TypeError):return False
        scenarios.append({'id':f'scenario_{len(scenarios)+1}','kind':kind,'line':line,
            'description':description,'input_payload':payload,'verified':False,
            'status':'inferred','expectation':'Intended branch probe. Execute the template to confirm actual behavior.'})
        return True

    for kind,line,description,constraints in targets:
        if len(scenarios)>=MAX_SCENARIOS:truncated=True;break
        if any(c is None for c,_ in constraints):
            uncovered.append({'line':line,'kind':kind,'reason':'Unsupported condition or condition inside a loop.'});continue
        refs=sorted(set().union(*(c.refs for c,_ in constraints)))
        if len(refs)>4:
            uncovered.append({'line':line,'kind':kind,'reason':'More than four fields in branch constraints.'});continue
        literals=[value for c,_ in constraints for value in c.values]
        domains=[]
        for ref in refs:
            original=read(base,ref,direction)
            values=[original]+literals+[MISSING,'',False,True,0,1,10,'OTHER']
            if isinstance(original,list):values += [[], original*2]
            # Stable order and types; bool must not collapse into numeric 0/1.
            unique=[]
            for value in values:
                if not any(type(value)==type(v) and value==v for v in unique):unique.append(value)
            domains.append(unique[:18])
        found=False
        for values in itertools.islice(itertools.product(*domains),MAX_SEARCH):
            state=copy.deepcopy(base)
            try:
                for ref,value in zip(refs,values):write(state,ref,value,direction)
                if not all(c.evaluate(lambda ref:read(state,ref,direction),source_format)==expected for c,expected in constraints):continue
                found=emit(state,kind,line,description)
                if found:break
            except (ValueError,TypeError,KeyError,IndexError,OverflowError):continue
        if not found:uncovered.append({'line':line,'kind':kind,'reason':'No compatible sample found within the bounded search; this does not prove the branch unreachable.'})

    for ref in dict.fromkeys(path[:-3] for path in loop_paths if path.endswith('[0]')):
        original=read(base,ref,direction)
        if not isinstance(original,list):continue
        for kind,value in [('list_empty',[]),('list_populated',original*2)]:
            state=copy.deepcopy(base)
            try:write(state,ref,value,direction);emit(state,kind,None,f'{ref}: {"empty" if not value else "multiple items"}')
            except (ValueError,TypeError,IndexError,KeyError):continue
    for ref,example in (regex_hints or {}).items():
        for kind,value in [('regex_no_match','NO_MATCH'),('regex_single_match',example),('regex_multiple_matches',example+' '+example)]:
            state=copy.deepcopy(base)
            try:write(state,ref,value,direction);emit(state,kind,None,f'{ref}: {kind.removeprefix("regex_").replace("_"," ")}')
            except (ValueError,TypeError,IndexError,KeyError):continue
    return scenarios, {'generated':len(scenarios),'limit':MAX_SCENARIOS,'truncated':truncated,
                       'uncovered':uncovered,'verified':False,
                       'note':'Static probes, not exhaustive coverage. FreeMarker execution, branch reachability and output correctness are unverified.'}
