#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
path = root / 'src/app/components/location-picker/location-picker.component.spec.ts'
text = path.read_text(encoding='utf-8')

old_import = "import mapboxgl from 'mapbox-gl';\n"
new_import = "declare const require: any;\n"
if text.count(old_import) != 1:
    raise RuntimeError(f'expected one Mapbox import, found {text.count(old_import)}')
text = text.replace(old_import, new_import, 1)

old_spy = "    spyOn(mapboxgl as any, 'Marker').and.returnValue(marker);\n"
new_spy = """    const mapboxModule = require('mapbox-gl');
    const markerFactory = jasmine.createSpy('Marker').and.returnValue(marker);
    if (mapboxModule.default) {
      mapboxModule.default.Marker = markerFactory;
    } else {
      Object.defineProperty(mapboxModule, 'default', {
        configurable: true,
        value: { Marker: markerFactory },
      });
    }
"""
if text.count(old_spy) != 1:
    raise RuntimeError(f'expected one Mapbox spy, found {text.count(old_spy)}')
text = text.replace(old_spy, new_spy, 1)

path.write_text(text, encoding='utf-8')
print({'status': 'focused Mapbox module setup patched', 'path': str(path)})
