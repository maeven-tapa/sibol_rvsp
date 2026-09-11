from django.contrib.auth.decorators import user_passes_test
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .models import Ticket, Ceremony, GateAdmission
from . import relay

staff = user_passes_test(lambda u: u.is_active and u.is_staff)


@staff
def setup(request):
    error = None
    available = relay.ports()
    if request.method == 'POST':
        mode = request.POST.get('mode')
        port = request.POST.get('port', '')
        try:
            duration = float(request.POST.get('duration', '1'))
            if mode not in ('entry', 'in_out', 'verify') or not 0.2 <= duration <= 5:
                raise ValueError()
            if mode != 'verify':
                # Open/close only: setup must never actuate the gate.
                with relay.connection(port):
                    pass
            request.session['gate_setup'] = {'mode': mode, 'port': port if mode != 'verify' else '', 'duration': duration, 'swapped': request.POST.get('swapped') == '1'}
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({'scanner_url': reverse('gate_scanner'), 'entry_url': reverse('gate_entries')})
            return redirect('gate_scanner')
        except ValueError:
            error = 'Select a mode and a pulse duration between 0.2 and 5 seconds.'
        except relay.RelayError as exc:
            error = str(exc)
    if error and request.headers.get('Accept') == 'application/json':
        return JsonResponse({'error': error}, status=400)
    return render(request, 'events/gate_setup.html', {'ports': available, 'error': error})


@staff
def scanner(request):
    config = request.session.get('gate_setup')
    if not config:
        return redirect('gate')
    return render(request, 'events/gate.html', {'config': config, 'ceremony': Ceremony.objects.filter(is_active=True).first()})


@staff
@require_POST
def scan(request):
    config = request.session.get('gate_setup')
    if not config:
        return JsonResponse({'error': 'Choose a mode and USB port in entry setup first.'}, status=400)
    code = request.POST.get('code', '').strip().upper()
    ticket = Ticket.objects.select_related('owner', 'ceremony').filter(code=code).first()
    def fail(message, status=400):
        data = {'error': message, 'result': 'already_entered' if status == 409 else 'invalid' if status == 400 else 'error'}
        if ticket:
            data.update(name=ticket.guest_name or ticket.owner.get_full_name() or ticket.owner.username, type=ticket.get_ticket_type_display())
            if status == 409:
                ticket.refresh_from_db(fields=['checked_in_at', 'exited_at'])
                admission = ticket.admissions.order_by('created_at').first()
                entered_at = ticket.checked_in_at
                data['admission_pending'] = ticket.admissions.exclude(status='sent').exists()
                data['exited'] = ticket.exited_at is not None
                recorded_at = entered_at or (admission.created_at if admission else None)
                data['entry_time'] = timezone.localtime(recorded_at).strftime('%b %d, %Y %I:%M:%S %p') if recorded_at else ''
        return JsonResponse(data, status=status)
    if not ticket:
        return fail('Ticket not found. Present a Sibol QR pass.')
    if not ticket.ceremony or not ticket.ceremony.is_active:
        return fail('This pass is not for the active ceremony.')
    if ticket.ticket_type == Ticket.TicketType.GUEST and ticket.reservation_status != 'approved':
        return fail('This guest reservation is awaiting administrator approval.')
    if not ticket.owner.is_active:
        return fail('This account is disabled.')
    is_admin = ticket.ticket_type == Ticket.TicketType.ADMIN
    if is_admin and not (ticket.owner.is_active and ticket.owner.is_staff):
        return fail('This admin account is no longer active.')
    channel = 2 if ticket.ticket_type == Ticket.TicketType.GUEST else 1
    gate = channel
    channel = 3 - channel if config.get('swapped') else channel
    direction = 'exit' if config['mode'] == 'in_out' and ticket.is_used else 'entry'
    channels = [1, 2] if is_admin or direction == 'exit' else [channel]

    def blocked(current):
        if current.exited_at or current.admissions.exclude(status='sent').exists():
            return True
        if direction == 'exit':
            return not current.is_used or current.admissions.filter(direction='exit').exists()
        return current.is_used or current.admissions.exists()

    if blocked(ticket):
        return fail('This ticket has already completed its scan or has an admission pending inspection.', 409)
    data = {'name': ticket.guest_name or ticket.owner.get_full_name() or ticket.owner.username, 'type': ticket.get_ticket_type_display(), 'relay': channel, 'gate': gate, 'gates': [1, 2] if is_admin or direction == 'exit' else [gate], 'relays': channels, 'code': ticket.code, 'direction': direction}
    if config['mode'] == 'verify':
        return JsonResponse({**data, 'message': 'Valid reservation · ticket remains unused', 'admitted': False})
    admissions = []
    try:
        with relay.connection(config['port']) as device:
            # Claim all entrances before sending any commands. Claims survive hardware errors.
            with transaction.atomic():
                locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
                if blocked(locked):
                    return fail('This ticket has already entered.', 409)
                admissions = [GateAdmission.objects.create(ticket=ticket, operator=request.user, port=config['port'], relay=number, direction=direction) for number in channels]
            if len(channels) == 2:
                relay.pulse_many(device, channels, config['duration'])
            else:
                relay.pulse(device, channel, config['duration'])
            for admission in admissions:
                admission.status = 'sent'
                admission.save(update_fields=['status'])
            Ticket.objects.filter(pk=ticket.pk).update(**{'exited_at' if direction == 'exit' else 'checked_in_at': timezone.now()})
    except IntegrityError:
        return fail('This ticket is already being admitted. Do not scan it again.', 409)
    except relay.RelayError as exc:
        if admissions:
            GateAdmission.objects.filter(pk__in=[row.pk for row in admissions], status='pending').update(status='uncertain', detail=str(exc))
            return fail('Relay communication failed during admission. The ticket is held for admin inspection; check the physical gate before retrying.', 503)
        return fail(str(exc), 503)
    return JsonResponse({**data, 'message': 'Exit granted · Both gates' if direction == 'exit' else 'Access granted · Both gates' if is_admin else f'Access granted · Gate {gate}', 'admitted': True})


@never_cache
@staff
def entries(request):
    if not request.session.get('gate_setup'):
        return redirect('gate')
    ceremony = Ceremony.objects.filter(is_active=True).first()
    rows = GateAdmission.objects.filter(ticket__ceremony=ceremony).select_related('ticket__owner', 'operator').order_by('-created_at', '-pk')[:200] if ceremony else []
    if request.GET.get('format') == 'json':
        return JsonResponse({'entries': [dict(time=timezone.localtime(row.created_at).strftime('%b %d, %Y %I:%M:%S %p'), name=row.ticket.owner.get_full_name() or row.ticket.owner.username, code=row.ticket.code, type=row.ticket.get_ticket_type_display(), relay=row.relay, direction=row.get_direction_display(), status=row.get_status_display(), operator=row.operator.username) for row in rows]})
    return render(request, 'events/gate_entries.html', {'ceremony': ceremony})
