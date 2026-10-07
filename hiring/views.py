import json
import logging
import os

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from rest_framework import filters, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .forms import CandidateSignUpForm
from .models import Application, CandidateProfile, JobPosting
from .serializers import (
    ApplicationSerializer,
    ApplicationStatusUpdateSerializer,
    CandidateProfileSerializer,
    JobPostingSerializer,
)
from .utils import analyze_candidate_with_gemini

logger = logging.getLogger(__name__)


class IsStaffOrReadOnly(permissions.BasePermission):
    """Anyone can read; only staff (HR) can create/update/delete."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class JobPostingViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for job postings.

    - Public/candidates see only active jobs.
    - Staff see everything; optional `?is_active=true|false` filter.
    - Extra filters: ?department=, ?shift=, ?search=, ?ordering=
    """

    serializer_class = JobPostingSerializer
    permission_classes = [IsStaffOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "department", "location", "description"]
    ordering_fields = ["created_at", "hourly_rate", "title"]

    def get_queryset(self):
        qs = JobPosting.objects.all()
        user = self.request.user
        params = self.request.query_params

        if not (user.is_authenticated and user.is_staff):
            qs = qs.filter(is_active=True)
        else:
            is_active = params.get("is_active")
            if is_active is not None:
                qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))

        if params.get("department"):
            qs = qs.filter(department__iexact=params["department"])
        if params.get("shift"):
            qs = qs.filter(shift=params["shift"])
        return qs


class ApplicationViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    - Candidates: create an application and list/retrieve their own.
    - HR (staff): list all applications and PATCH status / notes.
    - Filters: ?status=, ?job=, ?search=
    """

    http_method_names = ["get", "post", "patch", "head", "options"]  # no PUT/DELETE
    parser_classes = [JSONParser, MultiPartParser, FormParser]  # MultiPart needed for resume uploads
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "candidate__username",
        "candidate__first_name",
        "candidate__last_name",
        "job__title",
    ]
    ordering_fields = ["applied_at", "status"]

    def get_permissions(self):
        if self.action == "partial_update":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "partial_update":
            return ApplicationStatusUpdateSerializer
        return ApplicationSerializer

    def get_queryset(self):
        qs = Application.objects.select_related(
            "job", "candidate", "candidate__candidate_profile"
        )
        user = self.request.user
        if not user.is_staff:
            qs = qs.filter(candidate=user)

        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("job"):
            qs = qs.filter(job_id=params["job"])
        return qs

    def perform_create(self, serializer):
        application = serializer.save(candidate=self.request.user)
        self._attach_profile_resume(application)

        # Only trigger Gemini analysis when a resume ended up attached to
        # this application. AI analysis must never block or break
        # application submission — any failure here is logged, not raised.
        if application.resume:
            try:
                self._run_ai_analysis(application)
            except Exception:
                logger.exception("Gemini resume analysis failed for application %s", application.pk)
        else:
            logger.info(
                "No resume available for application %s (candidate has no "
                "profile resume uploaded); skipping AI analysis.",
                application.pk,
            )

    def _attach_profile_resume(self, application):
        """
        `resume` is read-only on ApplicationSerializer, so candidates can't
        set it directly in the POST body. Instead, if they've already
        uploaded a resume to their CandidateProfile (via the apply form),
        we copy that file onto this specific application automatically.
        This gives every application its own permanent snapshot of the
        resume that was on file at the time — even if the candidate later
        replaces their profile resume for a different job.
        """
        profile = getattr(application.candidate, "candidate_profile", None)
        if not (profile and profile.resume):
            return
        try:
            filename = os.path.basename(profile.resume.name)
            application.resume.save(filename, profile.resume, save=True)
        except Exception:
            logger.exception(
                "Could not attach profile resume to application %s", application.pk
            )

    def _run_ai_analysis(self, application):
        """
        Send this application's resume file, the job's title, and its
        required certifications to Gemini, and write the result straight
        onto the Application row so HR can see it immediately in the
        dashboard.
        """
        result = analyze_candidate_with_gemini(
            resume_path=application.resume.path,
            job_title=application.job.title,
            required_certs=application.job.required_certifications,
        )

        application.ai_match_score = result["match_score"]
        application.ai_summary = result["summary"]
        application.ai_screening_questions = json.dumps(result["safety_questions"])
        application.save(update_fields=["ai_match_score", "ai_summary", "ai_screening_questions"])

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Respond with the full application representation
        return Response(
            ApplicationSerializer(instance, context=self.get_serializer_context()).data
        )


class CandidateProfileViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Retrieve / update worker profiles, including resume/CV upload.

    - Candidates only see and edit their own profile.
    - Staff can view all profiles.
    - Convenience endpoint: GET/PATCH /api/profiles/me/
    - Accepts multipart/form-data (for resume uploads) as well as JSON.
    """

    serializer_class = CandidateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "put", "patch", "head", "options"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filter_backends = [filters.SearchFilter]
    search_fields = ["user__username", "user__first_name", "user__last_name", "certifications"]

    def get_queryset(self):
        qs = CandidateProfile.objects.select_related("user")
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        return qs

    def update(self, request, *args, **kwargs):
        # Only the owner may edit a profile (staff are read-only here).
        instance = self.get_object()
        if instance.user != request.user:
            return Response(
                {"detail": "You can only edit your own profile."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    @action(detail=False, methods=["get", "patch", "put"], url_path="me")
    def me(self, request):
        profile, _ = CandidateProfile.objects.get_or_create(user=request.user)
        if request.method == "GET":
            return Response(self.get_serializer(profile).data)
        serializer = self.get_serializer(
            profile, data=request.data, partial=(request.method == "PATCH")
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Template (HTML page) views — these render the frontend, separate from the
# JSON API above. The pages call the API endpoints above via fetch().
# ---------------------------------------------------------------------------

def job_portal(request):
    """Public candidate job portal. Login is only required to apply."""
    return render(request, "index.html")


@login_required(login_url="/api-auth/login/")
def hr_dashboard(request):
    """HR recruiter dashboard. Requires a logged-in staff account."""
    if not request.user.is_staff:
        return HttpResponseForbidden("HR access only.")
    return render(request, "hr_dashboard.html")


def signup(request):
    """
    Public self-registration for CANDIDATES only.
    Always creates a non-staff account, so signing up here never grants
    HR dashboard access — that's reserved for accounts staff mark as
    staff/superuser (via createsuperuser or Django admin).
    """
    if request.user.is_authenticated:
        return redirect("job-portal")

    if request.method == "POST":
        form = CandidateSignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_staff = False
            user.save()
            CandidateProfile.objects.get_or_create(user=user)
            login(request, user)
            return redirect("job-portal")
    else:
        form = CandidateSignUpForm()

    return render(request, "signup.html", {"form": form})