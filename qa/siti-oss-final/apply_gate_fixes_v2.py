#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
REPORTCARDS = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))

# Apply the previously reviewed candidate changes first.
runpy.run_path(str(ROOT / 'apply_candidate_fixes.py'), run_name='__main__')


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


def regex_replace_once(path: Path, pattern: str, replacement: str, label: str) -> None:
    text, newline = read_normalized(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f'{label}: expected one regex match in {path}, found {count}')
    write_preserve(path, updated, newline)


# Gate A: serialize submission of a one-time card inside the database
# transaction. This removes the check-then-insert race instead of trying to
# interpret pg-promise/SPEX BatchError shapes after a unique violation.
model = SERVER / 'src/api/routes/cards/model.js'
submit_report = r'''  // Add entry to the reports table and then update the card record accordingly
  submitReport: (card, body) =>
    db.tx((t) => {
      return t.oneOrNone(
        `SELECT received FROM ${config.TABLE_GRASP_CARDS}
         WHERE card_id = $1
         FOR UPDATE`,
        [card.card_id]
      ).then((current) => {
        if (!current) {
          const missing = new Error("Card not found");
          missing.code = "CARD_NOT_FOUND";
          throw missing;
        }
        if (current.received) {
          const conflict = new Error("Report already received");
          conflict.code = "REPORT_ALREADY_RECEIVED";
          throw conflict;
        }

        const partnerCode = body.partnerCode ? body.partnerCode : null;
        return t.none(
          `INSERT INTO ${config.TABLE_GRASP_REPORTS}
           (card_id, card_data, text, created_at, disaster_type,
            partner_code, status, the_geom)
           VALUES ($1, $2, COALESCE($3,''), $4, COALESCE($5,null),
            COALESCE($6,null), $7, ST_SetSRID(ST_Point($8,$9),4326))`,
          [
            card.card_id,
            body.card_data,
            body.text,
            body.created_at,
            body.disaster_type,
            partnerCode,
            "Confirmed",
            body.location.lng,
            body.location.lat,
          ]
        )
          .then(() => t.none(
            `UPDATE ${config.TABLE_GRASP_CARDS}
             SET received = TRUE WHERE card_id = $1`,
            [card.card_id]
          ))
          .then(() => t.none(
            `INSERT INTO ${config.TABLE_GRASP_LOG}
             (card_id, event_type) VALUES ($1, $2)`,
            [card.card_id, "REPORT SUBMITTED"]
          ))
          .then(() => t.oneOrNone(
            `SELECT * FROM grasp.push_to_all_reports($1) as notify`,
            [card.card_id]
          ));
      });
    })
      .timeout(config.PGTIMEOUT)
      .then((data) => {
        const notifyData = JSON.parse(data.notify) || {};
        notifyData.tweetID = body.tweetID || '';
        return notifyData;
      }),

  // All just expired report cards'''
regex_replace_once(
    model,
    r'  // Add entry to the reports table and then update the card record accordingly\n  submitReport: \(card, body\) =>.*?\n\n  // All just expired report cards',
    submit_report,
    'row-locked one-time report submission',
)

# Make the route understand the explicit transaction conflict. Keep the
# defensive PostgreSQL check for deployments that use a different model.
route = SERVER / 'src/api/routes/cards/index.js'
replace_once(
    route,
    '''        const duplicateReport = errors.some((entry) => {
          const candidate = entry && (entry.error || entry);
          return candidate && candidate.code === "23505" &&
            candidate.constraint === "reports_card_id_key";
        });''',
    '''        const duplicateReport =
          (err && err.code === "REPORT_ALREADY_RECEIVED") ||
          errors.some((entry) => {
            const candidate = entry && (entry.error || entry);
            return candidate && candidate.code === "23505" &&
              candidate.constraint === "reports_card_id_key";
          });''',
    'route-level one-time conflict handling',
)

# Gate B/C: SubmitButton already injects TranslateService, but its declaring
# feature module does not expose the translate pipe in production compilation.
# Use the injected service through a getter instead of adding a module-level
# dependency solely for the error message.
submit_html = REPORTCARDS / 'src/app/components/submit-button/submit-button.component.html'
replace_once(
    submit_html,
    "  {{ 'card.review.submitError' | translate }}",
    '  {{ submitErrorText }}',
    'submit error template without unavailable pipe',
)

submit_ts = REPORTCARDS / 'src/app/components/submit-button/submit-button.component.ts'
replace_once(
    submit_ts,
    '''  get loadingText(): string {
    return this.translate.instant('card.review.loading');
  }
''',
    '''  get loadingText(): string {
    return this.translate.instant('card.review.loading');
  }

  get submitErrorText(): string {
    return this.translate.instant('card.review.submitError');
  }
''',
    'translated submit error getter',
)

print({
    'status': 'final gate fixes applied',
    'server': str(SERVER),
    'reportcards': str(REPORTCARDS),
})
