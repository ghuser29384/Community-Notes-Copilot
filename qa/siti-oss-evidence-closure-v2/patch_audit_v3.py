#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
v2 = ROOT / 'patch_audit_v2.py'
text = v2.read_text(encoding='utf-8')

original_target = """  const context = await browser.newContext({
    viewport: scenario.viewport || { width: 1365, height: 900 },
    geolocation: { latitude: -6.175392, longitude: 106.827153 },
    permissions: ['geolocation'],
  });"""

styled_target = """  const context = await browser.newContext({
    viewport: scenario.viewport || { width: 1365, height: 900 },
    isMobile: Boolean(scenario.viewport && scenario.viewport.width <= 480),
    hasTouch: Boolean(scenario.viewport && scenario.viewport.width <= 480),
    deviceScaleFactor: scenario.viewport && scenario.viewport.width <= 480 ? 2 : 1,
    geolocation: { latitude: -6.175392, longitude: 106.827153 },
    permissions: ['geolocation'],
  });"""

count = text.count(original_target)
if count != 1:
    raise RuntimeError(
        f'expected one original mobile target in patch_audit_v2.py, found {count}'
    )
v2.write_text(text.replace(original_target, styled_target, 1), encoding='utf-8')
runpy.run_path(str(v2), run_name='__main__')
