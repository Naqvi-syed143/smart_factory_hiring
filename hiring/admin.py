from django.contrib import admin

from .models import Application, CandidateProfile, JobPosting


@admin.register(CandidateProfile)
class CandidateProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone_number", "preferred_shift", "experience_years", "has_resume")
    list_filter = ("preferred_shift",)
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "phone_number",
        "certifications",
    )
    raw_id_fields = ("user",)

    @admin.display(boolean=True, description="CV uploaded")
    def has_resume(self, obj):
        return bool(obj.resume)


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "location", "shift", "hourly_rate", "is_active", "created_at")
    list_filter = ("is_active", "shift", "department")
    list_editable = ("is_active",)
    search_fields = ("title", "department", "location", "description", "required_certifications")
    date_hierarchy = "created_at"


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("candidate", "job", "status", "applied_at")
    list_filter = ("status", "job__department", "job")
    list_editable = ("status",)
    search_fields = (
        "candidate__username",
        "candidate__first_name",
        "candidate__last_name",
        "candidate__email",
        "job__title",
        "notes",
    )
    raw_id_fields = ("candidate", "job")
    date_hierarchy = "applied_at"
    actions = ["mark_practical_test", "mark_medical_check", "mark_hired", "mark_rejected"]

    def _set_status(self, request, queryset, new_status):
        updated = queryset.update(status=new_status)
        self.message_user(request, f"{updated} application(s) set to '{new_status}'.")

    @admin.action(description="Move to Practical Test")
    def mark_practical_test(self, request, queryset):
        self._set_status(request, queryset, Application.Status.PRACTICAL_TEST)

    @admin.action(description="Move to Medical Check")
    def mark_medical_check(self, request, queryset):
        self._set_status(request, queryset, Application.Status.MEDICAL_CHECK)

    @admin.action(description="Mark as Hired")
    def mark_hired(self, request, queryset):
        self._set_status(request, queryset, Application.Status.HIRED)

    @admin.action(description="Mark as Rejected")
    def mark_rejected(self, request, queryset):
        self._set_status(request, queryset, Application.Status.REJECTED)