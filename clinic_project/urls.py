from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import include, path
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from pharmacy import views as pharmacy_views
from pharmacy.sitemaps import StaticViewSitemap


@require_GET
def healthz(request):
    """فحص بسيط تستخدمه Hetzner أو Nginx للتأكد أن Django يعمل."""
    return HttpResponse("ok", content_type="text/plain")


sitemaps = {
    "static": StaticViewSitemap,
}

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),

    path("healthz/", healthz, name="healthz"),

    path("pharmacy/", include("pharmacy.urls")),

    path("", pharmacy_views.landing_page, name="landing_page"),

    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),

    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="pharmacy/robots.txt",
            content_type="text/plain",
        ),
    ),
]