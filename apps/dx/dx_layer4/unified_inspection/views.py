"""Unified inspection page views."""

from django.shortcuts import render

from apps.dx.dx_layer4.common.context import build_context


def unified_inspection(request):
    """Render the read-only inspection/source-date mapping page."""

    return render(
        request,
        'layer4/unified_inspection.html',
        build_context('unified_inspection', request),
    )
