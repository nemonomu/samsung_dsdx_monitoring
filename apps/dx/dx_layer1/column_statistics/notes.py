"""Shared remarks for a collected column, independent of the inspection date."""
import json
import logging

from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from apps.dx.dx_document.manual import dx_access
from apps.dx.dx_layer1.collection_issues.retry import retry_locked_write
from apps.dx.dx_layer1.models import ColumnStatisticsNote

from .links import selection
from .services import EXCLUDED_COLUMNS


def serialize(note):
    if note is None:
        return None
    return dict(text=note.text, revision=note.revision, created_at=note.created_at.isoformat(),
                updated_at=note.updated_at.isoformat())


def save_note(identity, text, revision):
    with transaction.atomic():
        if revision == 0:
            note, created = ColumnStatisticsNote.objects.get_or_create(**identity, defaults={'text': text})
            return note, created
        notes = ColumnStatisticsNote.objects.filter(**identity)
        updated = notes.filter(revision=revision).update(
            text=text, revision=revision + 1, updated_at=timezone.now())
        return notes.first(), bool(updated)


@dx_access
@require_http_methods(['GET', 'POST'])
@csrf_protect
@never_cache
def notes(request):
    try:
        if request.method == 'GET':
            scope = selection({**request.GET.dict(), 'column': ''})
            scope.pop('column')
            found = ColumnStatisticsNote.objects.filter(**scope)
            return JsonResponse({'notes': {note.column: serialize(note) for note in found}})

        if len(request.body) > 16000:
            return JsonResponse({'error': '비고는 최대 2000자까지 입력할 수 있습니다.'}, status=413)
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError('비고 입력을 확인해주세요.')
        identity = selection(data)
        if not identity['column'] or identity['column'] in EXCLUDED_COLUMNS:
            raise ValueError('수집 항목을 확인해주세요.')
        text, revision = data.get('text'), data.get('revision')
        if not isinstance(text, str) or len(text) > 2000 or '\x00' in text:
            raise ValueError('비고는 최대 2000자까지 입력할 수 있습니다.')
        if type(revision) is not int or not 0 <= revision < 2147483647:
            raise ValueError('저장 버전을 확인해주세요.')

        note, saved = retry_locked_write(lambda: save_note(identity, text.strip(), revision))
        if not saved:
            return JsonResponse({'error': '다른 사용자가 먼저 저장했습니다. 비고를 다시 열어 최신 내용을 확인해주세요.',
                                 'note': serialize(note)}, status=409)
        return JsonResponse({'note': serialize(note)})
    except (json.JSONDecodeError, UnicodeError):
        return JsonResponse({'error': '비고 입력을 확인해주세요.'}, status=400)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except DatabaseError:
        logging.getLogger(__name__).exception('Column statistics note storage failed')
        return JsonResponse({'error': '비고에 접근하지 못했습니다. 잠시 후 다시 시도해주세요.'}, status=503)
