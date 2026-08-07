#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${GITHUB_WORKSPACE:?}/siti-oss-v3-work"
ART="${GITHUB_WORKSPACE:?}/siti-oss-v3-evidence"
RAW="$ROOT/raw-v2"
PASSING_RESULT_COMMIT="a675a25b5919a30919468db107210b4fe7ed9701"
TESTED_CANDIDATE_HEAD="d3f97708468506d5cd5ea2984805e31fa23be4c8"
SCHEMA_COMMIT="091229bff2a299c31b814979008ebc6df7b428e8"
SERVER_COMMIT="933f345801340027181be21d24671146e3785701"
REPORTCARDS_COMMIT="eaec8b1a2bfe15745077c0e8ad5ff69fbdccc552"

rm -rf "$ROOT" "$ART"
mkdir -p "$ROOT" "$ART"/{logs,patches,test-sources,focused-specs,exif,public-heads,clean-clone}
exec > >(tee "$ART/logs/reproducibility-v3.log") 2>&1

capture() {
  status=$?
  trap - EXIT
  set +e
  printf '%s\n' "$status" > "$ART/workflow-exit.txt"
  find "$ART" -type f -printf '%P\t%s bytes\n' | sort > "$ART/ARTIFACT-INDEX.txt"
  find "$ART" -type f ! -name SHA256SUMS.txt -print0 | sort -z | xargs -0 sha256sum > "$ART/SHA256SUMS.txt"
  ART="$ART" python3 - <<'PY'
from pathlib import Path
import os, zipfile
root = Path(os.environ['ART'])
out = root.parent / 'siti-oss-independent-reproducibility-v3.zip'
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(root.rglob('*')):
        if path.is_file():
            zf.write(path, arcname=str(path.relative_to(root)))
print({'archive': str(out), 'bytes': out.stat().st_size})
PY
  exit "$status"
}
trap capture EXIT

sudo apt-get update
sudo apt-get install -y unzip libimage-exiftool-perl python3-venv
sudo npm install -g n

# Recover and cryptographically verify the untouched passing evidence package.
git show "$PASSING_RESULT_COMMIT:qa/siti-oss-evidence-closure-v2/results/evidence-closure-v2.zip" > "$ROOT/evidence-closure-v2.zip"
mkdir -p "$RAW"
unzip -q "$ROOT/evidence-closure-v2.zip" -d "$RAW"
RAW="$RAW" python3 - <<'PY'
from pathlib import Path
import hashlib, os
root = Path(os.environ['RAW'])
verified = 0
for line in (root / 'SHA256SUMS.txt').read_text().splitlines():
    if not line.strip():
        continue
    expected, rel = line.split(maxsplit=1)
    rel = rel.strip()
    if rel.startswith('artifacts/'):
        rel = rel[len('artifacts/'):]
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f'checksum mismatch: {rel}')
    verified += 1
print({'raw_evidence_sha256_entries_verified': verified})
assert verified == 70, verified
PY
cp "$RAW/diffs/server-candidate-complete.patch" "$ART/patches/"
cp "$RAW/diffs/reportcards-candidate.patch" "$ART/patches/"
cp "$RAW/evidence-closure-v2-summary.json" "$ART/base-functional-closure-summary.json"
sha256sum "$ROOT/evidence-closure-v2.zip" "$ART/patches/"*.patch > "$ART/patches/SHA256SUMS.txt"

# Archive the exact focused-test source used at the tested candidate head.
for path in \
  qa/siti-oss-evidence-closure-v2/write_focused_specs.py \
  qa/siti-oss-evidence-closure-v2/patch_focused_specs_v2.py; do
  git show "$TESTED_CANDIDATE_HEAD:$path" > "$ART/test-sources/$(basename "$path")"
done
sha256sum "$ART/test-sources/"* > "$ART/test-sources/SHA256SUMS.txt"

# Verify that each audited snapshot is still the public default-branch head.
check_public_head() {
  label="$1"
  url="$2"
  branch="$3"
  expected="$4"
  actual="$(git ls-remote "$url" "refs/heads/$branch" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$url" "$branch" "$expected" "$actual" \
    >> "$ART/public-heads/default-heads.tsv"
  test "$actual" = "$expected"
}
printf 'label\trepository\tbranch\texpected\tactual\n' > "$ART/public-heads/default-heads.tsv"
check_public_head schema https://github.com/petabencana/sitioss-schema.git master "$SCHEMA_COMMIT"
check_public_head server https://github.com/petabencana/-Depricated-sitioss-server.git master "$SERVER_COMMIT"
check_public_head reportcards https://github.com/petabencana/sitioss-reportcards-ng.git master "$REPORTCARDS_COMMIT"

# Genuine clean clone: no copied node_modules. Apply exact candidate patch, then
# install from the repository lockfile in the clean clone itself.
git clone --no-tags --single-branch --branch master \
  https://github.com/petabencana/-Depricated-sitioss-server.git "$ROOT/server-clean"
git -C "$ROOT/server-clean" checkout "$SERVER_COMMIT"
test ! -e "$ROOT/server-clean/node_modules"
git -C "$ROOT/server-clean" apply --check "$ART/patches/server-candidate-complete.patch"
git -C "$ROOT/server-clean" apply "$ART/patches/server-candidate-complete.patch"
git -C "$ROOT/server-clean" diff --check
sudo n 10.24.1
hash -r
sudo npm install -g npm@7.24.2
node --version | tee "$ART/clean-clone/server-node-version.txt"
npm --version | tee "$ART/clean-clone/server-npm-version.txt"
(
  cd "$ROOT/server-clean"
  NODE_ENV=development npm ci --include=dev --legacy-peer-deps --no-audit --no-fund
) > "$ART/logs/server-clean-fresh-npm-ci.log" 2>&1
(
  cd "$ROOT/server-clean"
  npm run build
) > "$ART/logs/server-clean-fresh-build.log" 2>&1

git clone --no-tags --single-branch --branch master \
  https://github.com/petabencana/sitioss-reportcards-ng.git "$ROOT/reportcards-clean"
git -C "$ROOT/reportcards-clean" checkout "$REPORTCARDS_COMMIT"
test ! -e "$ROOT/reportcards-clean/node_modules"
git -C "$ROOT/reportcards-clean" apply --check "$ART/patches/reportcards-candidate.patch"
git -C "$ROOT/reportcards-clean" apply "$ART/patches/reportcards-candidate.patch"
git -C "$ROOT/reportcards-clean" -c core.whitespace=cr-at-eol diff --check
sudo n 14.21.3
hash -r
node --version | tee "$ART/clean-clone/reportcards-node-version.txt"
npm --version | tee "$ART/clean-clone/reportcards-npm-version.txt"
(
  cd "$ROOT/reportcards-clean"
  npm ci --no-audit --no-fund
) > "$ART/logs/reportcards-clean-fresh-npm-ci.log" 2>&1
(
  cd "$ROOT/reportcards-clean"
  NODE_OPTIONS=--max_old_space_size=6144 npm run build-dev-id
  NODE_OPTIONS=--max_old_space_size=6144 npm run build-prod-id
) > "$ART/logs/reportcards-clean-fresh-builds.log" 2>&1

# Recreate, archive, and execute the exact 14 focused specs on the genuine clean
# clone. Keep the compatibility type pin test-only and do not alter the patch.
(
  cd "$ROOT/reportcards-clean"
  npm install --no-save --no-package-lock --no-audit --no-fund @types/jasmine@2.8.16
) > "$ART/logs/reportcards-focused-type-pin.log" 2>&1
python3 "$ART/test-sources/write_focused_specs.py" "$ROOT/reportcards-clean" \
  > "$ART/logs/write-focused-specs.log"
python3 "$ART/test-sources/patch_focused_specs_v2.py" "$ROOT/reportcards-clean" \
  > "$ART/logs/patch-focused-specs.log"
cp "$ROOT/reportcards-clean/src/app/components/image-uploader/image-uploader.component.spec.ts" "$ART/focused-specs/"
cp "$ROOT/reportcards-clean/src/app/components/location-picker/location-picker.component.spec.ts" "$ART/focused-specs/"
cp "$ROOT/reportcards-clean/src/app/components/submit-button/submit-button.component.focused.spec.ts" "$ART/focused-specs/"
cp "$ROOT/reportcards-clean/src/app/services/cards/deck.service.focused.spec.ts" "$ART/focused-specs/"
sha256sum "$ART/focused-specs/"* > "$ART/focused-specs/SHA256SUMS.txt"
python3 - "$ROOT/reportcards-clean/src/test.ts" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
old = r"/\.spec\.ts$/"
new = r"/(image-uploader\.component\.spec|location-picker\.component\.spec|submit-button\.component\.focused\.spec|deck\.service\.focused\.spec)\.ts$/"
if text.count(old) != 1:
    raise RuntimeError(f'expected one test regex, found {text.count(old)}')
path.write_text(text.replace(old, new, 1))
PY

# Use Playwright's pinned Chromium build for the unit gate rather than the
# mutable Chrome bundled with the hosted runner image.
sudo n 20.19.1
hash -r
mkdir -p "$ROOT/pinned-browser"
(
  cd "$ROOT/pinned-browser"
  npm init -y >/dev/null
  npm install --no-save playwright@1.54.1
  npx playwright install --with-deps chromium
) > "$ART/logs/pinned-playwright-install.log" 2>&1
PINNED_CHROME="$(cd "$ROOT/pinned-browser" && node -e "console.log(require('playwright').chromium.executablePath())")"
"$PINNED_CHROME" --version | tee "$ART/clean-clone/focused-unit-browser-version.txt"
sudo n 14.21.3
hash -r
set +e
(
  cd "$ROOT/reportcards-clean"
  CHROME_BIN="$PINNED_CHROME" NODE_OPTIONS=--max_old_space_size=6144 \
    timeout 15m node --max_old_space_size=6144 \
    ./node_modules/@angular/cli/bin/ng test --watch=false \
    --browsers=ChromeHeadlessNoSandbox --code-coverage=false \
    --source-map=false --progress=false
) > "$ART/logs/focused-unit-fresh-clone-pinned-chromium.log" 2>&1
focused_exit=$?
set -e
printf '%s\n' "$focused_exit" > "$ART/clean-clone/focused-unit.exit"
test "$focused_exit" -eq 0
grep -q 'TOTAL: 14 SUCCESS' "$ART/logs/focused-unit-fresh-clone-pinned-chromium.log"
if grep -q 'FAILED' "$ART/logs/focused-unit-fresh-clone-pinned-chromium.log"; then
  exit 1
fi

# Independent EXIF verification: reconstruct the pinned fixture from the exact
# code and Pillow version, compare it with the archived fixture description,
# then parse both the reconstructed source and the actual stored output using
# ExifTool rather than Pillow.
python3 -m venv "$ROOT/exif-venv"
. "$ROOT/exif-venv/bin/activate"
pip install --disable-pip-version-check pillow==10.4.0 \
  > "$ART/logs/pillow-install.log" 2>&1
RAW="$RAW" ART="$ART" python3 - <<'PY'
from pathlib import Path
import hashlib, json, os
from PIL import Image, TiffImagePlugin
raw = Path(os.environ['RAW'])
art = Path(os.environ['ART'])
image = Image.new('RGB', (16, 16), (53, 105, 142))
exif = Image.Exif()
exif[34853] = {
    1: 'S',
    2: (
        TiffImagePlugin.IFDRational(6, 1),
        TiffImagePlugin.IFDRational(10, 1),
        TiffImagePlugin.IFDRational(3141, 100),
    ),
    3: 'E',
    4: (
        TiffImagePlugin.IFDRational(106, 1),
        TiffImagePlugin.IFDRational(49, 1),
        TiffImagePlugin.IFDRational(3771, 100),
    ),
}
path = art / 'exif/reconstructed-pillow-10.4.0-source-gps.jpg'
image.save(path, format='JPEG', quality=92, exif=exif)
parsed = Image.open(path).getexif().get_ifd(34853)
result = {
    'path': str(path),
    'bytes': path.stat().st_size,
    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'has_exif_header': b'Exif\x00\x00' in path.read_bytes(),
    'gps_ifd': {str(k): str(v) for k, v in parsed.items()},
    'gps_tag_present': bool(parsed),
    'reconstruction_note': 'Reconstructed from the exact pinned Pillow 10.4.0 fixture code; the original source JPEG was not archived by v2.',
}
expected = json.loads((raw / 'exif/original-exif-verification.json').read_text())
assert result['bytes'] == expected['bytes'] == 772, (result, expected)
assert result['has_exif_header'] == expected['has_exif_header'] is True
assert result['gps_ifd'] == expected['gps_ifd'], (result, expected)
assert result['gps_tag_present'] == expected['gps_tag_present'] is True
(art / 'exif/reconstructed-source-pillow-verification.json').write_text(json.dumps(result, indent=2))
PY
exiftool -json -n -G1 -a -s "$ART/exif/reconstructed-pillow-10.4.0-source-gps.jpg" \
  > "$ART/exif/reconstructed-source-exiftool.json"
exiftool -json -n -G1 -a -s "$RAW/browser-v2/true-exif-gps-image-real-storage-upload-1.bin" \
  > "$ART/exif/actual-stored-output-exiftool.json"
RAW="$RAW" ART="$ART" python3 - <<'PY'
from pathlib import Path
import hashlib, json, os
raw = Path(os.environ['RAW'])
art = Path(os.environ['ART'])
source = json.loads((art / 'exif/reconstructed-source-exiftool.json').read_text())[0]
stored = json.loads((art / 'exif/actual-stored-output-exiftool.json').read_text())[0]
source_keys = {key.split(']')[-1].lstrip(':'): value for key, value in source.items()}
stored_keys = {key.split(']')[-1].lstrip(':'): value for key, value in stored.items()}
assert 'GPSLatitude' in source_keys and 'GPSLongitude' in source_keys, source_keys
assert str(source_keys.get('GPSLatitudeRef', '')).upper() in {'S', 'SOUTH'}, source_keys
assert str(source_keys.get('GPSLongitudeRef', '')).upper() in {'E', 'EAST'}, source_keys
for key in stored_keys:
    if key.startswith('GPS'):
        raise AssertionError({'unexpected_stored_gps_key': key, 'value': stored_keys[key]})
actual_output = raw / 'browser-v2/true-exif-gps-image-real-storage-upload-1.bin'
result = {
    'independent_parser': 'ExifTool',
    'source_gps_detected': True,
    'stored_gps_absent': True,
    'stored_output_sha256': hashlib.sha256(actual_output.read_bytes()).hexdigest(),
    'stored_output_bytes': actual_output.stat().st_size,
    'stored_file_type': stored_keys.get('FileType'),
    'stored_mime_type': stored_keys.get('MIMEType'),
}
(art / 'exif/independent-exiftool-verification.json').write_text(json.dumps(result, indent=2))
PY
deactivate
exiftool -ver | tee "$ART/exif/exiftool-version.txt"

# Final strict summary. Every boolean below is backed by a preceding fail-fast
# command, not a manually asserted narrative field.
ART="$ART" RAW="$RAW" \
PASSING_RESULT_COMMIT="$PASSING_RESULT_COMMIT" \
TESTED_CANDIDATE_HEAD="$TESTED_CANDIDATE_HEAD" \
SCHEMA_COMMIT="$SCHEMA_COMMIT" SERVER_COMMIT="$SERVER_COMMIT" \
REPORTCARDS_COMMIT="$REPORTCARDS_COMMIT" python3 - <<'PY'
from pathlib import Path
import hashlib, json, os
art = Path(os.environ['ART'])
raw = Path(os.environ['RAW'])
base = json.loads((raw / 'evidence-closure-v2-summary.json').read_text())
exif = json.loads((art / 'exif/independent-exiftool-verification.json').read_text())
result = {
    'passing_functional_result_commit': os.environ['PASSING_RESULT_COMMIT'],
    'tested_candidate_head': os.environ['TESTED_CANDIDATE_HEAD'],
    'exact_public_sources': {
        'schema': os.environ['SCHEMA_COMMIT'],
        'server': os.environ['SERVER_COMMIT'],
        'reportcards': os.environ['REPORTCARDS_COMMIT'],
    },
    'base_functional_closure_core_pass': base['core_pass'],
    'raw_evidence_sha256_entries_verified': 70,
    'public_default_heads_match_exact_sources': True,
    'server_clean_clone_fresh_npm_ci_build': True,
    'reportcards_clean_clone_fresh_npm_ci_builds': True,
    'focused_test_sources_archived': True,
    'focused_units_on_fresh_clone_with_pinned_chromium': {
        'executed': 14,
        'passed': 14,
        'exit_code': int((art / 'clean-clone/focused-unit.exit').read_text().strip()),
    },
    'independent_exiftool_verification': exif,
    'patch_sha256': {
        'server': hashlib.sha256((art / 'patches/server-candidate-complete.patch').read_bytes()).hexdigest(),
        'reportcards': hashlib.sha256((art / 'patches/reportcards-candidate.patch').read_bytes()).hexdigest(),
    },
    'limits': [
        'No current-production source mapping was established.',
        'No production AWS bucket, live report, or beneficiary data was touched.',
        'No Siti OSS maintainer review, upstream acceptance, merge, or deployment was established.',
        'The original v2 source JPEG was not archived; v3 independently validates a deterministic reconstruction from the exact pinned fixture code and the actual stored output bytes.',
    ],
}
result['core_pass'] = (
    result['base_functional_closure_core_pass'] is True and
    result['public_default_heads_match_exact_sources'] is True and
    result['server_clean_clone_fresh_npm_ci_build'] is True and
    result['reportcards_clean_clone_fresh_npm_ci_builds'] is True and
    result['focused_units_on_fresh_clone_with_pinned_chromium']['exit_code'] == 0 and
    result['independent_exiftool_verification']['source_gps_detected'] is True and
    result['independent_exiftool_verification']['stored_gps_absent'] is True
)
(art / 'independent-reproducibility-v3-summary.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
assert result['core_pass'], result
PY
