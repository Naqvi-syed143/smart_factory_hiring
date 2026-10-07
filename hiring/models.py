from django.conf import settings
from django.db import models


class ShiftChoices(models.TextChoices):
    DAY = "day", "Day"
    NIGHT = "night", "Night"
    ROTATING = "rotating", "Rotating"
    ANY = "any", "Any"


def resume_upload_path(instance, filename):
    return f"resumes/user_{instance.user_id}/{filename}"


class CandidateProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate_profile",
    )
    phone_number = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    preferred_shift = models.CharField(
        max_length=10,
        choices=ShiftChoices.choices,
        default=ShiftChoices.ANY,
    )
    certifications = models.TextField(
        blank=True,
        help_text="List certifications, e.g. forklift license, welding, OSHA.",
    )
    experience_years = models.PositiveIntegerField(default=0)
    resume = models.FileField(
        upload_to=resume_upload_path,
        blank=True,
        null=True,
        help_text="CV/Resume file (PDF or Word, max 5MB).",
    )

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"Profile: {self.user.get_username()}"


class JobPosting(models.Model):
    title = models.CharField(max_length=200)
    department = models.CharField(max_length=100)
    location = models.CharField(max_length=200)
    shift = models.CharField(
        max_length=10,
        choices=ShiftChoices.choices,
        default=ShiftChoices.DAY,
    )
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    description = models.TextField()
    required_certifications = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.department})"


class Application(models.Model):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        PRACTICAL_TEST = "practical_test", "Practical Test"
        MEDICAL_CHECK = "medical_check", "Medical Check"
        HIRED = "hired", "Hired"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(
        JobPosting,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.APPLIED,
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Internal HR notes.")

    # --- Resume for this specific application ---
    # (CandidateProfile also has its own standing `resume`; this one lets a
    # candidate attach/override a resume tailored to this particular job.)
    resume = models.FileField(upload_to="resumes/", blank=True, null=True)

    # --- AI resume analysis (populated automatically when `resume` is set) ---
    ai_match_score = models.IntegerField(
        default=0,
        help_text="AI-generated 0-100 match score against the job's requirements.",
    )
    ai_summary = models.TextField(
        blank=True,
        help_text="AI-generated 2-sentence summary of candidate fit.",
    )
    ai_screening_questions = models.TextField(
        blank=True,
        help_text="JSON-encoded list of 3 AI-generated safety/screening questions.",
    )

    class Meta:
        ordering = ["-applied_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "candidate"],
                name="unique_application_per_job_per_candidate",
            )
        ]

    def __str__(self):
        return f"{self.candidate.get_username()} -> {self.job.title} [{self.status}]"