#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()

image_spec = r'''import { ImageUploaderComponent } from './image-uploader.component';

describe('ImageUploaderComponent focused candidate behavior', () => {
  let deckService: any;
  let translate: any;
  let component: ImageUploaderComponent;

  beforeEach(() => {
    deckService = jasmine.createSpyObj('DeckService', [
      'getPreview',
      'setPreview',
      'setImageUrl',
      'updateSignedUrl',
      'clearImage',
    ]);
    deckService.getPreview.and.returnValue(undefined);
    translate = jasmine.createSpyObj('TranslateService', ['instant']);
    translate.instant.and.callFake((key: string) => key);
    component = new ImageUploaderComponent(deckService, translate);
  });

  it('rejects an unsupported MIME type before requesting a signed URL', async () => {
    const input: any = {
      files: [new File(['not-an-image'], 'payload.gif', { type: 'image/gif' })],
      value: 'selected',
    };
    await component.onFileChanged({ target: input } as any);
    expect(component.imageError).toBe('type');
    expect(input.value).toBe('');
    expect(deckService.clearImage).toHaveBeenCalled();
    expect(deckService.updateSignedUrl).not.toHaveBeenCalled();
  });

  it('rejects an image larger than ten megabytes before decoding', async () => {
    const input: any = {
      files: [new File(
        [new ArrayBuffer(10 * 1024 * 1024 + 1)],
        'large.jpg',
        { type: 'image/jpeg' }
      )],
      value: 'selected',
    };
    await component.onFileChanged({ target: input } as any);
    expect(component.imageError).toBe('size');
    expect(deckService.clearImage).toHaveBeenCalled();
    expect(deckService.updateSignedUrl).not.toHaveBeenCalled();
  });

  it('uses only the sanitized file for preview and upload signing', async () => {
    const original = new File(['original'], 'photo.png', { type: 'image/png' });
    const sanitized = new File(['sanitized'], 'photo.png', { type: 'image/png' });
    const input: any = { files: [original], value: 'selected' };
    spyOn<any>(component, 'sanitizeImage').and.returnValue(Promise.resolve(sanitized));
    spyOn(component, 'setImagePreview');

    await component.onFileChanged({ target: input } as any);

    expect(component.setImagePreview).toHaveBeenCalledWith(sanitized);
    expect(deckService.setPreview).toHaveBeenCalledWith(sanitized);
    expect(deckService.setImageUrl).toHaveBeenCalled();
    expect(deckService.updateSignedUrl).toHaveBeenCalledWith(sanitized);
    expect(component.imageError).toBe('');
  });

  it('converts a decode failure into a visible, retryable validation error', async () => {
    const input: any = {
      files: [new File(['broken'], 'broken.jpg', { type: 'image/jpeg' })],
      value: 'selected',
    };
    spyOn<any>(component, 'sanitizeImage').and.returnValue(
      Promise.reject(new Error('decode failed'))
    );

    await component.onFileChanged({ target: input } as any);

    expect(component.imageError).toBe('decode');
    expect(input.value).toBe('');
    expect(deckService.clearImage).toHaveBeenCalled();
  });

  it('clears image state and exposes a translated error message', () => {
    component.imageError = 'type';
    expect(component.imageErrorText).toBe('card.review.imageError.type');
    component.deletePreview();
    expect(component.imageError).toBe('');
    expect(deckService.clearImage).toHaveBeenCalled();
  });
});
'''

location_spec = r'''import mapboxgl from 'mapbox-gl';
import { LocationPickerComponent } from './location-picker.component';

describe('LocationPickerComponent focused candidate behavior', () => {
  let deckService: any;
  let component: LocationPickerComponent;
  let marker: any;

  beforeEach(() => {
    deckService = jasmine.createSpyObj('DeckService', [
      'userCannotBack',
      'userCanContinue',
      'userCannotContinue',
      'setLocation',
      'getLocation',
      'getDeckSubType',
      'setInputAddress',
    ]);
    deckService.location = undefined;
    deckService.getDeckSubType.and.returnValue('flood');

    component = new LocationPickerComponent(
      deckService,
      jasmine.createSpyObj('TranslateService', ['instant']) as any,
      jasmine.createSpyObj('HttpClient', ['get']) as any
    );
    component.type = 'flood';
    component.provider = {
      search: jasmine.createSpy('search').and.returnValue(
        Promise.resolve([{ x: 106.831, y: -6.1701 }])
      ),
    };
    component.map = {
      flyTo: jasmine.createSpy('flyTo'),
      getCenter: jasmine.createSpy('getCenter').and.returnValue({
        lng: 106.827153,
        lat: -6.175392,
      }),
    };
    marker = {
      setLngLat: jasmine.createSpy('setLngLat'),
      addTo: jasmine.createSpy('addTo'),
      on: jasmine.createSpy('on'),
      getLngLat: jasmine.createSpy('getLngLat'),
    };
    marker.setLngLat.and.returnValue(marker);
    marker.addTo.and.returnValue(marker);
    marker.on.and.returnValue(marker);
    spyOn(mapboxgl as any, 'Marker').and.returnValue(marker);
  });

  it('records a selected search result immediately without requiring marker drag', async () => {
    await component.onConfirmSearch('Monumen Nasional');

    expect(component.map.flyTo).toHaveBeenCalledWith({
      center: [106.831, -6.1701],
      essential: true,
    });
    expect(marker.setLngLat).toHaveBeenCalledWith([106.831, -6.1701]);
    expect(deckService.setLocation).toHaveBeenCalledWith({
      lat: -6.1701,
      lng: 106.831,
    });
    expect(deckService.userCanContinue).toHaveBeenCalled();
  });

  it('allows continuation only when a location is already stored', () => {
    deckService.location = undefined;
    component.checkIsUserAbleToContinue();
    expect(deckService.userCannotContinue).toHaveBeenCalled();

    deckService.userCannotContinue.calls.reset();
    deckService.location = { lat: -6.17, lng: 106.83 };
    component.checkIsUserAbleToContinue();
    expect(deckService.userCanContinue).toHaveBeenCalled();
  });
});
'''

submit_spec = r'''import { SubmitButtonComponent } from './submit-button.component';

describe('SubmitButtonComponent focused candidate behavior', () => {
  let deckService: any;
  let navController: any;
  let component: SubmitButtonComponent;

  beforeEach(() => {
    deckService = jasmine.createSpyObj('DeckService', [
      'submit',
      'getRoute',
      'getDescription',
      'getPreview',
      'isCaptchaCleared',
      'getDeckSubType',
      'isPermittedLocation',
      'submitNotificationRequest',
      'submitNeedRequest',
      'submitGiverRequest',
    ]);
    deckService.getRoute.and.returnValue({});
    deckService.getDescription.and.returnValue('report');
    deckService.getPreview.and.returnValue(undefined);
    deckService.isCaptchaCleared.and.returnValue(true);
    deckService.getDeckSubType.and.returnValue('flood');
    deckService.selectedProducts = [];

    navController = jasmine.createSpyObj('NavigationService', [
      'getCurrentRouteName',
      'next',
    ]);
    navController.getCurrentRouteName.and.returnValue('review');

    component = new SubmitButtonComponent(
      deckService,
      navController,
      {} as any,
      { instant: (key: string) => key } as any
    );
  });

  it('keeps a failed submission on the review page and permits retry', async () => {
    deckService.submit.and.returnValue(Promise.reject(new Error('network')));

    await component.submit();

    expect(component.isLoading).toBe(false);
    expect(component.isSumbitted).toBe(false);
    expect(component.submitError).toBe(true);
    expect(navController.next).not.toHaveBeenCalled();
  });

  it('can succeed on a second attempt after a failed first attempt', async () => {
    deckService.submit.and.returnValues(
      Promise.reject(new Error('network')),
      Promise.resolve()
    );

    await component.submit();
    await component.submit();

    expect(deckService.submit).toHaveBeenCalledTimes(2);
    expect(component.submitError).toBe(false);
    expect(component.isLoading).toBe(false);
    expect(navController.next).toHaveBeenCalledTimes(1);
  });

  it('suppresses duplicate clicks while the first submission is pending', async () => {
    let resolveSubmit: () => void;
    const pending = new Promise<void>((resolve) => { resolveSubmit = resolve; });
    deckService.submit.and.returnValue(pending);

    const first = component.submit();
    const second = component.submit();
    expect(deckService.submit).toHaveBeenCalledTimes(1);

    resolveSubmit();
    await Promise.all([first, second]);
    expect(navController.next).toHaveBeenCalledTimes(1);
  });
});
'''

deck_spec = r'''import { Observable } from 'rxjs';
import { DeckService } from './deck.service';

describe('DeckService focused candidate behavior', () => {
  function routeFor(cardId: string): any {
    return { snapshot: { _routerState: { url: '/' + cardId + '/flood' } } };
  }

  it('uses the explicit report type instead of training keywords in description', () => {
    const service = new DeckService({} as any);
    service.route = routeFor('card-1');
    service.type = 'flood';
    service.subType = 'flood';
    service.location = { lat: -6.17, lng: 106.83 };
    service.description = 'This is a test of a real flood report';
    service.reportType = 'real';

    expect(service._get_report_summary().is_training).toBe(false);
    service.reportType = 'training';
    expect(service._get_report_summary().is_training).toBe(true);
  });

  it('clears all image state atomically', () => {
    const service = new DeckService({} as any);
    service.preview = new File(['x'], 'x.png', { type: 'image/png' });
    service.setImage = true;
    service.fileType = 'png';
    service.imageSignedUrl = 'signed';

    service.clearImage();

    expect(service.preview).toBeUndefined();
    expect(service.setImage).toBe(false);
    expect(service.fileType).toBe('');
    expect(service.imageSignedUrl).toBe('url_error');
  });

  it('reconciles a lost success response before reporting failure', async () => {
    const http: any = jasmine.createSpyObj('HttpClient', ['put', 'get', 'patch']);
    http.put.and.returnValue(new Observable((observer) => {
      observer.error(new Error('response lost'));
    }));
    http.get.and.returnValue({
      toPromise: () => Promise.resolve({ result: { received: true } }),
    });
    const service = new DeckService(http);

    await service.putReport({}, 'card-2', false, false);

    expect(http.get).toHaveBeenCalled();
    expect(service.isError).toBe(false);
  });

  it('rejects when reconciliation confirms the report was not received', async () => {
    const http: any = jasmine.createSpyObj('HttpClient', ['put', 'get', 'patch']);
    http.put.and.returnValue(new Observable((observer) => {
      observer.error(new Error('request failed'));
    }));
    http.get.and.returnValue({
      toPromise: () => Promise.resolve({ result: { received: false } }),
    });
    const service = new DeckService(http);
    let rejected = false;

    try {
      await service.putReport({}, 'card-3', false, false);
    } catch (_error) {
      rejected = true;
    }

    expect(rejected).toBe(true);
    expect(service.isError).toBe(true);
  });
});
'''

files = {
    root / 'src/app/components/image-uploader/image-uploader.component.spec.ts': image_spec,
    root / 'src/app/components/location-picker/location-picker.component.spec.ts': location_spec,
    root / 'src/app/components/submit-button/submit-button.component.focused.spec.ts': submit_spec,
    root / 'src/app/services/cards/deck.service.focused.spec.ts': deck_spec,
}
for path, content in files.items():
    path.write_text(content, encoding='utf-8')

print({
    'status': 'focused candidate specs written',
    'root': str(root),
    'files': [str(path.relative_to(root)) for path in files],
})
