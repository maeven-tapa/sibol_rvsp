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
from django.utils import timezone
from .forms import SignUpForm, StudentForm, CeremonyForm, AccessCodeForm, AdminLoginForm, FacultyForm, ProgramItemForm
from .models import Ticket, Student, Ceremony, Faculty, StudentProfile, ProgramItem, TicketTransfer
import uuid
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.conf import settings
from .access_codes import issue_access_code, code_digest


def ensure_student_ticket(user, ceremony):
    """Give every eligible account its included student pass for this ceremony."""
    if ceremony and not user.is_staff:
        Ticket.objects.get_or_create(owner=user, ceremony=ceremony, ticket_type=Ticket.TicketType.STUDENT)

def home(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("dashboard")
    ceremony = Ceremony.objects.filter(is_active=True).first()
    graduates = Student.objects.count() + Faculty.objects.count()
    guests = ceremony.tickets.filter(ticket_type=Ticket.TicketType.GUEST).count() if ceremony else 0
    return render(request, "events/home.html", {'ceremony': ceremony, 'graduates': graduates, 'guests': guests, 'expected': graduates + guests})


def program_flow(request):
    ceremony = Ceremony.objects.filter(is_active=True).first()
    items = ceremony.program_items.all() if ceremony else ProgramItem.objects.none()
    lyrics = {'english': '', 'tagalog': ''}
    for language in lyrics:
        with open(f'{settings.BASE_DIR}/static/txt/tup_hymn_{"eng" if language == "english" else "tagalog"}.txt', encoding='utf-8') as source:
            lyrics[language] = source.read()
    return render(request, 'events/program_flow.html', {'ceremony': ceremony, 'items': items, 'lyrics': lyrics})

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
    ensure_student_ticket(request.user, ceremony)
    with transaction.atomic():
        guest_count = Ticket.objects.select_for_update().filter(owner=request.user, ceremony=ceremony, ticket_type=Ticket.TicketType.GUEST).count()
        if guest_count >= 2:
            messages.error(request, "Each student may reserve a maximum of two guest tickets.")
            return redirect("tickets")
        Ticket.objects.create(owner=request.user, ticket_type=Ticket.TicketType.GUEST, ceremony=ceremony)
    messages.success(request, "Your guest ticket is confirmed!")
    return redirect("tickets")


@login_required
@require_POST
def reserve_guests(request):
    ceremony = Ceremony.objects.filter(is_active=True).first()
    count = int(request.POST.get('count', 0) or 0)
    relation = request.POST.get('relation', '')
    guest_name = request.POST.get('guest_name', '').strip()
    if not ceremony or count not in (1, 2) or relation not in ('Relative', 'Friend') or not request.FILES.get('receipt'):
        messages.error(request, 'Choose one or two tickets, a guest type, and upload your payment receipt.')
        return redirect('tickets')
    with transaction.atomic():
        existing = Ticket.objects.select_for_update().filter(owner=request.user, ceremony=ceremony, ticket_type=Ticket.TicketType.GUEST).count()
        if existing + count > 2:
            messages.error(request, 'You may reserve a maximum of two guest tickets.')
            return redirect('tickets')
        for number in range(count):
            Ticket.objects.create(owner=request.user, ceremony=ceremony, ticket_type=Ticket.TicketType.GUEST, guest_relation=relation, guest_name=guest_name if count == 1 else f'{guest_name or relation} {number + 1}', payment_receipt=request.FILES['receipt'], reservation_status='pending')
    messages.success(request, 'Guest ticket reservation request submitted for administrator approval.')
    return redirect('tickets')


@login_required
@require_POST
def transfer_ticket(request):
    ticket = get_object_or_404(Ticket, pk=request.POST.get('ticket_id'), owner=request.user, ticket_type=Ticket.TicketType.GUEST, reservation_status='approved', checked_in_at__isnull=True)
    recipient = User.objects.filter(username__iexact=request.POST.get('recipient_id', '').strip()).exclude(pk=request.user.pk).first()
    if not recipient or recipient.is_staff:
        messages.error(request, 'Enter the receiving student’s TUP ID.')
    elif TicketTransfer.objects.filter(ticket=ticket).exists():
        messages.error(request, 'This ticket already has a transfer request.')
    else:
        TicketTransfer.objects.create(ticket=ticket, sender=request.user, recipient=recipient)
        messages.success(request, 'Transfer request sent. The ticket remains yours until the student accepts it.')
    return redirect('tickets')


@login_required
@require_POST
def accept_transfer(request, transfer_id):
    transfer = get_object_or_404(TicketTransfer, pk=transfer_id, recipient=request.user, accepted_at__isnull=True)
    with transaction.atomic():
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
    guest_count = request.user.tickets.filter(ceremony=ceremony, ticket_type=Ticket.TicketType.GUEST).exclude(reservation_status='declined').count() if ceremony else 0
    incoming_transfers = TicketTransfer.objects.select_related('ticket', 'sender').filter(recipient=request.user, accepted_at__isnull=True)
    tickets = request.user.tickets.select_related('ceremony').exclude(reservation_status='declined').annotate(ticket_order=Case(When(ticket_type=Ticket.TicketType.STUDENT, then=0), default=1, output_field=IntegerField())).order_by('ticket_order', 'purchased_at')
    return render(request, "events/tickets.html", {"tickets": tickets, 'ceremony': ceremony, 'guest_count': guest_count, 'guest_slots': max(0, 2 - guest_count), 'incoming_transfers': incoming_transfers})

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


def complete_ceremony(ceremony):
    # Preserve roster details and registration state as they were at completion.
    students = Student.objects.select_related('profile').order_by('tupc_id')
    faculty = Faculty.objects.select_related('user').filter(user__tickets__ceremony=ceremony, user__tickets__ticket_type=Ticket.TicketType.FACULTY).distinct().order_by('name')
    ceremony.roster_snapshot = {
        'students': [dict(tupc_id=row.tupc_id, name=row.name, course=row.course, section=row.section, profile=hasattr(row, 'profile')) for row in students],
        'faculty': [dict(employee_id=row.employee_id, name=row.name, department=row.department, campus=row.campus, user=dict(username=row.user.username, email=row.user.email)) for row in faculty],
    }
    ceremony.is_active = False
    ceremony.completed_at = timezone.now()
    ceremony.save(update_fields=['roster_snapshot', 'is_active', 'completed_at'])


@never_cache
@user_passes_test(lambda user: user.is_staff)
def dashboard(request):
    history_id = request.GET.get('ceremony', '')
    is_history = bool(history_id)
    selected_ceremony = None
    if is_history:
        if not history_id.isdecimal():
            raise Http404('Ceremony not found.')
        selected_ceremony = get_object_or_404(Ceremony, pk=history_id, is_active=False)
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
    student_form, ceremony_form, faculty_form, program_item_form = StudentForm(), CeremonyForm(), FacultyForm(), ProgramItemForm()
    open_modal = ''
    if request.method == 'POST':
        if request.POST.get('action') in ('approve_reservation', 'decline_reservation'):
            ticket = get_object_or_404(Ticket, pk=request.POST.get('ticket_id'), ticket_type=Ticket.TicketType.GUEST, reservation_status='pending')
            ticket.reservation_status = 'approved' if request.POST.get('action') == 'approve_reservation' else 'declined'
            ticket.save(update_fields=['reservation_status'])
            messages.success(request, f'Reservation {ticket.reservation_status}.')
            return redirect('dashboard')
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
                messages.success(request, 'Program flow item saved.')
                return redirect('dashboard')
            open_modal = 'programItemModal'
        if request.POST.get('action') == 'student_access_code':
            profile = get_object_or_404(StudentProfile, student_id=request.POST.get('student_id'), user__is_staff=False)
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
            Ticket.objects.get_or_create(owner=request.user, ceremony=ceremony, ticket_type=Ticket.TicketType.ADMIN)
            messages.success(request, 'Your admin ticket is ready. It permits one admission at each gate and is excluded from attendance totals.')
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
            messages.success(request, 'Ceremony marked complete. Home information cards, reservations, and student roster are now hidden.')
            if completed:
                return redirect(f"{request.path}?ceremony={completed.pk}")
            return redirect('dashboard')
    ceremony = selected_ceremony if is_history else Ceremony.objects.filter(is_active=True).first()
    ticket_list = Ticket.objects.select_related("owner").filter(ceremony=ceremony).order_by("-purchased_at") if ceremony else Ticket.objects.none()
    counted_tickets = ticket_list.exclude(ticket_type=Ticket.TicketType.ADMIN)
    total = counted_tickets.count()
    used = counted_tickets.filter(checked_in_at__isnull=False).count()
    guests = ticket_list.filter(ticket_type=Ticket.TicketType.GUEST).count()
    revenue = sum(ticket.price for ticket in counted_tickets)
    students = Student.objects.select_related('profile').order_by('tupc_id')
    faculty_accounts = Faculty.objects.select_related('user').filter(user__tickets__ceremony=ceremony, user__tickets__ticket_type=Ticket.TicketType.FACULTY).distinct().order_by('name') if ceremony else Faculty.objects.none()
    if is_history:
        if ceremony.roster_snapshot is not None:
            students = ceremony.roster_snapshot['students']
            faculty_accounts = ceremony.roster_snapshot['faculty']
        else:
            # Older ceremonies have ticket records but no saved eligibility snapshot.
            students = students.filter(profile__user__tickets__ceremony=ceremony, profile__user__tickets__ticket_type=Ticket.TicketType.STUDENT).distinct()
    ticket_table = dashboard_table(request, ticket_list, 'tickets', 'Ticket audit', ['code', 'owner__username', 'owner__first_name', 'owner__last_name', 'owner__email', 'ticket_type'])
    student_table = dashboard_table(request, students, 'students', 'Eligible students', ['tupc_id', 'name', 'course', 'section'])
    faculty_table = dashboard_table(request, faculty_accounts, 'faculty', 'Faculty attendees', ['employee_id', 'name', 'department', 'campus', 'user__email'])
    return render(request, "events/dashboard.html", {
        'issued_student_code': request.session.pop('issued_student_code', None),
        'admin_ticket': ticket_list.filter(owner=request.user, ticket_type=Ticket.TicketType.ADMIN).first(),
        'tickets': ticket_table['page'], 'ticket_table': ticket_table, 'student_table': student_table, 'faculty_table': faculty_table, 'total': total, 'used': used, 'guests': guests, 'revenue': revenue,
        'student_form': student_form, 'faculty_form': faculty_form, 'ceremony_form': ceremony_form, 'program_item_form': program_item_form,
        'program_items': ceremony.program_items.all() if ceremony else ProgramItem.objects.none(),
        'pending_reservations': Ticket.objects.select_related('owner').filter(ceremony=ceremony, ticket_type=Ticket.TicketType.GUEST, reservation_status='pending') if ceremony and not is_history else Ticket.objects.none(),
        'students': student_table['page'], 'faculty_accounts': faculty_table['page'], 'ceremony': ceremony,
        'ceremonies': Ceremony.objects.filter(is_active=False).order_by('-starts_at'),
        'is_history': is_history, 'open_modal': open_modal,
    })


@require_POST
def check_student(request):
    student = Student.objects.filter(tupc_id=request.POST.get('tupc_id', '').strip().upper()).first()
    if not student or User.objects.filter(username__iexact=student.tupc_id).exists():
        return JsonResponse({'error': 'ID unavailable for registration. Check with the administrator or sign in if you already have an account.'}, status=400)
    first_name, _, last_name = student.name.partition(' ')
    return JsonResponse({'first_name': first_name, 'last_name': last_name, 'course': student.course, 'section': student.section})
