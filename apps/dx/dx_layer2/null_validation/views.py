from django.shortcuts import render
from apps.dx.dx_layer2.common.context import build_context


def null_validation(request):
    """NULL 검증"""
    return render(request, 'layer2_null_validation.html', build_context('null_validation', request))


def null_review_log(request):
    """해당값 정상 처리한 NULL 검수 로그"""
    return render(
        request,
        'layer2_null_review_log.html',
        build_context('null_review_log', request),
    )
