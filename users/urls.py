from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/', views.LoginView.as_view(), name='login'),
    path('auth/google/', views.GoogleLoginView.as_view(), name='google-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('auth/password/forgot/', views.ForgotPasswordView.as_view(), name='password-forgot'),
    path('auth/password/verify/', views.VerifyResetCodeView.as_view(), name='password-verify'),
    path('auth/password/reset/', views.ResetPasswordView.as_view(), name='password-reset'),
    path('me/', views.MeView.as_view(), name='me'),
    path('me/password/', views.ChangePasswordView.as_view(), name='change-password'),
]
