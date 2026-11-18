"""
로그인 필수 및 권한 체크 미들웨어
모든 페이지에 로그인이 필요하도록 설정
DS/DX 페이지별 접근 권한 체크
"""

from django.shortcuts import redirect, render
from django.urls import reverse
from django.http import HttpResponseForbidden
import re


class LoginRequiredMiddleware:
    """
    로그인하지 않은 사용자는 로그인 페이지로 리다이렉트
    DS/DX 페이지별 접근 권한 체크
    """

    # 로그인 없이 접근 가능한 URL 패턴
    EXEMPT_URLS = [
        r'^/accounts/login/?$',
        r'^/accounts/session-status/?$',  # 만료 시 리다이렉트 대신 JSON 응답
        r'^/admin/',
        r'^/static/',
        r'^/api/health/?$',  # 헬스체크 API
        r'^/dx-share/',  # DX 공개 문서 공유 링크 + 공유 이미지 프록시
        r'^/ds-share/',  # DS 공개 문서 공유 링크 + 공유 이미지 프록시
    ]

    # DX 페이지 패턴
    DX_URLS = [
        r'^/dx/',
    ]

    # DS 페이지 패턴
    DS_URLS = [
        r'^/ds/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_urls = [re.compile(url) for url in self.EXEMPT_URLS]
        self.dx_urls = [re.compile(url) for url in self.DX_URLS]
        self.ds_urls = [re.compile(url) for url in self.DS_URLS]

    def __call__(self, request):
        # 로그인 페이지 및 예외 URL은 통과
        path = request.path_info

        for pattern in self.exempt_urls:
            if pattern.match(path):
                return self.get_response(request)

        # 로그인하지 않은 경우 로그인 페이지로 리다이렉트
        if not request.user.is_authenticated:
            login_url = reverse('accounts:login')
            # 현재 URL을 next 파라미터로 전달
            if path != '/':
                login_url = f"{login_url}?next={path}"
            return redirect(login_url)

        # 관리자는 모든 페이지 접근 가능
        if request.user.is_staff or request.user.is_superuser:
            return self.get_response(request)

        # DS/DX 권한 체크
        try:
            profile = request.user.profile
        except:
            # 프로필이 없으면 생성
            from .models import UserProfile
            profile = UserProfile.objects.create(user=request.user)

        # DX 페이지 접근 권한 체크
        for pattern in self.dx_urls:
            if pattern.match(path):
                if not profile.can_access_dx:
                    return render(request, 'accounts/access_denied.html', {
                        'message': 'DX 페이지에 접근할 권한이 없습니다.',
                        'required_permission': 'DX'
                    }, status=403)

        # DS 페이지 접근 권한 체크
        for pattern in self.ds_urls:
            if pattern.match(path):
                if not profile.can_access_ds:
                    return render(request, 'accounts/access_denied.html', {
                        'message': 'DS 페이지에 접근할 권한이 없습니다.',
                        'required_permission': 'DS'
                    }, status=403)

        return self.get_response(request)
