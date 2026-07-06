"""
URL configuration for wgadminui project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # django-allauth (login, logout, email verification, MFA, passkeys)
    path("accounts/", include("allauth.urls")),
    # django-invitations
    path("invitations/", include("invitations.urls", namespace="invitations")),
    # i18n
    path("i18n/", include("django.conf.urls.i18n")),
    # Our dashboard app (catches everything else)
    path("", include("dashboard.urls")),
]
