#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

server = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
path = server / 'src/test/testCards.js'
text = path.read_text(encoding='utf-8').replace('\r\n', '\n')

# The public server already required sub_submission, while its own integration
# fixtures omitted it. Add the ordinary non-submission value to every card
# report fixture so the tests continue to exercise their intended condition.
text, report_count = re.subn(
    r"('disaster_type':\s*[^,]+,\n)(\s*)('card_data':)",
    lambda match: match.group(1) + match.group(2) + "'sub_submission': false,\n" + match.group(2) + match.group(3),
    text,
)
if report_count < 2:
    raise RuntimeError(f'Expected multiple report fixtures, patched {report_count}')

# The hardened image PATCH contract persists the validated extension. Keep the
# old semantic tests but supply the new required field.
text, image_count = re.subn(
    r"('image_url':\s*'image',\n)(\s*)(})",
    lambda match: match.group(1) + match.group(2) + "'image_type': 'jpeg',\n" + match.group(2) + match.group(3),
    text,
)
if image_count != 3:
    raise RuntimeError(f'Expected three image fixtures, patched {image_count}')

path.write_text(text, encoding='utf-8')
print({'status': 'server test contract fixtures patched', 'reports': report_count, 'images': image_count})
