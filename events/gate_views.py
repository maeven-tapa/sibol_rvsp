from django.contrib.auth.decorators import user_passes_test
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
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
            if mode not in ('entry', 'verify') or not 0.2 <= duration <= 5:
                raise ValueError()
            if mode == 'entry':
                # Open/close only: setup must never actuate the gate.
                with relay.connection(port):
                    pass
            request.session['gate_setup'] = {'mode': mode, 'port': port if mode == 'entry' else '', 'duration': duration}
            return redirect('gate_scanner')
        except ValueError:
            error = 'Select a mode and a pulse duration between 0.2 and 5 seconds.'
        except relay.RelayError as exc:
            error = str(exc)
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
        return JsonResponse({'error': message}, status=status)
    if not ticket:
        return fail('Ticket not found. Present a Sibol QR pass.')
    if not ticket.ceremony or not ticket.ceremony.is_active:
        return fail('This pass is not for the active ceremony.')
    if ticket.ticket_type == Ticket.TicketType.GUEST and ticket.reservation_status != 'approved':
        return fail('This guest reservation is awaiting administrator approval.')
    is_admin = ticket.ticket_type == Ticket.TicketType.ADMIN
    if is_admin and not (ticket.owner.is_active and ticket.owner.is_staff):
        return fail('This admin account is no longer active.')
    channel = 2 if ticket.ticket_type == Ticket.TicketType.GUEST else 1
    if is_admin:
        if request.POST.get('admin_gate') not in ('1', '2'):
            return fail('Select Gate 1 or Gate 2 for this admin pass.')
        channel = int(request.POST['admin_gate'])
    if ticket.is_used and not is_admin:
        return fail('This ticket has already been checked in.', 409)
    if GateAdmission.objects.filter(ticket=ticket, **({"relay": channel} if is_admin else {})).exists():
        return fail('This ticket has an admission attempt on record. Ask the administrator to inspect its gate log.', 409)
    data = {'name': ticket.owner.get_full_name() or ticket.owner.username, 'type': ticket.get_ticket_type_display(), 'relay': channel, 'code': ticket.code}
    if config['mode'] == 'verify':
        return JsonResponse({**data, 'message': 'Valid reservation · ticket remains unused', 'admitted': False})
    admission = None
    try:
        with relay.connection(config['port']) as device:
            # A unique ticket/gate claim prevents duplicate relay pulses.
            admission = GateAdmission.objects.create(ticket=ticket, operator=request.user, port=config['port'], relay=channel)
            relay.pulse(device, channel, config['duration'])
            admission.status = 'sent'
            admission.save(update_fields=['status'])
            Ticket.objects.filter(pk=ticket.pk).update(checked_in_at=timezone.now())
    except IntegrityError:
        return fail('This ticket is already being admitted. Do not scan it again.', 409)
    except relay.RelayError as exc:
        if admission:
            admission.status = 'uncertain'
            admission.detail = str(exc)
            admission.save(update_fields=['status', 'detail'])
            return fail('Relay communication failed during admission. The ticket is held for admin inspection; check the physical gate before retrying.', 503)
        return fail(str(exc), 503)
    return JsonResponse({**data, 'message': f'Welcome! Relay {channel} pulse sent · checked in', 'admitted': True})
