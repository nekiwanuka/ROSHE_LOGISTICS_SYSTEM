"""
URL Configuration for roshe_logistics project
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView


admin.site.site_header = 'ROSHE LOGISTICS'
admin.site.site_title = 'ROSHE LOGISTICS Admin'
admin.site.index_title = 'Administration'

urlpatterns = [
    path(
        'favicon.ico',
        RedirectView.as_view(url=f'{settings.STATIC_URL}favicon.ico', permanent=True),
    ),
    path('admin/', admin.site.urls),
    path('', include('logistics.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
