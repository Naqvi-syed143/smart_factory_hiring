from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from hiring.views import hr_dashboard, job_portal, signup

urlpatterns = [
    # HTML pages
    path("", job_portal, name="job-portal"),
    path("hr/", hr_dashboard, name="hr-dashboard"),
    path("signup/", signup, name="signup"),

    # Admin + API
    path("admin/", admin.site.urls),
    path("api/", include("hiring.urls")),
    path("api-auth/", include("rest_framework.urls")),  # provides /api-auth/login/ and /logout/
]

# Serve uploaded resumes/CVs in development only.
# In production, a real web server (nginx, etc.) should serve MEDIA_URL instead.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)