from django.urls import path

from apps.accounts.views import csrf_token, login_view, logout_view, me_view

urlpatterns = [
    path("csrf/", csrf_token, name="auth-csrf"),
    path("login/", login_view, name="auth-login"),
    path("logout/", logout_view, name="auth-logout"),
    path("me/", me_view, name="auth-me"),
]
