import secrets

from django.contrib.auth import password_validation
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .google import GoogleTokenError, verify_google_token
from .models import PasswordResetCode, TechnicianProfile, User
from .serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    LogoutSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSerializer,
    VerifyCodeSerializer,
)

RESET_SALT = 'password-reset'
RESET_TOKEN_MAX_AGE = 15 * 60  # seconds


def tokens_for(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh['role'] = user.role
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


@extend_schema(tags=['Auth'])
class RegisterView(generics.CreateAPIView):
    """Create a customer or technician account and sign in straight away."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth'

    @extend_schema(responses={201: OpenApiResponse(description='The new user plus `access` and `refresh` tokens.')})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        body = {**tokens_for(user), 'user': UserSerializer(user, context={'request': request}).data}
        return Response(body, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Auth'])
class LoginView(TokenObtainPairView):
    """Sign in with email and password. Returns `access`, `refresh` and the user."""

    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth'


@extend_schema(tags=['Auth'], request=GoogleLoginSerializer)
class GoogleLoginView(APIView):
    """Sign in (or sign up) with a Google ID token. Returns `access`, `refresh` and the user.

    `role` only matters for a brand-new account; an existing account keeps its role, and signing
    in to the other app with it is refused.
    """

    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth'

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claims = verify_google_token(serializer.validated_data['id_token'])
        except GoogleTokenError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        email = claims['email'].strip().lower()
        requested_role = serializer.validated_data.get('role')
        role = requested_role or User.Role.CUSTOMER
        created = False
        with transaction.atomic():
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email, password=None, role=role, full_name=(claims.get('name') or email.split('@')[0])[:150]
                )
                if role == User.Role.TECHNICIAN:
                    TechnicianProfile.objects.create(user=user)
                created = True
        if not user.is_active:
            return Response({'detail': 'This account is disabled.'}, status=status.HTTP_401_UNAUTHORIZED)
        if requested_role and user.role != requested_role:
            return Response(
                {'role': f'This is a {user.get_role_display().lower()} account. Please use the {user.role} sign-in.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        body = {**tokens_for(user), 'user': UserSerializer(user, context={'request': request}).data, 'created': created}
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@extend_schema(tags=['Auth'], request=LogoutSerializer, responses={204: None})
class LogoutView(APIView):
    """Invalidate a refresh token so it can't be used again."""

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data['refresh']).blacklist()
        except TokenError:
            pass  # Already expired or blacklisted: the goal (signed out) is met either way.
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=['Profile'])
class MeView(generics.RetrieveUpdateAPIView):
    """The signed-in user's profile. PATCH to edit it; send multipart form data to change the photo."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_serializer_class(self):
        return ProfileUpdateSerializer if self.request.method == 'PATCH' else UserSerializer

    def get_object(self):
        return self.request.user

    @extend_schema(request=ProfileUpdateSerializer, responses=UserSerializer)
    def patch(self, request, *args, **kwargs):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user, context={'request': request}).data)


@extend_schema(tags=['Profile'], request=ChangePasswordSerializer, responses={204: None})
class ChangePasswordView(APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- password reset: 1) email a code, 2) verify it, 3) set a new password ----

@extend_schema(tags=['Password reset'], request=ForgotPasswordSerializer, responses={200: OpenApiResponse(description='Always succeeds, so nobody can discover which emails have accounts.')})
class ForgotPasswordView(APIView):
    """Email a 6-digit code to the address if it belongs to an account (valid for 10 minutes)."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            code = f'{secrets.randbelow(10**6):06d}'
            PasswordResetCode.issue(user, code)
            send_mail(
                subject='Your Volvo password reset code',
                message=(
                    f'Hi {user.first_name or "there"},\n\n'
                    f'Your password reset code is {code}. It expires in 10 minutes.\n\n'
                    'If you didn\'t ask for this, you can ignore this email.'
                ),
                from_email=None,
                recipient_list=[user.email],
                fail_silently=True,
            )
        return Response({'detail': 'If that email has an account, a code is on its way.'})


@extend_schema(tags=['Password reset'], request=VerifyCodeSerializer, responses={200: OpenApiResponse(description='Returns a short-lived `reset_token`.')})
class VerifyResetCodeView(APIView):
    """Check the 6-digit code. On success returns a `reset_token` to use in the last step."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        code = serializer.validated_data['code']

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        reset = user.reset_codes.filter(used=False).first() if user else None
        if not reset or not reset.verify(code):
            return Response({'code': ['That code is incorrect or has expired.']}, status=status.HTTP_400_BAD_REQUEST)

        token = signing.dumps({'uid': user.pk, 'reset': reset.pk}, salt=RESET_SALT)
        return Response({'reset_token': token})


@extend_schema(tags=['Password reset'], request=ResetPasswordSerializer, responses={204: None})
class ResetPasswordView(APIView):
    """Set a new password using the `reset_token` from the verify step."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = signing.loads(serializer.validated_data['reset_token'], salt=RESET_SALT, max_age=RESET_TOKEN_MAX_AGE)
        except signing.BadSignature:
            return Response({'reset_token': ['This reset link has expired. Please start again.']}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            reset = PasswordResetCode.objects.select_for_update().filter(pk=payload['reset'], user_id=payload['uid']).first()
            if not reset or reset.used:
                return Response({'reset_token': ['This reset link has already been used.']}, status=status.HTTP_400_BAD_REQUEST)
            user = reset.user
            try:
                password_validation.validate_password(serializer.validated_data['new_password'], user)
            except Exception as exc:  # DjangoValidationError
                messages = getattr(exc, 'messages', [str(exc)])
                return Response({'new_password': messages}, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(serializer.validated_data['new_password'])
            user.save(update_fields=['password'])
            reset.used = True
            reset.save(update_fields=['used'])
        return Response(status=status.HTTP_204_NO_CONTENT)
