#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
runpy.run_path(str(ROOT / 'apply_completion_fixes.py'), run_name='__main__')
runpy.run_path(str(ROOT / 'style_candidate_sources.py'), run_name='__main__')
