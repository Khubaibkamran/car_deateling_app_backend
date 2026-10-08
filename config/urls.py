from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

api_v1 = [
    path('', include('users.urls')),
    path('', include('vehicles.urls')),
    path('', include('services.urls')),
    path('', include('bookings.urls')),
    path('', include('notifications.urls')),
    path('', include('chat.urls')),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_v1)),
    # API documentation: open /api/docs/ in a browser for Swagger UI.
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

if settings.DEBUG:
    # Uploaded photos are served by Django only in development.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
