"""Explicit admin-only resume; run with service environment and an increased budget.
Usage: AGENT_MAX_MODEL_CALLS=14 python scripts/resume_review.py JOB_ID
Does not retry transport errors or restart OCR/solve. See Runner.resume_review guards.
"""
import sys
from math_agent.config import Settings
from math_agent.pipeline import Runner
if __name__ == '__main__':
    runner=Runner(Settings(),sys.argv[1])
    runner.resume_review()
    print(runner.store.get(runner.job_id)['status'])
