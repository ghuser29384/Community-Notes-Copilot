#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

SERVER = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
REPORTCARDS = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))


def read_preserve(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    newline = '\r\n' if b'\r\n' in data else '\n'
    return data.decode('utf-8'), newline


def write_preserve(path: Path, text: str, newline: str) -> None:
    if newline == '\r\n':
        text = text.replace('\r\n', '\n').replace('\n', '\r\n')
    else:
        text = text.replace('\r\n', '\n')
    path.write_bytes(text.encode('utf-8'))


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text, newline = read_preserve(path)
    normalized = text.replace('\r\n', '\n')
    old_n = old.replace('\r\n', '\n')
    new_n = new.replace('\r\n', '\n')
    count = normalized.count(old_n)
    if count != 1:
        raise RuntimeError(f'{label}: expected exactly one anchor in {path}, found {count}')
    write_preserve(path, normalized.replace(old_n, new_n, 1), newline)


def append_once(path: Path, block: str, marker: str) -> None:
    text, newline = read_preserve(path)
    normalized = text.replace('\r\n', '\n')
    if marker in normalized:
        return
    if not normalized.endswith('\n'):
        normalized += '\n'
    normalized += block.strip('\n') + '\n'
    write_preserve(path, normalized, newline)


# Legacy server fixes, scoped to the exact public deprecated server commit.
server_cards = SERVER / 'src/api/routes/cards/index.js'
replace_once(
    server_cards,
    "        tweetID: Joi.string().allow('').default(''),\n        sub_submission: Joi.bool().required(),",
    "        tweetID: Joi.string().allow('').default(''),\n"
    "        // The current public Report Cards client sends this explicit flag.\n"
    "        is_training: Joi.bool().default(false),\n"
    "        sub_submission: Joi.bool().required(),",
    'server accepts explicit is_training field',
)
replace_once(
    server_cards,
    '              ContentType: req.query.file_type,',
    '              // Bind the validated MIME type into the signed PUT request.\n'
    '              ContentType: req.headers["content-type"],',
    'signed content type binding',
)
replace_once(
    server_cards,
    '      body: Joi.object().keys({\n        image_url: Joi.string().required(),\n      }),',
    '      body: Joi.object().keys({\n'
    '        image_url: Joi.string().required(),\n'
    '        image_type: Joi.string().valid("jpeg", "png").required(),\n'
    '      }),',
    'image patch type validation',
)
replace_once(
    server_cards,
    '                  "/" +\n                  req.body.image_url +\n                  ".jpg";',
    '                  "/" +\n'
    '                  req.body.image_url +\n'
    '                  "." +\n'
    '                  req.body.image_type;',
    'preserve validated image extension',
)
replace_once(
    server_cards,
    '''      .catch((err) => {
        /* istanbul ignore next */
        logger.error(err);
        /* istanbul ignore next */
        next(err);
      });
  }
}''',
    '''      .catch((err) => {
        // Concurrent requests can both observe received=false before the first
        // transaction commits. Normalize the losing unique-card race to the
        // same stable conflict response as an ordinary replay.
        const errors = [err].concat((err && err.errors) || []);
        const duplicateReport = errors.some((entry) => {
          const candidate = entry && (entry.error || entry);
          return candidate && candidate.code === "23505" &&
            candidate.constraint === "reports_card_id_key";
        });
        if (duplicateReport) {
          clearCache();
          return res.status(409).json({
            statusCode: 409,
            cardId: req.params.cardId,
            message: `Report already received for card '${req.params.cardId}'`,
          });
        }
        /* istanbul ignore next */
        logger.error(err);
        /* istanbul ignore next */
        next(err);
      });
  }
}''',
    'concurrent duplicate normalization',
)

# Report Cards deterministic location confirmation and explicit training type.
location_picker = REPORTCARDS / 'src/app/components/location-picker/location-picker.component.ts'
replace_once(
    location_picker,
    '''    if (this.currentMarker) this.currentMarker.remove(this.map)
    this.currentMarker = marker

    marker.on('dragend' , () => {''',
    '''    if (this.currentMarker) this.currentMarker.remove(this.map)
    this.currentMarker = marker

    // A selected search result is already a concrete user choice. Record it
    // immediately, while retaining marker drag for optional fine adjustment.
    this.deckService.setLocation({ lat: results[0].y, lng: results[0].x })
    this.deckService.userCanContinue()

    marker.on('dragend' , () => {''',
    'search result confirms location',
)

deck_service = REPORTCARDS / 'src/app/services/cards/deck.service.ts'
replace_once(
    deck_service,
    '''  setImageUrl() {
    return this.setImage = true;
  }
''',
    '''  setImageUrl() {
    return this.setImage = true;
  }

  clearImage() {
    this.preview = undefined;
    this.setImage = false;
    this.fileType = '';
    this.imageSignedUrl = 'url_error';
  }
''',
    'clear image state',
)
replace_once(
    deck_service,
    '''  containsTrainingWord(str) {
    const words = this.trainingWords;
    for (const word of words) {
      if (str.toLowerCase().includes(word.toLowerCase())) {
        return true;
      }
    }
    return false;
  }

''',
    '',
    'remove free-text training classifier',
)
replace_once(
    deck_service,
    "      is_training : this.getReportType() === 'training' || this.containsTrainingWord(this.description)",
    "      is_training: this.getReportType() === 'training'",
    'explicit training state only',
)
replace_once(
    deck_service,
    '''  putReport(
    report: any,
''',
    '''  private confirmReportReceived(id: string): Promise<boolean> {
    return this.http
      .get<any>(env.data_server + 'cards/' + id)
      .toPromise()
      .then((response) =>
        !!(response && response.result && response.result.received)
      )
      .catch(() => false);
  }

  private patchReportImage(reportURL: string, id: string): Promise<void> {
    return this.http
      .patch(reportURL, {
        image_url: id,
        image_type: this.fileType,
      })
      .toPromise()
      .then(() => undefined);
  }

  putReport(
    report: any,
''',
    'reconciliation and image patch helpers',
)
replace_once(
    deck_service,
    '''          if (hasPhoto && photoUploaded) {
            // If photo uploaded successfully, patch image_url
            this.http
              .patch(reportURL, {
                // TODO: match server patch handler
                image_url: id,
                image_type: this.fileType,
              })
              .subscribe(
                (patch_success) => {
                  // Proceed to thanks page
                  // thanks_settings.code = 'pass';
                  // router.navigate('thanks');
                  resolve();
                },
                (patch_error) => {
                  // Proceed to thanks page with image upload error notification
                  // thanks_settings.code = 'fail';
                  // router.navigate('thanks');
                  reject();
                }
              );
          } ''',
    '''          if (hasPhoto && photoUploaded) {
            // The image has already been accepted by object storage. Persist
            // its validated extension before completing the report flow.
            this.patchReportImage(reportURL, id).then(resolve).catch(reject);
          } ''',
    'use shared image patch helper',
)
replace_once(
    deck_service,
    '''        (error) => {
          // error_settings.code = put_error.statusCode;
          // error_settings.msg = put_error.statusText;
          // router.navigate('error');
          this.isError = true;
          reject();
        }
''',
    '''        (error) => {
          // A response can be lost after the server commits. Reconcile the
          // one-time card before showing a retryable failure. If a photo was
          // already uploaded, complete its metadata patch after reconciliation.
          this.confirmReportReceived(id).then((received) => {
            if (!received) {
              this.isError = true;
              reject(error);
              return;
            }
            const finish = hasPhoto && photoUploaded
              ? this.patchReportImage(reportURL, id)
              : Promise.resolve();
            finish.then(() => {
              this.isError = false;
              resolve();
            }).catch((patchError) => {
              this.isError = true;
              reject(patchError);
            });
          });
        }
''',
    'response-loss reconciliation',
)

# Decode and canvas-reencode ordinary UI image submissions before upload.
image_ts = REPORTCARDS / 'src/app/components/image-uploader/image-uploader.component.ts'
_, image_newline = read_preserve(image_ts)
image_component = '''import { Component, OnInit } from '@angular/core';
import { DeckService } from '../../services/cards/deck.service'

@Component({
  selector: 'app-image-uploader',
  templateUrl: './image-uploader.component.html',
  styleUrls: ['./image-uploader.component.scss']
})
export class ImageUploaderComponent implements OnInit {
  rotateDeg: number = 0
  imageError = ''
  private readonly allowedTypes = ['image/jpeg', 'image/png']
  private readonly maxBytes = 10 * 1024 * 1024
  private readonly maxPixels = 20 * 1000 * 1000

  constructor(private deckService: DeckService) {}

  ngOnInit() {
    if (this.isImageSelected)
      this.setImagePreview(this.deckService.getPreview())
  }

  get isImageSelected(): boolean {
    return this.deckService.getPreview() ? true : false
  }

  async onFileChanged(event) {
    const input = event.target as HTMLInputElement
    const file = input.files && input.files[0]
    if (!file) return

    this.imageError = ''
    if (this.allowedTypes.indexOf(file.type) === -1) {
      this.rejectFile(input, 'type')
      return
    }
    if (file.size > this.maxBytes) {
      this.rejectFile(input, 'size')
      return
    }

    try {
      // Decode and re-encode before preview or upload. This rejects false MIME
      // declarations and strips EXIF/GPS and other container metadata.
      const sanitized = await this.sanitizeImage(file)
      this.setImagePreview(sanitized)
      this.deckService.setPreview(sanitized)
      this.deckService.setImageUrl()
      this.deckService.updateSignedUrl(sanitized)
    } catch (_error) {
      this.rejectFile(input, 'decode')
    }
  }

  private rejectFile(input: HTMLInputElement, code: string) {
    this.imageError = code
    input.value = ''
    this.deckService.clearImage()
  }

  private sanitizeImage(file: File): Promise<File> {
    return new Promise((resolve, reject) => {
      const image = new Image()
      const objectUrl = URL.createObjectURL(file)
      image.onload = () => {
        try {
          if (!image.naturalWidth || !image.naturalHeight ||
              image.naturalWidth * image.naturalHeight > this.maxPixels) {
            throw new Error('Image dimensions are not supported')
          }
          const canvas = document.createElement('canvas')
          canvas.width = image.naturalWidth
          canvas.height = image.naturalHeight
          const context = canvas.getContext('2d')
          if (!context) throw new Error('Canvas is unavailable')
          context.drawImage(image, 0, 0)
          canvas.toBlob((blob) => {
            URL.revokeObjectURL(objectUrl)
            if (!blob) {
              reject(new Error('Image re-encoding failed'))
              return
            }
            resolve(new File([blob], file.name, {
              type: file.type,
              lastModified: Date.now(),
            }))
          }, file.type, file.type === 'image/jpeg' ? 0.9 : undefined)
        } catch (error) {
          URL.revokeObjectURL(objectUrl)
          reject(error)
        }
      }
      image.onerror = () => {
        URL.revokeObjectURL(objectUrl)
        reject(new Error('The selected file is not a decodable image'))
      }
      image.src = objectUrl
    })
  }

  setImagePreview(file) {
    const reader = new FileReader()
    reader.onload = function (e: any) {
      document.getElementById('image-uploader-picture').setAttribute('src', e.target.result)
    }
    reader.readAsDataURL(file)
  }

  rotateImage() {
    this.rotateDeg += 90
  }

  deletePreview() {
    this.imageError = ''
    this.deckService.clearImage()
  }
}
'''
write_preserve(image_ts, image_component, image_newline)

image_html = REPORTCARDS / 'src/app/components/image-uploader/image-uploader.component.html'
replace_once(
    image_html,
    '  type="file" accept="image/*" id="image-uploader-button" #file\n>',
    '  type="file" accept="image/jpeg,image/png" id="image-uploader-button" #file\n>\n'
    '<p *ngIf="imageError" role="alert" class="image-uploader-error">\n'
    "  {{ ('card.review.imageError.' + imageError) | translate }}\n"
    '</p>',
    'image input restrictions and error',
)
append_once(
    REPORTCARDS / 'src/app/components/image-uploader/image-uploader.component.scss',
    '''
.image-uploader-error {
  color: #fff;
  background: rgba(139, 30, 30, 0.9);
  padding: 8px 12px;
  margin: 8px 0;
  border-radius: 4px;
}
''',
    '.image-uploader-error',
)

# Retry failures in place instead of navigating to a terminal error screen.
submit_ts = REPORTCARDS / 'src/app/components/submit-button/submit-button.component.ts'
replace_once(
    submit_ts,
    '''  isLoading = false;
  isSumbitted = false;
''',
    '''  isLoading = false;
  isSumbitted = false;
  submitError = false;
''',
    'submit error state',
)
replace_once(
    submit_ts,
    '''    if (!this.isSumbitted) {
      this.isSumbitted = true;
      await this.deckService
''',
    '''    if (!this.isSumbitted) {
      this.submitError = false;
      this.isSumbitted = true;
      await this.deckService
''',
    'reset submit error',
)
replace_once(
    submit_ts,
    '''        .catch(() => {
          this.isLoading = false;
          this.navController.next(this.deckService.getRoute());
        });
''',
    '''        .catch(() => {
          this.isLoading = false;
          this.isSumbitted = false;
          this.submitError = true;
        });
''',
    'retryable submit failure',
)
append_once(
    REPORTCARDS / 'src/app/components/submit-button/submit-button.component.html',
    '''
<p *ngIf="submitError" role="alert" class="submit-error">
  {{ 'card.review.submitError' | translate }}
</p>
''',
    'class="submit-error"',
)
append_once(
    REPORTCARDS / 'src/app/components/submit-button/submit-button.component.scss',
    '''
.submit-error {
  color: #fff;
  background: rgba(139, 30, 30, 0.9);
  padding: 8px 12px;
  margin: 8px 10px;
  border-radius: 4px;
}
''',
    '.submit-error',
)

thank_html = REPORTCARDS / 'src/app/routes/cards/thank/thank.component.html'
replace_once(
    thank_html,
    '''
  <p class="thanks__subtitle">
  {{ reportSuccessText.title | translate}} <a href="{{reportUrlText | translate}}">{{reportUrlText | translate}}</a> {{ reportSuccessText.subTitle | translate}}
  </p>
''',
    '\n',
    'remove undefined reportSuccessText block',
)
replace_once(
    thank_html,
    '<h3 class="need_thanks__title"> {{ reportSuccessText.result | translate}}</h3>',
    '<h3 class="need_thanks__title"> {{ reportText.result | translate}}</h3>',
    'use defined reportText result',
)

locale_values = {
    'en': {
        'loading': '      "loading": "Loading..."',
        'submit': 'The report was not confirmed. Check your connection and try again.',
        'type': 'Only JPEG and PNG images are supported.',
        'size': 'The image must be 10 MB or smaller.',
        'decode': 'The selected file could not be decoded as a safe image.',
    },
    'id': {
        'loading': '      "loading": "Sedang memuat..."',
        'submit': 'Laporan belum terkonfirmasi. Periksa koneksi Anda dan coba lagi.',
        'type': 'Hanya gambar JPEG dan PNG yang didukung.',
        'size': 'Ukuran gambar harus 10 MB atau kurang.',
        'decode': 'Berkas yang dipilih tidak dapat dibaca sebagai gambar yang aman.',
    },
}
for locale, values in locale_values.items():
    path = REPORTCARDS / f'deployments/id/assets/locales/{locale}.json'
    replacement = (
        values['loading'] + ',\n'
        f'      "submitError": {json.dumps(values["submit"], ensure_ascii=False)},\n'
        '      "imageError": {\n'
        f'        "type": {json.dumps(values["type"], ensure_ascii=False)},\n'
        f'        "size": {json.dumps(values["size"], ensure_ascii=False)},\n'
        f'        "decode": {json.dumps(values["decode"], ensure_ascii=False)}\n'
        '      }'
    )
    replace_once(path, values['loading'], replacement, f'{locale} error translations')
    json.loads(path.read_text(encoding='utf-8'))

print(json.dumps({
    'server': str(SERVER),
    'reportcards': str(REPORTCARDS),
    'status': 'candidate fixes applied',
}, indent=2))
