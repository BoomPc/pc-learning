"""Explicit admin action: preserve mathematics, queue a diagram revision.
Usage (service environment): python scripts/revise_diagram.py ORIGINAL_JOB FEEDBACK_JSON
FEEDBACK_JSON contains a list of diagram Issues. This action may incur model fees.
"""
import json,sys
from pathlib import Path
from math_agent.config import Settings
from math_agent.revisions import create_diagram_revision
if __name__=='__main__':
    print(create_diagram_revision(Settings(),sys.argv[1],json.loads(Path(sys.argv[2]).read_text())))
