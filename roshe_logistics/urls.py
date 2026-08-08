"""
URL Configuration for roshe_logistics project
"""

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from logistics import views as logistics_views

handler404 = "logistics.views.not_found"


admin.site.site_header = "ROSHE LOGISTICS"
admin.site.site_title = "ROSHE LOGISTICS Admin"
admin.site.index_title = "Administration"

urlpatterns = [
    path(
        "favicon.ico",
        RedirectView.as_view(url=f"{settings.STATIC_URL}favicon.ico", permanent=True),
    ),
    path("admin/", admin.site.urls),
    path("", include("logistics.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Keep the same generic not-found response in local debug mode, where Django
# would otherwise display the project's URL patterns for an invalid address.
urlpatterns += [re_path(r"^.*$", logistics_views.not_found)]
