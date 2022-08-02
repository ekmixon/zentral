# adapted from https://github.com/mozilla/django-csp
from functools import partial
from django.conf import settings
from django.utils.crypto import get_random_string
from django.utils.functional import SimpleLazyObject
from http.client import INTERNAL_SERVER_ERROR, NOT_FOUND


CSP_HEADER = 'Content-Security-Policy'


DEFAULT_CSP_POLICIES = {
  "default-src": "'self'",
  "script-src": "'self'",
  "base-uri": "'none'",
  "frame-ancestors": "'none'",
  "object-src": "'none'",
  "style-src": "'self' 'unsafe-inline'",
}


def make_csp_nonce(request, length=16):
    if not getattr(request, '_csp_nonce', None):
        request._csp_nonce = get_random_string(length)
    return request._csp_nonce


def build_csp_header(request):
    csp_policies = DEFAULT_CSP_POLICIES.copy()
    if csp_nonce := getattr(request, '_csp_nonce', None):
        csp_policies["script-src"] += f" 'nonce-{csp_nonce}'"
    return ";".join(f"{k} {v}" for k, v in csp_policies.items())


def csp_middleware(get_response):
    def middleware(request):
        nonce_func = partial(make_csp_nonce, request)
        request.csp_nonce = SimpleLazyObject(nonce_func)

        response = get_response(request)

        if CSP_HEADER in response:
            # header already present (HOW ???)
            return response

        if response.status_code in (INTERNAL_SERVER_ERROR, NOT_FOUND) and settings.DEBUG:
            # no policies in debug views
            return response

        response[CSP_HEADER] = build_csp_header(request)

        return response

    return middleware


def deployment_info_middleware(get_response):
    deployment_info = {}
    try:
        import base.deployment as deployment
    except ImportError:
        pass
    else:
        for attr in ("version", "image_id", "instance_id", "setup_at"):
            val = getattr(deployment, attr, None)
            if val is not None:
                deployment_info[attr] = val

    def middleware(request):
        request.zentral_deployment = deployment_info
        return get_response(request)

    return middleware
