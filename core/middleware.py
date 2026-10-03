from django.http import HttpResponsePermanentRedirect

from .auth import load_user


class CurrentUserMiddleware:
    """request.current_user — joriy foydalanuvchi yoki None (sessiya cookie'si bo'lsagina bazaga so'rov)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.current_user = load_user(request)
        return self.get_response(request)


class TrailingSlashMiddleware:
    """/ustalar/ -> /ustalar (asl saytdagi URL'lar oxirgi "/" siz)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if request.method in ("GET", "HEAD") and len(path) > 1 and path.endswith("/") and not path.startswith("/static/"):
            query = request.META.get("QUERY_STRING")
            return HttpResponsePermanentRedirect(path.rstrip("/") + (f"?{query}" if query else ""))
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response
