#!/usr/bin/env python3
from pathlib import Path

path = Path('qa/siti-oss-final/reportcards_fix_e2e.mjs')
text = path.read_text(encoding='utf-8')

old_jpeg = "/9j/4QBBRXhpZgAAU0lUSV9BVURJVF9HUFNMYXRpdHVkZT0tNi4xNzUzOTI7R1BTTG9uZ2l0dWRlPTEwNi44MjcxNTM7/+AAEEpGSUYAAQEAAAEAAQAA/9sAQwAFAwQEBAMFBAQEBQUFBgcMCAcHBwcPCwsJDBEPEhIRDxERExYcFxMUGhURERghGBodHR8fHxMXIiQiHiQcHh8e/9sAQwEFBQUHBgcOCAgOHhQRFB4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4e/8AAEQgAAgACAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8A8sooor86P7LP/9k="
new_jpeg = "/9j/4QBBRXhpZgAAU0lUSV9BVURJVF9HUFNMYXRpdHVkZT0tNi4xNzUzOTI7R1BTTG9uZ2l0dWRlPTEwNi44MjcxNTM7/+AAEEpGSUYAAQEAAAEAAQAA/9sAQwADAgIDAgIDAwMDBAMDBAUIBQUEBAUKBwcGCAwKDAwLCgsLDQ4SEA0OEQ4LCxAWEBETFBUVFQwPFxgWFBgSFBUU/9sAQwEDBAQFBAUJBQUJFA0LDRQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU/8AAEQgAAgACAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8A+dKKKK/DD/VM/9k="n
if text.count(old_jpeg) != 1:
    raise SystemExit(f'expected one old JPEG fixture, found {text.count(old_jpeg)}')
text = text.replace(old_jpeg, new_jpeg, 1)

old_assertion = "    signed_content_type_bound: byId['valid-image']?.s3Uploads[0]?.signedHeaders?.includes('content-type') || false,"
new_assertion = """    signed_content_type_bound: (() => {
      const upload = byId['valid-image']?.s3Uploads[0];
      if (!upload) return false;
      const constrainedType = new URL(upload.url).searchParams.get('Content-Type');
      return Boolean(
        upload.signedHeaders?.includes('content-type') ||
        constrainedType === upload.contentType
      );
    })(),"""
if text.count(old_assertion) != 1:
    raise SystemExit(f'expected one signed-content assertion, found {text.count(old_assertion)}')
text = text.replace(old_assertion, new_assertion, 1)

path.write_text(text, encoding='utf-8')
print({'status': 'Gate B harness v2 patched', 'path': str(path)})
