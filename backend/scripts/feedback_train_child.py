"""Internal subprocess entry; input is piped, not placed in process arguments."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import sys
from scripts.run_feedback_job import train


@_log_traced('scripts.feedback_train_child.main', level=20)
def main():
    raw=sys.stdin.read(4_000_001)
    if len(raw.encode())>4_000_000:raise ValueError('Worker input too large.')
    data=json.loads(raw)
    if not 1<=data['steps']<=500:raise ValueError('Invalid step limit.')
    print(json.dumps(train(data['bundle'],data['manifest'],data['steps'],data['job_id'])),flush=True)


if __name__=='__main__':main()
