#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEGACY = Path(os.environ.get('SITI_LEGACY_AUDIT_SCRIPTS', 'qa/siti-oss-final'))
SERVER = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
REPORTCARDS = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))

# Apply the previously reviewed candidate patch stack first.
runpy.run_path(str(LEGACY / 'apply_gate_fixes_v3.py'), run_name='__main__')


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


# The raw CommonJS entrypoint is injected as a browser-global script by
# angular.json and executes `exports.*` without a CommonJS wrapper. Use the
# package's browser UMD bundle instead.
angular_json = REPORTCARDS / 'angular.json'
replace_once(
    angular_json,
    'node_modules/leaflet-geosearch/lib/index.js',
    'node_modules/leaflet-geosearch/dist/bundle.min.js',
    'browser-safe leaflet-geosearch bundle',
)

# Permit an S3-compatible endpoint only when explicitly configured. Production
# defaults remain unchanged, while the isolated validation can exercise real
# signature enforcement against MinIO rather than intercepting the PUT.
config_js = SERVER / 'src/config.js'
replace_once(
    config_js,
    "  AWS_S3_SIGNATURE_VERSION: process.env.AWS_SIGNATURE_VERSION || 'v4',\n",
    "  AWS_S3_SIGNATURE_VERSION: process.env.AWS_SIGNATURE_VERSION || 'v4',\n"
    "  AWS_S3_ENDPOINT: process.env.AWS_S3_ENDPOINT || '',\n"
    "  AWS_S3_FORCE_PATH_STYLE: process.env.AWS_S3_FORCE_PATH_STYLE === 'true' || false,\n"
    "  AWS_SESSION_TOKEN: process.env.AWS_SESSION_TOKEN || '',\n",
    'optional S3-compatible endpoint configuration',
)

# AWS SDK v2 hoists ContentType into a query parameter for S3 presigned PUTs
# but does not include content-type in X-Amz-SignedHeaders. Generate the narrow
# SigV4 PUT contract explicitly so a changed or missing Content-Type invalidates
# the signature at S3 itself.
presigner = SERVER / 'src/lib/presignPutObject.js'
presigner.write_text(r'''/**
 * SigV4 PUT presigner with an enforced Content-Type header.
 * @module src/lib/presignPutObject
 */
const crypto = require("crypto");
const URLParser = require("url").URL;

/**
 * Apply AWS RFC3986 encoding.
 * @param {String} value Raw value
 * @return {String} Encoded value
 */
function encode(value) {
  return encodeURIComponent(value).replace(/[!'()*]/g, (character) =>
    "%" + character.charCodeAt(0).toString(16).toUpperCase()
  );
}

/**
 * Encode an S3 path while preserving separators.
 * @param {String} value Path value
 * @return {String} Canonical URI
 */
function encodePath(value) {
  return value.split("/").map((part) => encode(part)).join("/");
}

/**
 * Return a SHA-256 hex digest.
 * @param {String} value Value to hash
 * @return {String} Hex digest
 */
function sha256(value) {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}

/**
 * Return an HMAC digest.
 * @param {Buffer|String} key HMAC key
 * @param {String} value Value to sign
 * @param {String} encoding Optional digest encoding
 * @return {Buffer|String} Digest
 */
function hmac(key, value, encoding) {
  return crypto.createHmac("sha256", key)
    .update(value, "utf8")
    .digest(encoding);
}

/**
 * Build an S3 request target.
 * @param {Object} config Server configuration
 * @param {String} bucket Bucket name
 * @param {String} key Object key
 * @return {Object} Target properties
 */
function target(config, bucket, key) {
  if (config.AWS_S3_ENDPOINT) {
    const parsed = new URLParser(config.AWS_S3_ENDPOINT);
    const basePath = parsed.pathname.replace(/\/$/, "");
    if (config.AWS_S3_FORCE_PATH_STYLE) {
      return {
        protocol: parsed.protocol,
        host: parsed.host,
        uri: basePath + "/" + encode(bucket) + "/" + encodePath(key),
      };
    }
    return {
      protocol: parsed.protocol,
      host: encode(bucket) + "." + parsed.host,
      uri: basePath + "/" + encodePath(key),
    };
  }

  const host = config.AWS_REGION === "us-east-1" ?
    bucket + ".s3.amazonaws.com" :
    bucket + ".s3." + config.AWS_REGION + ".amazonaws.com";
  return {
    protocol: "https:",
    host: host,
    uri: "/" + encodePath(key),
  };
}

/**
 * Generate a presigned PUT whose Content-Type is part of SignedHeaders.
 * @param {Object} config Server configuration
 * @param {String} bucket Bucket name
 * @param {String} key Object key
 * @param {String} contentType Required Content-Type
 * @param {Number} expires Validity in seconds
 * @return {Object} Signed and public object URLs
 */
export default function presignPutObject(
  config,
  bucket,
  key,
  contentType,
  expires = 900
) {
  const requestTarget = target(config, bucket, key);
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, "");
  const date = amzDate.slice(0, 8);
  const scope = date + "/" + config.AWS_REGION + "/s3/aws4_request";
  const signedHeaders = "content-type;host";
  const parameters = [
    ["X-Amz-Algorithm", "AWS4-HMAC-SHA256"],
    ["X-Amz-Credential", config.AWS_S3_ACCESS_KEY_ID + "/" + scope],
    ["X-Amz-Date", amzDate],
    ["X-Amz-Expires", String(expires)],
    ["X-Amz-SignedHeaders", signedHeaders],
  ];
  if (config.AWS_SESSION_TOKEN) {
    parameters.push(["X-Amz-Security-Token", config.AWS_SESSION_TOKEN]);
  }
  const canonicalQuery = parameters
    .map((entry) => encode(entry[0]) + "=" + encode(entry[1]))
    .sort()
    .join("&");
  const canonicalHeaders =
    "content-type:" + contentType.trim() + "\n" +
    "host:" + requestTarget.host.toLowerCase() + "\n";
  const canonicalRequest =
    "PUT\n" + requestTarget.uri + "\n" + canonicalQuery + "\n" +
    canonicalHeaders + "\n" + signedHeaders + "\nUNSIGNED-PAYLOAD";
  const stringToSign =
    "AWS4-HMAC-SHA256\n" + amzDate + "\n" + scope + "\n" +
    sha256(canonicalRequest);
  const dateKey = hmac("AWS4" + config.AWS_S3_SECRET_ACCESS_KEY, date);
  const regionKey = hmac(dateKey, config.AWS_REGION);
  const serviceKey = hmac(regionKey, "s3");
  const signingKey = hmac(serviceKey, "aws4_request");
  const signature = hmac(signingKey, stringToSign, "hex");
  const base = requestTarget.protocol + "//" + requestTarget.host +
    requestTarget.uri;

  return {
    signedRequest: base + "?" + canonicalQuery +
      "&X-Amz-Signature=" + signature,
    objectUrl: base,
  };
}
''', encoding='utf-8')

cards_route = SERVER / 'src/api/routes/cards/index.js'
replace_once(
    cards_route,
    'import AWS from "aws-sdk";',
    'import presignPutObject from "../../../lib/presignPutObject";',
    'use strict content-type presigner',
)
replace_once(
    cards_route,
    '''  // Create an S3 object
  let s3 = new AWS.S3({
    accessKeyId: config.AWS_S3_ACCESS_KEY_ID,
    secretAccessKey: config.AWS_S3_SECRET_ACCESS_KEY,
    signatureVersion: config.AWS_S3_SIGNATURE_VERSION,
    region: config.AWS_REGION,
  });

''',
    '',
    'remove AWS SDK v2 S3 presigner',
)
replace_once(
    cards_route,
    '''            // Call AWS S3 library
            s3.getSignedUrl("putObject", s3params, (err, data) => {
              let returnData;
              if (err) {
                /* istanbul ignore next */
                logger.error("could not get signed url from S3");
                /* istanbul ignore next */
                logger.error(err);
                returnData = { statusCode: 500, error: err };
              } else {
                returnData = {
                  signedRequest: data,
                  url:
                    "https://s3." +
                    config.AWS_REGION +
                    ".amazonaws.com/" +
                    config.IMAGES_BUCKET +
                    "/" +
                    s3params.Key,
                };
                // Return signed URL
                clearCache();
                logger.debug("s3 signed request: " + returnData.signedRequest);
                res.write(JSON.stringify(returnData));
                res.end();
              }
            });''',
    '''            try {
              const signed = presignPutObject(
                config,
                s3params.Bucket,
                s3params.Key,
                s3params.ContentType
              );
              const returnData = {
                signedRequest: signed.signedRequest,
                url: signed.objectUrl,
              };
              clearCache();
              logger.debug("s3 signed request generated");
              res.status(200).json(returnData);
            } catch (err) {
              /* istanbul ignore next */
              logger.error("could not get signed url for S3");
              /* istanbul ignore next */
              logger.error(err);
              res.status(500).json({
                statusCode: 500,
                error: "Could not generate image upload URL",
              });
            }''',
    'replace hoisted Content-Type presigning',
)

print(json.dumps({
    'status': 'completion fixes applied',
    'server': str(SERVER),
    'reportcards': str(REPORTCARDS),
    'changes': [
        'browser-safe leaflet-geosearch UMD bundle',
        'explicit SigV4 content-type signed PUT contract',
        'optional S3-compatible endpoint for enforcement testing',
    ],
}, indent=2))
