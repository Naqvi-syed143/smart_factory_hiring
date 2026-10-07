from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ApplicationViewSet, CandidateProfileViewSet, JobPostingViewSet

router = DefaultRouter()
router.register(r"jobs", JobPostingViewSet, basename="job")
router.register(r"applications", ApplicationViewSet, basename="application")
router.register(r"profiles", CandidateProfileViewSet, basename="profile")

# This module is mounted at /api/ in backend/urls.py — it only contains
# the JSON API routes. The HTML page routes live in backend/urls.py directly.
urlpatterns = [
    path("", include(router.urls)),
]