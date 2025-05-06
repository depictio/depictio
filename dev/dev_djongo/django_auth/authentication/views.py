from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.conf import settings
from django.urls import reverse
from .serializers import RegisterSerializer, UserSerializer
from rest_framework_simplejwt.tokens import RefreshToken
import json


class RegisterView(generics.CreateAPIView):
    """
    API endpoint for user registration
    Dash UI will send registration form data to this endpoint
    """
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer


class UserDetailView(generics.RetrieveAPIView):
    """
    API endpoint to get current user details
    Used by Dash to display user information after authentication
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return self.request.user


class LogoutView(APIView):
    """
    API endpoint for user logout
    Since we're not using token blacklisting, this endpoint simply returns a success response.
    The actual logout happens client-side by removing the stored tokens.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        # We don't actually invalidate the token server-side
        # The client is responsible for removing the token from storage
        return Response(
            {"detail": "Logout successful"},
            status=status.HTTP_200_OK
        )


def get_tokens_for_user(user):
    """
    Generate JWT tokens for a user
    """
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class SocialLoginSuccessView(APIView):
    """
    View that handles the redirect after successful social authentication.
    Generates JWT tokens for the authenticated user and redirects to the frontend.
    """
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        try:
            # The user should be authenticated by django-allauth at this point
            if request.user.is_authenticated:
                user = request.user
                
                # Generate JWT tokens
                tokens = get_tokens_for_user(user)
                
                # Redirect to the frontend with tokens as URL parameters
                frontend_url = 'http://localhost:8050'  # Dash frontend URL
                redirect_url = f"{frontend_url}/?access_token={tokens['access']}&refresh_token={tokens['refresh']}&username={user.username}"
                return redirect(redirect_url)
            else:
                return Response(
                    {"error": "Authentication failed"},
                    status=status.HTTP_401_UNAUTHORIZED
                )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
