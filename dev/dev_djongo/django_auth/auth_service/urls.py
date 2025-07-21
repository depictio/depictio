"""auth_service URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
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
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

# API documentation setup
schema_view = get_schema_view(
    openapi.Info(
        title="Authentication API",
        default_version="v1",
        description="API for authentication with Django and MongoDB",
        terms_of_service="https://www.example.com/terms/",
        contact=openapi.Contact(email="contact@example.com"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # Authentication API endpoints
    path("api/auth/", include("authentication.urls")),
    # django-allauth URLs - make sure these come after our custom URLs
    path("accounts/", include("allauth.urls")),
    # API documentation
    path("swagger/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
]

# Add a handler for the Google OAuth callback
from authentication.views import SocialLoginSuccessView

urlpatterns += [
    # Add a success URL that will redirect to the frontend with tokens
    path("social-login-success/", SocialLoginSuccessView.as_view(), name="social_login_success"),
]
