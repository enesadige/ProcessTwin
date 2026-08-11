import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User


def _user_payload(user: User) -> dict[str, str | int]:
    return {"id": user.pk, "username": user.get_username(), "email": user.email, "role": user.role}


@require_GET
@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({"detail": "CSRF cookie ready."})


@require_POST
def login_view(request):
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Invalid request."}, status=400)

    identifier = str(payload.get("username", payload.get("email", ""))).strip()
    password = payload.get("password")
    if not identifier or not isinstance(password, str) or not password:
        return JsonResponse({"detail": "Username and password are required."}, status=400)

    user = authenticate(request, username=identifier, password=password)
    if user is None and "@" in identifier:
        account = User.objects.filter(email__iexact=identifier).first()
        if account is not None:
            user = authenticate(request, username=account.get_username(), password=password)
    if user is None or not user.is_active:
        return JsonResponse({"detail": "Invalid username or password."}, status=401)

    login(request, user)
    return JsonResponse({"user": _user_payload(user)})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"detail": "Logged out."})


@require_GET
def me_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    return JsonResponse({"user": _user_payload(request.user)})
