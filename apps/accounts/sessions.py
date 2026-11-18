"""Expose the persisted DB session deadline without renewing timer probes."""

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_cookie


def expiry_cookie_name():
    return settings.SESSION_COOKIE_NAME + '_expires'


def stored_expiry(request):
    return Session.objects.filter(
        session_key=request.session.session_key,
    ).values_list('expire_date', flat=True).first()


class SessionExpiryMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        # Status reads must not invoke SAVE_EVERY_REQUEST, including 405 responses.
        match = getattr(request, 'resolver_match', None)
        if match and match.func is session_status:
            return response

        response = super().process_response(request, response)
        cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
        if cookie is None:
            return response

        if str(cookie['max-age']) == '0':
            response.delete_cookie(
                expiry_cookie_name(), path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
        elif getattr(request, 'user', None) and request.user.is_authenticated:
            # Read after Django saves: get_expiry_date() alone would calculate a
            # new relative deadline instead of reading the actual DB deadline.
            expires = stored_expiry(request)
            if expires is not None:
                response.set_cookie(
                    expiry_cookie_name(), str(int(expires.timestamp() * 1000)),
                    max_age=cookie['max-age'] or None,
                    expires=cookie['expires'] or None,
                    path=settings.SESSION_COOKIE_PATH,
                    domain=settings.SESSION_COOKIE_DOMAIN,
                    secure=settings.SESSION_COOKIE_SECURE,
                    httponly=False, samesite=settings.SESSION_COOKIE_SAMESITE,
                )
        return response


@never_cache
@vary_on_cookie
@require_GET
def session_status(request):
    expires = stored_expiry(request) if request.user.is_authenticated else None
    now = timezone.now()
    if expires is None or expires <= now:
        return JsonResponse({'authenticated': False}, status=401)
    return JsonResponse({
        'authenticated': True,
        'expiresAt': int(expires.timestamp() * 1000),
        'serverTime': int(now.timestamp() * 1000),
        'expiryCookie': expiry_cookie_name(),
    })
