#!/usr/bin/env python3
from __future__ import annotations

import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTCARDS = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))

# Apply all prior reviewed server and Report Cards fixes first.
runpy.run_path(str(ROOT / 'apply_gate_fixes_v2.py'), run_name='__main__')


def read_normalized(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    return raw.decode('utf-8').replace('\r\n', '\n'), newline


def write_preserve(path: Path, text: str, newline: str) -> None:
    normalized = text.replace('\r\n', '\n')
    if newline == '\r\n':
        normalized = normalized.replace('\n', '\r\n')
    path.write_bytes(normalized.encode('utf-8'))


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text, newline = read_normalized(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected one anchor in {path}, found {count}')
    write_preserve(path, text.replace(old, new, 1), newline)


image_ts = REPORTCARDS / 'src/app/components/image-uploader/image-uploader.component.ts'
replace_once(
    image_ts,
    "import { DeckService } from '../../services/cards/deck.service'\n",
    "import { DeckService } from '../../services/cards/deck.service'\n"
    "import { TranslateService } from '@ngx-translate/core';\n",
    'image uploader translate service import',
)
replace_once(
    image_ts,
    '  constructor(private deckService: DeckService) {}',
    '''  constructor(
    private deckService: DeckService,
    private translate: TranslateService
  ) {}''',
    'image uploader translate service injection',
)
replace_once(
    image_ts,
    '''  ngOnInit() {
    if (this.isImageSelected)
      this.setImagePreview(this.deckService.getPreview())
  }
''',
    '''  ngOnInit() {
    if (this.isImageSelected)
      this.setImagePreview(this.deckService.getPreview())
  }

  get imageErrorText(): string {
    return this.imageError
      ? this.translate.instant('card.review.imageError.' + this.imageError)
      : '';
  }
''',
    'image uploader translated error getter',
)

image_html = REPORTCARDS / 'src/app/components/image-uploader/image-uploader.component.html'
replace_once(
    image_html,
    "  {{ ('card.review.imageError.' + imageError) | translate }}",
    '  {{ imageErrorText }}',
    'image error template without unavailable pipe',
)

print({
    'status': 'image uploader feature-module translation fix applied',
    'reportcards': str(REPORTCARDS),
})
