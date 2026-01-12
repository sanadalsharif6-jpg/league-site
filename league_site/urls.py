from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("league.urls")),  # routes متاع التطبيق
]

# serve media في وضع التطوير فقط
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# (اختياري) لو عندك صفحات 404/500 مخصصة
handler404 = "league.views.custom_404"
handler500 = "league.views.custom_500"
