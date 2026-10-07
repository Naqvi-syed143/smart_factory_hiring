from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Application, CandidateProfile, JobPosting

User = get_user_model()

MAX_RESUME_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_RESUME_EXTENSIONS = (".pdf", ".doc", ".docx")


class UserSerializer(serializers.ModelSerializer):
    """Read-only public details of a user."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "email", "is_staff"]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.get_username()


class CandidateProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    resume_url = serializers.SerializerMethodField()

    class Meta:
        model = CandidateProfile
        fields = [
            "id",
            "user",
            "phone_number",
            "address",
            "preferred_shift",
            "certifications",
            "experience_years",
            "resume",
            "resume_url",
        ]
        read_only_fields = ["id", "user", "resume_url"]
        extra_kwargs = {"resume": {"write_only": True, "required": False}}

    def get_resume_url(self, obj):
        if not obj.resume:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.resume.url) if request else obj.resume.url

    def validate_resume(self, value):
        if not value:
            return value
        if value.size > MAX_RESUME_SIZE:
            raise serializers.ValidationError("Resume file must be under 5MB.")
        if not value.name.lower().endswith(ALLOWED_RESUME_EXTENSIONS):
            raise serializers.ValidationError("Resume must be a PDF or Word document (.pdf, .doc, .docx).")
        return value


class JobPostingSerializer(serializers.ModelSerializer):
    applications_count = serializers.IntegerField(
        source="applications.count", read_only=True
    )

    class Meta:
        model = JobPosting
        fields = [
            "id",
            "title",
            "department",
            "location",
            "shift",
            "hourly_rate",
            "description",
            "required_certifications",
            "is_active",
            "created_at",
            "applications_count",
        ]
        read_only_fields = ["id", "created_at", "applications_count"]

    def validate_hourly_rate(self, value):
        if value <= 0:
            raise serializers.ValidationError("Hourly rate must be greater than 0.")
        return value


class ApplicationSerializer(serializers.ModelSerializer):
    """Used for creating / listing / retrieving applications.

    - `job` is written as an ID; `job_detail` is the nested read-only version.
    - `candidate` is always the authenticated user (never taken from input).
    - `status` and `notes` can only be changed via ApplicationStatusUpdateSerializer.
    - HR notes are hidden from non-staff users.
    """

    job_detail = JobPostingSerializer(source="job", read_only=True)
    candidate = UserSerializer(read_only=True)
    candidate_profile = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id",
            "job",
            "job_detail",
            "candidate",
            "candidate_profile",
            "status",
            "applied_at",
            "notes",
            "resume",
            "ai_match_score",
            "ai_summary",
            "ai_screening_questions",
        ]
        # `resume` is read-only here by design: candidates can't set it
        # directly via POST. Instead, ApplicationViewSet.perform_create()
        # auto-copies it from the candidate's profile resume (see views.py),
        # so frontend clients can read it but never tamper with it, same as
        # the AI fields.
        read_only_fields = [
            "id",
            "candidate",
            "candidate_profile",
            "status",
            "applied_at",
            "notes",
            "resume",
            "ai_match_score",
            "ai_summary",
            "ai_screening_questions",
        ]

    def get_candidate_profile(self, obj):
        profile = getattr(obj.candidate, "candidate_profile", None)
        if profile is None:
            return None
        # Pass context through so resume_url can build an absolute URI.
        data = CandidateProfileSerializer(profile, context=self.context).data
        data.pop("user", None)  # already exposed under `candidate`
        return data

    def validate_job(self, job):
        if not job.is_active:
            raise serializers.ValidationError("This job posting is no longer active.")
        return job

    def validate(self, attrs):
        request = self.context.get("request")
        if request and self.instance is None:
            if Application.objects.filter(
                job=attrs["job"], candidate=request.user
            ).exists():
                raise serializers.ValidationError(
                    {"job": "You have already applied to this job."}
                )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not (request and request.user.is_staff):
            for field in ("notes", "ai_match_score", "ai_summary", "ai_screening_questions"):
                data.pop(field, None)
        return data


class ApplicationStatusUpdateSerializer(serializers.ModelSerializer):
    """HR-only: update status and notes."""

    class Meta:
        model = Application
        fields = ["id", "status", "notes"]
        read_only_fields = ["id"]