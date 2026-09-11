from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db.models import Sum, Q, Case, When, IntegerField
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse, HttpResponseNotAllowed, Http404
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from .forms import SignUpForm, StudentForm, CeremonyForm, AccessCodeForm, AdminLoginForm, FacultyForm, ProgramItemForm, TicketSettingsForm, StartTicketsForm
from .models import Ticket, Student, Ceremony, Faculty, StudentProfile, ProgramItem, TicketTransfer, GuestReservation, GateAdmission
import json
import uuid
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.conf import settings
from .access_codes import issue_access_code, code_digest
from .ticket_policy import ticket_limit, issued_count, remaining_slots


def ensure_student_ticket(user, ceremony):
    """Give every eligible account its included student pass for this ceremony."""
    if ceremony and ceremony.auto_student_ticket and user.is_active and not user.is_staff and not Faculty.objects.filter(user=user).exists() and not StudentProfile.objects.filter(user=user, student__archived_ceremony__isnull=False).exists():
        with transaction.atomic():
            # I-lock ang account habang chine-check at ginagawa ang included student pass.
            User.objects.select_for_update().get(pk=user.pk)
            if remaining_slots(user, ceremony) and not GuestReservation.objects.filter(owner=user, ceremony=ceremony, ticket_type='STUDENT', status='pending').exists():
                Ticket.objects.get_or_create(owner=user, ceremony=ceremony, ticket_type=Ticket.TicketType.STUDENT)

def home(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("dashboard")
    ceremony = Ceremony.objects.filter(is_active=True).first()
    graduates = Student.objects.filter(archived_ceremony__isnull=True).count() + Faculty.objects.filter(archived_ceremony__isnull=True).count()
    guests = ceremony.tickets.filter(ticket_type=Ticket.TicketType.GUEST).count() if ceremony else 0
    return render(request, "events/home.html", {'ceremony': ceremony, 'graduates': graduates, 'guests': guests, 'expected': graduates + guests})


def program_flow(request):
    ceremony = Ceremony.objects.filter(is_active=True).first()
    items = ceremony.program_items.all() if ceremony else ProgramItem.objects.none()
    hymns = []
    selected_languages = dict.fromkeys(item.hymn_language for item in items if item.hymn_language)
    for language in selected_languages:
        if language not in ProgramItem.HymnLanguage.values:
            continue
        filename = 'eng' if language == ProgramItem.HymnLanguage.ENGLISH else 'tagalog'
        with open(settings.BASE_DIR / f'static/txt/tup_hymn_{filename}.txt', encoding='utf-8') as source:
            hymns.append({
                'language': language,
                'lang': 'en' if language == ProgramItem.HymnLanguage.ENGLISH else 'tl',
                'label': ProgramItem.HymnLanguage(language).label,
                'lyrics': source.read(),
            })
    return render(request, 'events/program_flow.html', {'ceremony': ceremony, 'items': items, 'hymns': hymns})


@never_cache
def register(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("dashboard")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            ensure_student_ticket(user, Ceremony.objects.filter(is_active=True).first())
            request.session["registration_code"] = issue_access_code(user.student_profile)
        return redirect("account_details")
    return render(request, "registration/register.html", {"form": form})

@never_cache
def account_details(request):
    code = request.session.get('registration_code')
    if not code:
        return redirect('register')
    return render(request, 'registration/account_details.html', {'access_code': code})


@never_cache
def sign_in(request):
    form = AccessCodeForm(request.POST or None)
    if request.method == 'POST':
        # Bilangin ang failed attempts per IP; may limang minutong cache timeout.
        key = 'access-login:' + request.META.get('REMOTE_ADDR', 'unknown')
        attempts = cache.get(key, 0)
        if attempts >= 10:
            form.add_error(None, 'Too many attempts. Please try again in five minutes.')
        elif form.is_valid():
            profile = StudentProfile.objects.select_related('user').filter(access_code_digest=code_digest(form.cleaned_data['access_code']), user__is_active=True, user__is_staff=False).first()
            if profile:
                cache.delete(key)
                request.session.pop('registration_code', None)
                login(request, profile.user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('tickets')
            cache.set(key, attempts + 1, 300)
            form.add_error(None, 'Invalid access code. Check your code and try again.')
        else:
            cache.set(key, attempts + 1, 300)
    return render(request, 'registration/login.html', {'form': form})


@never_cache
def admin_sign_in(request):
    form = AdminLoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect('dashboard')
    return render(request, 'registration/login.html', {'form': form, 'admin_login': True})


def sign_out(request):
    logout(request)
    return redirect("home")

@login_required
@require_POST
def buy_ticket(request, ticket_type):
    if request.user.is_staff:
        messages.info(request, "Admin accounts do not purchase attendee tickets.")
        return redirect("dashboard")
    ticket_type = ticket_type.upper()
    if ticket_type != Ticket.TicketType.GUEST:
        messages.error(request, "Please choose a valid ticket type.")
        return redirect("home")
    ceremony = Ceremony.objects.filter(is_active=True).first()
    if not ceremony:
        messages.error(request, 'Ticket reservations open when a ceremony is announced.')
        return redirect('tickets')
    if not ceremony.ticket_workflow:
        messages.info(request, 'Ticket reservations have not started yet.')
    elif ceremony.ticket_workflow == 'selling':
        messages.info(request, 'Submit a reservation request with payment proof. A guest ticket is issued only after administrator approval.')
    else:
        messages.info(request, 'Submit a ticket request for administrator approval. A receipt upload is optional.')
    return redirect("tickets")


@login_required
@require_POST
# Pending requests muna ang ginagawa rito; admin approval ang susunod na hakbang.
def reserve_guests(request):
    ceremony = Ceremony.objects.filter(is_active=True).first()
    try:
        count = int(request.POST.get('count', 0) or 0)
    except (TypeError, ValueError):
        count = 0
    relation = request.POST.get('relation', '')
    guest_name = request.POST.get('guest_name', '').strip()
    if not ceremony or not ceremony.ticket_workflow:
        messages.error(request, 'Ticket reservations have not started yet.')
        return redirect('tickets')
    if request.user.is_staff or not 1 <= count <= 100 or relation not in ('Relative', 'Friend') or (ceremony.ticket_workflow == 'selling' and not request.FILES.get('receipt')):
        messages.error(request, 'Choose a valid ticket quantity and guest type' + (', and upload your payment receipt.' if ceremony.ticket_workflow == 'selling' else '.'))
        return redirect('tickets')
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        ensure_student_ticket(request.user, ceremony)
        if count > remaining_slots(request.user, ceremony):
            messages.error(request, f'Your limit is {ticket_limit(request.user, ceremony)} total tickets, including your personal pass and pending requests.')
            return redirect('tickets')
        for number in range(count):
            GuestReservation.objects.create(owner=request.user, ceremony=ceremony, guest_relation=relation, guest_name=guest_name if count == 1 else f'{guest_name or relation} {number + 1}', payment_receipt=request.FILES.get('receipt', ''))
    messages.success(request, 'Guest ticket request submitted. A QR ticket will be issued after administrator approval.')
    return redirect('tickets')


@login_required
@require_POST
def reserve_student(request):
    ceremony = Ceremony.objects.filter(is_active=True).first()
    eligible = StudentProfile.objects.filter(user=request.user, student__is_active=True, student__archived_ceremony__isnull=True).exists()
    if not ceremony or not ceremony.ticket_workflow or ceremony.auto_student_ticket or request.user.is_staff or not eligible or Faculty.objects.filter(user=request.user).exists():
        messages.error(request, 'Student ticket requests are unavailable for this account.')
        return redirect('tickets')
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        personal = Ticket.objects.filter(owner=request.user, ceremony=ceremony, ticket_type='STUDENT').exclude(reservation_status='declined').exists()
        pending = GuestReservation.objects.filter(owner=request.user, ceremony=ceremony, ticket_type='STUDENT', status='pending').exists()
        if personal or pending:
            messages.info(request, 'You already have a student ticket or a pending request.')
        elif not remaining_slots(request.user, ceremony):
            messages.error(request, 'Your total ticket limit has been reached.')
        else:
            GuestReservation.objects.create(owner=request.user, ceremony=ceremony, ticket_type='STUDENT', payment_receipt=request.FILES.get('receipt', ''))
            messages.success(request, 'Student ticket requested. Your pass will appear after administrator approval.')
    return redirect('tickets')


def verified_transfer_students():
    return User.objects.filter(
        is_active=True, is_staff=False,
        student_profile__student__is_active=True,
        student_profile__student__archived_ceremony__isnull=True,
        student_profile__access_code_digest__isnull=False,
    ).exclude(student_profile__access_code_digest='').order_by('first_name', 'last_name', 'username')


@login_required
@require_POST
def transfer_ticket(request):
    ticket = get_object_or_404(Ticket, pk=request.POST.get('ticket_id'), owner=request.user, ticket_type=Ticket.TicketType.GUEST, reservation_status='approved', checked_in_at__isnull=True, ceremony__is_active=True)
    recipient = verified_transfer_students().filter(username__iexact=request.POST.get('recipient_id', '').strip()).exclude(pk=request.user.pk).first()
    if not recipient:
        messages.error(request, 'Choose an active, verified student to receive this ticket.')
    elif TicketTransfer.objects.filter(ticket=ticket).exists():
        messages.error(request, 'This ticket already has a transfer request.')
    else:
        TicketTransfer.objects.create(ticket=ticket, sender=request.user, recipient=recipient)
        messages.success(request, 'Transfer request sent. The ticket remains yours until the student accepts it.')
    return redirect('tickets')


@login_required
@require_POST
# Sa acceptance lang lilipat ang owner, matapos i-check ulit ang ticket at slots.
def accept_transfer(request, transfer_id):
    transfer = get_object_or_404(TicketTransfer, pk=transfer_id, recipient=request.user, accepted_at__isnull=True)
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=transfer.ticket_id)
        if (not verified_transfer_students().filter(pk=request.user.pk).exists()
                or ticket.owner_id != transfer.sender_id or ticket.is_used
                or ticket.reservation_status != 'approved' or not ticket.ceremony or not ticket.ceremony.is_active):
            messages.error(request, 'This transfer is no longer available.')
            return redirect('tickets')
        User.objects.select_for_update().get(pk=request.user.pk)
        ensure_student_ticket(request.user, ticket.ceremony)
        if not remaining_slots(request.user, ticket.ceremony):
            messages.error(request, 'Your total ticket limit has been reached. This transfer was not accepted.')
            return redirect('tickets')
        transfer.ticket = ticket
        transfer.ticket.owner = request.user
        transfer.ticket.save(update_fields=['owner'])
        transfer.accepted_at = timezone.now()
        transfer.save(update_fields=['accepted_at'])
    messages.success(request, 'Ticket transfer accepted. The pass is now in your portal.')
    return redirect('tickets')

@login_required
def purchase(request):
    if request.user.is_staff:
        return redirect("dashboard")
    return redirect('tickets')

@login_required
def tickets(request):
    if request.user.is_staff:
        return redirect("dashboard")
    ceremony = Ceremony.objects.filter(is_active=True).first()
    ensure_student_ticket(request.user, ceremony)
    guest_count = request.user.tickets.filter(ceremony=ceremony, ticket_type=Ticket.TicketType.GUEST).count() if ceremony else 0
    pending_guest_requests = request.user.guest_reservations.filter(ceremony=ceremony, status=GuestReservation.Status.PENDING).order_by('created_at') if ceremony else GuestReservation.objects.none()
    incoming_transfers = TicketTransfer.objects.select_related('ticket', 'sender').filter(recipient=request.user, accepted_at__isnull=True)
    tickets = request.user.tickets.select_related('ceremony').exclude(reservation_status='declined').annotate(ticket_order=Case(When(ticket_type=Ticket.TicketType.STUDENT, then=0), default=1, output_field=IntegerField())).order_by('ticket_order', 'purchased_at')
    transferable_tickets = tickets.filter(ticket_type=Ticket.TicketType.GUEST, reservation_status='approved', checked_in_at__isnull=True, ceremony__is_active=True, transfer__isnull=True)
    transfer_recipients = verified_transfer_students().exclude(pk=request.user.pk)
    slots = remaining_slots(request.user, ceremony) if ceremony else 0
    can_request_student = bool(ceremony and ceremony.ticket_workflow and not ceremony.auto_student_ticket and slots and StudentProfile.objects.filter(user=request.user, student__is_active=True, student__archived_ceremony__isnull=True).exists() and not Faculty.objects.filter(user=request.user).exists() and not tickets.filter(ceremony=ceremony, ticket_type='STUDENT').exists() and not pending_guest_requests.filter(ticket_type='STUDENT').exists())
    return render(request, "events/tickets.html", {"tickets": tickets, 'ceremony': ceremony, 'guest_count': guest_count, 'guest_slots': slots, 'guest_quantities': range(1, slots + 1), 'ticket_limit': ticket_limit(request.user, ceremony) if ceremony else 0, 'can_request_student': can_request_student, 'pending_guest_requests': pending_guest_requests, 'incoming_transfers': incoming_transfers, 'transferable_tickets': transferable_tickets, 'transferable_ids': list(transferable_tickets.values_list('pk', flat=True)), 'transfer_recipients': transfer_recipients})

# Shared search at pagination ito para sa live records at archived snapshot lists.
def dashboard_table(request, rows, key, label, fields):
    query = request.GET.get(f'{key}_q', '').strip()
    if query:
        if isinstance(rows, list):
            def value(row, field):
                for part in field.split('__'):
                    row = row.get(part, '') if isinstance(row, dict) else ''
                return str(row or '')
            rows = [row for row in rows if any(query.casefold() in value(row, field).casefold() for field in fields)]
        else:
            match = Q()
            for field in fields:
                match |= Q(**{f'{field}__icontains': query})
            rows = rows.filter(match)
    page = Paginator(rows, 20).get_page(request.GET.get(f'{key}_page'))
    params = request.GET.copy()
    def page_url(number):
        params[f'{key}_page'] = number
        return f'?{params.urlencode()}#{key}-table'
    links = [(number, page_url(number)) for number in page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1) if isinstance(number, int)]
    return {
        'page': page, 'key': key, 'label': label, 'query': query, 'links': links,
        'previous': page_url(page.previous_page_number()) if page.has_previous() else '',
        'next': page_url(page.next_page_number()) if page.has_next() else '',
        'preserved': [(name, val) for name, val in request.GET.items() if name not in (f'{key}_q', f'{key}_page')],
    }


@transaction.atomic
def complete_ceremony(ceremony):
    if ceremony.completed_at:
        return
    # Preserve roster details and registration state as they were at completion.
    students = Student.objects.filter(archived_ceremony__isnull=True).select_related('profile').order_by('tupc_id')
    faculty = Faculty.objects.select_related('user').filter(user__tickets__ceremony=ceremony, user__tickets__ticket_type=Ticket.TicketType.FACULTY).distinct().order_by('name')
    # Kopyahin ang roster para pareho pa rin ang history kahit magbago ang live records.
    ceremony.roster_snapshot = {
        'students': [dict(tupc_id=row.tupc_id, name=row.name, program_section=row.program_section, is_active=row.is_active, profile=hasattr(row, 'profile')) for row in students],
        'faculty': [dict(employee_id=row.employee_id, name=row.name, department=row.department, campus=row.campus, user=dict(username=row.user.username, email=row.user.email)) for row in faculty],
    }
    # Keep account and ticket records intact, but retire access and live roster membership.
    student_ids = list(students.values_list('pk', flat=True))
    faculty_ids = list(faculty.values_list('pk', flat=True))
    attendee_ids = set(ceremony.tickets.exclude(owner__is_staff=True).values_list('owner_id', flat=True))
    attendee_ids.update(StudentProfile.objects.filter(student_id__in=student_ids).values_list('user_id', flat=True))
    attendee_ids.update(Faculty.objects.filter(pk__in=faculty_ids).values_list('user_id', flat=True))
    Student.objects.filter(pk__in=student_ids).update(archived_ceremony=ceremony)
    Faculty.objects.filter(pk__in=faculty_ids).update(archived_ceremony=ceremony)
    User.objects.filter(pk__in=attendee_ids, is_staff=False).update(is_active=False)
    ceremony.is_active = False
    ceremony.completed_at = timezone.now()
    ceremony.save(update_fields=['roster_snapshot', 'is_active', 'completed_at'])


@never_cache
@user_passes_test(lambda user: user.is_staff)
# Iisang view ang gamit ng admin dashboard at history; is_history ang panghiwalay.
def dashboard(request, is_history=False):
    history_id = request.GET.get('ceremony', '')
    if history_id and not is_history:
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
        return redirect(f"{reverse('history')}?{request.GET.urlencode()}")
    selected_ceremony = None
    if is_history and request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    if is_history and history_id:
        if not history_id.isdecimal():
            raise Http404('Ceremony not found.')
        selected_ceremony = get_object_or_404(Ceremony, pk=history_id, is_active=False)
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
    ticket_settings_form = None
    start_tickets_form = None
    student_form, ceremony_form, faculty_form, program_item_form = StudentForm(), CeremonyForm(), FacultyForm(), ProgramItemForm()
    open_modal = ''
    student_edit_form = StudentForm(prefix='edit')
    editing_student = None
    if request.method == 'POST':
        if request.POST.get('action') == 'start_tickets':
            with transaction.atomic():
                current = get_object_or_404(Ceremony.objects.select_for_update(), is_active=True)
                if current.ticket_workflow:
                    messages.info(request, 'Tickets have already started for this ceremony.')
                    return redirect('dashboard')
                start_tickets_form = StartTicketsForm(request.POST, request.FILES, instance=current)
                if start_tickets_form.is_valid():
                    start_tickets_form.save()
                    messages.success(request, 'Tickets started. Reservation options are now available in attendee portals.')
                    return redirect('dashboard')
            open_modal = 'startTicketsModal'
        if request.POST.get('action') == 'ticket_settings':
            current = get_object_or_404(Ceremony, is_active=True)
            ticket_settings_form = TicketSettingsForm(request.POST, instance=current)
            if ticket_settings_form.is_valid():
                ticket_settings_form.save()
                messages.success(request, 'Ticket settings saved for this ceremony.')
                return redirect('dashboard')
            open_modal = 'ticketSettingsModal'
        if request.POST.get('action') in ('approve_reservation', 'decline_reservation'):
            with transaction.atomic():
                reservation = get_object_or_404(GuestReservation.objects.select_for_update(), pk=request.POST.get('reservation_id') or request.POST.get('ticket_id'), status=GuestReservation.Status.PENDING, ceremony__is_active=True)
                if request.POST.get('action') == 'approve_reservation':
                    User.objects.select_for_update().get(pk=reservation.owner_id)
                    if issued_count(reservation.owner, reservation.ceremony) >= ticket_limit(reservation.owner, reservation.ceremony):
                        messages.error(request, 'This account has reached its total ticket limit. The request remains pending.')
                        return redirect('dashboard')
                    if reservation.ticket_type == 'STUDENT' and Ticket.objects.filter(owner=reservation.owner, ceremony=reservation.ceremony, ticket_type='STUDENT').exists():
                        messages.error(request, 'This student already has a personal pass.')
                        return redirect('dashboard')
                    Ticket.objects.create(owner=reservation.owner, ceremony=reservation.ceremony, ticket_type=reservation.ticket_type, price_amount=150 if reservation.ticket_type == 'GUEST' and reservation.ceremony.ticket_workflow != 'requests' else 0, guest_relation=reservation.guest_relation, guest_name=reservation.guest_name, payment_receipt=reservation.payment_receipt)
                    reservation.delete()
                    messages.success(request, 'Reservation approved. The QR ticket has been issued.')
                else:
                    reservation.status = GuestReservation.Status.DECLINED
                    reservation.save(update_fields=['status'])
                    messages.success(request, 'Reservation declined. No ticket was issued.')
            return redirect('dashboard')
        if request.POST.get('action') == 'program_flow_save':
            ceremony = get_object_or_404(Ceremony, is_active=True)
            try:
                entries = json.loads(request.POST.get('items', ''))
            except (ValueError, TypeError):
                return JsonResponse({'error': 'Invalid program list.'}, status=400)
            if not isinstance(entries, list) or len(entries) > 500:
                return JsonResponse({'error': 'Enter a program list of up to 500 items.'}, status=400)
            with transaction.atomic():
                existing = {item.pk: item for item in ceremony.program_items.select_for_update()}
                forms, seen = [], set()
                for index, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        return JsonResponse({'error': 'Invalid program item.'}, status=400)
                    item_id = entry.get('id')
                    if item_id is not None and (type(item_id) is not int or item_id not in existing or item_id in seen):
                        return JsonResponse({'error': 'An item is invalid or belongs to another ceremony. Reload the page.'}, status=400)
                    seen.add(item_id) if item_id is not None else None
                    form = ProgramItemForm(entry, instance=existing.get(item_id))
                    if not form.is_valid():
                        return JsonResponse({'error': f'Item {index + 1}: ' + '; '.join(f'{field}: {", ".join(errors)}' for field, errors in form.errors.items())}, status=400)
                    forms.append(form)
                for position, form in enumerate(forms):
                    item = form.save(commit=False)
                    item.ceremony = ceremony
                    item.position = position
                    item.save()
                ceremony.program_items.filter(pk__in=set(existing) - seen).delete()
                ceremony.program_saved_at = timezone.now()
                ceremony.save(update_fields=['program_saved_at'])
            return JsonResponse({'ok': True})
        if request.POST.get('action') in ('program_item_create', 'program_item_update'):
            ceremony = Ceremony.objects.filter(is_active=True).first()
            if not ceremony:
                messages.error(request, 'Start a ceremony before adding a program flow.')
                return redirect('dashboard')
            instance = None
            if request.POST.get('action') == 'program_item_update':
                instance = get_object_or_404(ProgramItem, pk=request.POST.get('program_item_id'), ceremony=ceremony)
            program_item_form = ProgramItemForm(request.POST, instance=instance)
            if program_item_form.is_valid():
                item = program_item_form.save(commit=False)
                item.ceremony = ceremony
                if instance is None:
                    item.position = ceremony.program_items.count()
                item.save()
                ceremony.program_saved_at = timezone.now()
                ceremony.save(update_fields=['program_saved_at'])
                messages.success(request, 'Program flow item saved.')
                return redirect('dashboard')
            open_modal = 'programItemModal'
        if request.POST.get('action') in ('student_edit', 'student_disable', 'student_enable', 'student_delete'):
            if not Ceremony.objects.filter(is_active=True).exists():
                messages.error(request, 'Start a ceremony before managing students.')
                return redirect('dashboard')
            with transaction.atomic():
                student = get_object_or_404(Student.objects.select_for_update(), pk=request.POST.get('student_id'), archived_ceremony__isnull=True)
                profile = getattr(student, 'profile', None)
                action = request.POST['action']
                if action == 'student_edit':
                    student_edit_form = StudentForm(request.POST, instance=student, prefix='edit')
                    if student_edit_form.is_valid():
                        student_edit_form.save()
                        if profile:
                            profile.user.username = student.tupc_id
                            profile.user.first_name, profile.user.last_name = student.account_names
                            profile.user.first_name = profile.user.first_name[:150]
                            profile.user.last_name = profile.user.last_name[:150]
                            profile.user.save(update_fields=['username', 'first_name', 'last_name'])
                        messages.success(request, 'Student details updated.')
                        return redirect('dashboard')
                    editing_student = student
                    open_modal = 'studentEditModal'
                elif action in ('student_disable', 'student_enable'):
                    student.is_active = action == 'student_enable'
                    student.save(update_fields=['is_active'])
                    if profile:
                        profile.user.is_active = student.is_active
                        profile.user.save(update_fields=['is_active'])
                    messages.success(request, 'Student enabled.' if student.is_active else 'Student disabled.')
                    return redirect('dashboard')
                else:
                    if profile:
                        profile.user.is_active = False
                        profile.user.save(update_fields=['is_active'])
                        profile.student = None
                        profile.save(update_fields=['student'])
                    student.delete()
                    messages.success(request, 'Student removed from the roster. Existing ticket records have been retained.')
                    return redirect('dashboard')
        if request.POST.get('action') == 'student_access_code':
            profile = get_object_or_404(StudentProfile, student_id=request.POST.get('student_id'), student__archived_ceremony__isnull=True, user__is_staff=False)
            request.session['issued_student_code'] = {'name': profile.student.name, 'code': issue_access_code(profile)}
            return redirect('dashboard')
        if request.POST.get('action') == 'student':
            if not Ceremony.objects.filter(is_active=True).exists():
                messages.error(request, 'Start a ceremony before adding eligible students.')
                return redirect('dashboard')
            student_form = StudentForm(request.POST)
            if student_form.is_valid():
                student_form.save()
                messages.success(request, 'Student added. They can now create an account with their TUP ID.')
                return redirect('dashboard')
            open_modal = 'studentModal'
        elif request.POST.get('action') == 'admin_ticket':
            ceremony = Ceremony.objects.filter(is_active=True).first()
            if not ceremony:
                messages.error(request, 'Start a ceremony before generating an admin ticket.')
                return redirect('dashboard')
            Ticket.objects.create(owner=request.user, ceremony=ceremony, ticket_type=Ticket.TicketType.ADMIN)
            messages.success(request, 'A new admin ticket is ready. Scanning it activates both gates together. It is excluded from attendance totals.')
            return redirect('dashboard')
        elif request.POST.get('action') == 'faculty':
            ceremony = Ceremony.objects.filter(is_active=True).first()
            if not ceremony:
                messages.error(request, 'Start a ceremony before adding faculty accounts.')
                return redirect('dashboard')
            faculty_form = FacultyForm(request.POST)
            if faculty_form.is_valid():
                with transaction.atomic():
                    faculty = faculty_form.save(commit=False)
                    faculty_user = User(username=f"FAC-{uuid.uuid4().hex[:8].upper()}", first_name=faculty.name[:150], email=faculty_form.cleaned_data["email"])
                    faculty_user.set_unusable_password()
                    faculty_user.save()
                    faculty.user = faculty_user
                    faculty.current_access_code = f'FAC-{uuid.uuid4().hex[:6].upper()}'
                    faculty.save()
                    Ticket.objects.create(owner=faculty_user, ceremony=ceremony, ticket_type=Ticket.TicketType.FACULTY)
                messages.success(request, 'Faculty account and Gate 1 pass created.')
                return redirect('dashboard')
            open_modal = 'facultyModal'
        elif request.POST.get('action') == 'ceremony':
            ceremony_form = CeremonyForm(request.POST)
            if ceremony_form.is_valid():
                with transaction.atomic():
                    for previous in Ceremony.objects.select_for_update().filter(is_active=True):
                        complete_ceremony(previous)
                    ceremony = ceremony_form.save(commit=False)
                    ceremony.is_active = True
                    ceremony.save()
                messages.success(request, 'New ceremony announced. Home and ticket reservations are updated.')
                return redirect('dashboard')
        elif request.POST.get('action') == 'close_ceremony':
            with transaction.atomic():
                completed = Ceremony.objects.select_for_update().filter(is_active=True).first()
                if completed:
                    complete_ceremony(completed)
            messages.success(request, 'Ceremony completed. Students, faculty accounts, and tickets are archived in History. The next ceremony will start with an empty roster.')
            if completed:
                return redirect(f"{reverse('history')}?ceremony={completed.pk}")
            return redirect('dashboard')
    ceremony = selected_ceremony if is_history else Ceremony.objects.filter(is_active=True).first()
    ticket_list = Ticket.objects.select_related("owner").filter(ceremony=ceremony).order_by("-purchased_at") if ceremony else Ticket.objects.none()
    counted_tickets = ticket_list.exclude(ticket_type=Ticket.TicketType.ADMIN)
    total = counted_tickets.count()
    used = counted_tickets.filter(checked_in_at__isnull=False).count()
    guests = ticket_list.filter(ticket_type=Ticket.TicketType.GUEST).count()
    revenue = sum(ticket.price for ticket in counted_tickets)
    students = Student.objects.filter(archived_ceremony__isnull=True).select_related('profile').order_by('tupc_id')
    faculty_accounts = Faculty.objects.select_related('user').filter(user__tickets__ceremony=ceremony, user__tickets__ticket_type=Ticket.TicketType.FACULTY).distinct().order_by('name') if ceremony else Faculty.objects.none()
    if is_history and ceremony:
        if ceremony.roster_snapshot is not None:
            students = ceremony.roster_snapshot['students']
            faculty_accounts = ceremony.roster_snapshot['faculty']
        else:
            # Older ceremonies have ticket records but no saved eligibility snapshot.
            students = Student.objects.select_related('profile').filter(profile__user__tickets__ceremony=ceremony, profile__user__tickets__ticket_type=Ticket.TicketType.STUDENT).distinct().order_by('tupc_id')
    ticket_table = dashboard_table(request, ticket_list, 'tickets', 'Ticket audit', ['code', 'owner__username', 'owner__first_name', 'owner__last_name', 'owner__email', 'ticket_type'])
    student_table = dashboard_table(request, students, 'students', 'Eligible students', ['tupc_id', 'name', 'program_section'])
    faculty_table = dashboard_table(request, faculty_accounts, 'faculty', 'Faculty attendees', ['employee_id', 'name', 'department', 'campus', 'user__email'])
    admission_rows = GateAdmission.objects.filter(ticket__ceremony=ceremony).select_related('ticket__owner', 'operator').order_by('-created_at', '-pk') if is_history and ceremony else GateAdmission.objects.none()
    entry_table = dashboard_table(request, admission_rows, 'entries', 'Entry log', ['ticket__code', 'ticket__guest_name', 'ticket__owner__username', 'ticket__owner__first_name', 'ticket__owner__last_name', 'direction', 'operator__username'])
    return render(request, "events/history.html" if is_history else "events/dashboard.html", {
        'issued_student_code': request.session.pop('issued_student_code', None),
        'admin_ticket': ticket_list.filter(owner=request.user, ticket_type=Ticket.TicketType.ADMIN).first(),
        'entry_table': entry_table, 'admissions': entry_table['page'], 'tickets': ticket_table['page'], 'ticket_table': ticket_table, 'student_table': student_table, 'faculty_table': faculty_table, 'total': total, 'used': used, 'guests': guests, 'revenue': revenue,
        'start_tickets_form': start_tickets_form if start_tickets_form is not None else StartTicketsForm(),
        'ticket_settings_form': ticket_settings_form if ticket_settings_form is not None else TicketSettingsForm(instance=ceremony), 'student_form': student_form, 'faculty_form': faculty_form, 'ceremony_form': ceremony_form, 'program_item_form': program_item_form,
        'program_items': ceremony.program_items.all() if ceremony else ProgramItem.objects.none(),
        'program_editor_items': list(ceremony.program_items.values('id', 'item_type', 'title', 'description', 'speaker', 'hymn_language')) if ceremony else [],
        'pending_reservations': GuestReservation.objects.select_related('owner').filter(ceremony=ceremony, status=GuestReservation.Status.PENDING) if ceremony and not is_history else GuestReservation.objects.none(),
        'students': student_table['page'], 'faculty_accounts': faculty_table['page'], 'ceremony': ceremony,
        'ceremonies': Ceremony.objects.filter(is_active=False).order_by('-starts_at'),
        'is_history': is_history, 'open_modal': open_modal,
        'student_edit_form': student_edit_form, 'editing_student': editing_student,
    })


@require_POST
def check_student(request):
    student = Student.objects.filter(tupc_id=request.POST.get('tupc_id', '').strip().upper(), is_active=True, archived_ceremony__isnull=True).first()
    if not student or User.objects.filter(username__iexact=student.tupc_id).exists():
        return JsonResponse({'error': 'ID unavailable for registration. Check with the administrator or sign in if you already have an account.'}, status=400)
    first_name, last_name = student.account_names
    return JsonResponse({'first_name': first_name, 'last_name': last_name, 'program_section': student.program_section})
