import uuid
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator


class Student(models.Model):
    archived_ceremony = models.ForeignKey('Ceremony', null=True, blank=True, on_delete=models.PROTECT, related_name='archived_students')
    is_active = models.BooleanField(default=True)
    tupc_id = models.CharField(max_length=12, unique=True, verbose_name="TUP ID")
    name = models.CharField(max_length=300)
    course = models.CharField(max_length=120)
    section = models.CharField(max_length=60)

    def __str__(self):
        return f"{self.tupc_id} — {self.name}"


class Ceremony(models.Model):
    class Campus(models.TextChoices):
        CAVITE = "Cavite", "Cavite"
        MANILA = "Manila", "Manila"
        TAGUIG = "Taguig", "Taguig"
        BATANGAS = "Batangas", "Batangas"

    title = models.CharField(max_length=150, default="Sibol Graduation")
    theme = models.CharField(max_length=300, blank=True)
    batch_name = models.CharField(max_length=150, blank=True)
    commencement_number = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    campus = models.CharField(max_length=20, choices=Campus.choices, default=Campus.MANILA)
    starts_at = models.DateTimeField()
    venue = models.CharField(max_length=250)
    is_active = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    program_saved_at = models.DateTimeField(null=True, blank=True)
    roster_snapshot = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['is_active'], condition=models.Q(is_active=True), name='one_active_ceremony')]

    def __str__(self):
        return self.title

    @property
    def commencement_ordinal(self):
        number = self.commencement_number
        if not number:
            return '—'
        if 10 < number % 100 < 14:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
        return f'{number}{suffix}'


class ProgramItem(models.Model):
    class ItemType(models.TextChoices):
        REGISTRATION = 'registration', 'Registration'
        AWARDING = 'awarding', 'Awarding'
        SONG = 'song', 'Song'
        VIDEO = 'video', 'Video'
        SPEAKER = 'speaker', 'Speaker'
        SPEECH = 'speech', 'Speech'
        ASSEMBLY = 'assembly', 'Assembly'
        OTHER = 'other', 'Other'

    class HymnLanguage(models.TextChoices):
        ENGLISH = 'english', 'English'
        TAGALOG = 'tagalog', 'Tagalog'

    ceremony = models.ForeignKey(Ceremony, on_delete=models.CASCADE, related_name='program_items')
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    speaker = models.CharField(max_length=200, blank=True)
    hymn_language = models.CharField(max_length=10, choices=HymnLanguage.choices, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('position', 'pk')

    def __str__(self):
        return self.title

    @property
    def display_speaker(self):
        value = self.speaker.strip()
        return '' if value.lower() in ('na', 'n/a') else value


class StudentProfile(models.Model):
    access_code_digest = models.CharField(max_length=64, unique=True, null=True, blank=True)
    current_access_code = models.CharField(max_length=12, blank=True)
    student = models.OneToOneField(Student, on_delete=models.PROTECT, null=True, related_name="profile")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
    contact_number = models.CharField(max_length=25)


class Faculty(models.Model):
    archived_ceremony = models.ForeignKey(Ceremony, null=True, blank=True, on_delete=models.PROTECT, related_name='archived_faculty')
    employee_id = models.CharField(max_length=60, unique=True, null=True, verbose_name="Employee Faculty ID")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="faculty_profile")
    name = models.CharField(max_length=300)
    department = models.CharField(max_length=180, verbose_name="Department / Office")
    campus = models.CharField(max_length=20, choices=Ceremony.Campus.choices)
    current_access_code = models.CharField(max_length=16, blank=True)

    def __str__(self):
        return f"{self.name} — {self.department}"


class Ticket(models.Model):
    class TicketType(models.TextChoices):
        ADMIN = "ADMIN", "Admin account"
        STUDENT = "STUDENT", "Student"
        FACULTY = "FACULTY", "Faculty"
        GUEST = "GUEST", "Guest"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets")
    ceremony = models.ForeignKey(Ceremony, on_delete=models.PROTECT, null=True, related_name="tickets")
    ticket_type = models.CharField(max_length=10, choices=TicketType.choices)
    code = models.CharField(max_length=16, unique=True, editable=False)
    purchased_at = models.DateTimeField(auto_now_add=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    guest_relation = models.CharField(max_length=20, blank=True)
    guest_name = models.CharField(max_length=150, blank=True)
    payment_receipt = models.FileField(upload_to='receipts/', blank=True)
    reservation_status = models.CharField(max_length=10, choices=[('pending', 'Pending'), ('approved', 'Approved'), ('declined', 'Declined')], default='approved')

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"SB-26-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def price(self):
        return 150 if self.ticket_type == self.TicketType.GUEST else 0

    @property
    def gate(self):
        if self.ticket_type == self.TicketType.ADMIN:
            return "Both gates"
        return "Guest Gate" if self.ticket_type == self.TicketType.GUEST else "Student & Faculty Gate"

    @property
    def is_used(self):
        return self.checked_in_at is not None

    def __str__(self):
        return f"{self.code} — {self.owner.get_full_name() or self.owner.username}"


class TicketTransfer(models.Model):
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name='transfer')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_ticket_transfers')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_ticket_transfers')
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)


class GateAdmission(models.Model):
    # A durable claim prevents a second relay pulse even if a request is retried.
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='admissions')
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    port = models.CharField(max_length=120)
    relay = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, default='pending', choices=[('pending', 'Pending'), ('sent', 'Pulse sent'), ('uncertain', 'Needs inspection')])
    created_at = models.DateTimeField(auto_now_add=True)
    detail = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ticket", "relay"], name="one_admission_per_ticket_gate")]
