from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from .serializers import RegisterSerializer, UserSerializer
from rest_framework_simplejwt.tokens import RefreshToken


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
