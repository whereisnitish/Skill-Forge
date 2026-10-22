from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.core import views as core_views
from apps.marketing.sitemaps import MarketingSitemap

admin.site.site_header = "SkillForge administration"
admin.site.site_title = "SkillForge admin"

urlpatterns = [
    path("healthz/", core_views.liveness, name="healthz"),
    path("readyz/", core_views.readiness, name="readyz"),
    path("robots.txt", core_views.robots_txt, name="robots"),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": {"marketing": MarketingSitemap}},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("settings/", include("apps.accounts.settings_urls")),
    path("onboarding/", include("apps.onboarding.urls")),
    path("app/", include("apps.learning.urls")),
    path("app/", include("apps.catalog.urls")),
    path("app/mentor/", include("apps.mentor.urls")),
    path("app/notifications/", include("apps.notifications.urls")),
    path("billing/", include("apps.billing.urls")),
    path("", include("apps.marketing.urls")),
]

handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
