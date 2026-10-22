"""One local inference request; input/output are JSON, with no interactive shell."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import sys
from app.transformations.local_model import worker

if __name__=='__main__':
    request=json.loads(sys.stdin.read(65536))
    print(json.dumps(worker(request['source'],request['target_field'],request.get('target_format','JSON'),request.get('guided'))))
