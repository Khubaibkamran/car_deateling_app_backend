"""Verify a Google ID token (from the app's "Continue with Google" button)."""
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleTokenError(Exception):
    pass


def verify_google_token(token: str) -> dict:
    """Return the token's claims (email, name, picture...) or raise GoogleTokenError."""
    audiences = settings.GOOGLE_CLIENT_IDS
    if not audiences:
        raise GoogleTokenError('Google sign-in is not configured on the server.')
    try:
        claims = id_token.verify_oauth2_token(token, google_requests.Request(), audience=audiences)
    except ValueError as exc:
        raise GoogleTokenError('Invalid Google sign-in. Please try again.') from exc
    if not claims.get('email') or not claims.get('email_verified'):
        raise GoogleTokenError('Your Google email address is not verified.')
    return claims
