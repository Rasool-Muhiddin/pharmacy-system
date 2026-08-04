from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps.views import sitemap

from pharmacy import views as pharmacy_views
from pharmacy.sitemaps import StaticViewSitemap

sitemaps = {
    "static": StaticViewSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),

    path('pharmacy/', include('pharmacy.urls')),

    path('', pharmacy_views.landing_page, name='landing_page'),

    path(
        'sitemap.xml',
        sitemap,
        {'sitemaps': sitemaps},
        name='django.contrib.sitemaps.views.sitemap'
    ),
]