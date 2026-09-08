from unittest.mock import patch, MagicMock
from django.test import TestCase, SimpleTestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Ceremony, Ticket, GateAdmission
from . import relay


class GateTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('operator', is_staff=True)
        self.user = User.objects.create_user('student')
        self.ceremony = Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.ticket = Ticket.objects.create(owner=self.user, ceremony=self.ceremony, ticket_type='STUDENT')
        self.client.force_login(self.admin)

    def configure(self, mode='entry'):
        session=self.client.session
        session['gate_setup']={'mode':mode,'port':'COM3','duration':1}
        session.save()

    def test_setup_required_and_staff_only(self):
        self.assertRedirects(self.client.get('/gate/scanner/'), '/gate/')
        self.assertEqual(self.client.post('/gate/scan/', {'code':self.ticket.code}).status_code, 400)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/gate/').status_code, 302)
        self.assertEqual(self.client.post('/gate/scan/', {'code':self.ticket.code}).status_code, 302)

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse')
    def test_verify_never_switches_or_consumes(self, pulse, connection):
        self.configure('verify')
        response=self.client.post('/gate/scan/', {'code':self.ticket.code})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['admitted'])
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_used)
        self.assertFalse(GateAdmission.objects.exists())
        pulse.assert_not_called(); connection.assert_not_called()

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse')
    def test_student_guest_mapping_and_duplicate_block(self, pulse, connection):
        self.configure()
        for kind, number in [('STUDENT',1),('GUEST',2)]:
            ticket=Ticket.objects.create(owner=self.user, ceremony=self.ceremony, ticket_type=kind)
            response=self.client.post('/gate/scan/', {'code':ticket.code})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['relay'], number)
            self.assertEqual(pulse.call_args.args[1], number)
            ticket.refresh_from_db(); self.assertTrue(ticket.is_used)
            before=pulse.call_count
            self.assertEqual(self.client.post('/gate/scan/', {'code':ticket.code}).status_code, 409)
            self.assertEqual(pulse.call_count, before)

    @patch('events.gate_views.relay.connection', side_effect=relay.RelayError('Port disconnected'))
    def test_missing_port_does_not_claim_ticket(self, connection):
        self.configure()
        self.assertEqual(self.client.post('/gate/scan/', {'code':self.ticket.code}).status_code, 503)
        self.assertFalse(GateAdmission.objects.exists())
        self.ticket.refresh_from_db(); self.assertFalse(self.ticket.is_used)

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse', side_effect=relay.RelayError('Failed write'))
    def test_uncertain_pulse_held_without_retry(self, pulse, connection):
        self.configure()
        self.assertEqual(self.client.post('/gate/scan/', {'code':self.ticket.code}).status_code, 503)
        self.assertEqual(GateAdmission.objects.get().status,'uncertain')
        self.assertEqual(self.client.post('/gate/scan/', {'code':self.ticket.code}).status_code, 409)
        self.assertEqual(pulse.call_count, 1)

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse')
    def test_setup_does_not_switch_relay(self, pulse, connection):
        self.assertRedirects(self.client.post('/gate/', {'mode':'entry','port':'COM3','duration':'1'}),'/gate/scanner/')
        connection.assert_called_once_with('COM3'); pulse.assert_not_called()

    def test_csrf_required(self):
        client=Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post('/gate/scan/',{'code':self.ticket.code}).status_code,403)

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse')
    def test_admin_opens_both_gates_without_selector_and_blocks_repeat(self, pulse, connection):
        self.configure()
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        response = self.client.post('/gate/scan/', {'code': ticket.code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['relays'], [1, 2])
        self.assertEqual([call.args[1] for call in pulse.call_args_list], [1, 2])
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code}).status_code, 409)
        self.assertEqual(pulse.call_count, 2)
        self.assertEqual(GateAdmission.objects.filter(ticket=ticket).count(), 2)

    @patch('events.gate_views.relay.pulse')
    def test_admin_revoked_owner(self, pulse):
        self.configure('verify')
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code}).status_code, 200)
        ticket.owner = self.user
        ticket.save()
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code}).status_code, 400)
        pulse.assert_not_called()

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse')
    def test_swapped_assignment_reaches_correct_relay_and_logs(self, pulse, connection):
        response = self.client.post('/gate/', {'mode':'entry', 'port':'COM3', 'duration':'1', 'swapped':'1'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'scanner_url':'/gate/scanner/', 'entry_url':'/gate/entries/'})
        self.assertTrue(self.client.session['gate_setup']['swapped'])
        pulse.assert_not_called()
        for kind, gate, number in [('STUDENT', 1, 2), ('GUEST', 2, 1)]:
            ticket = Ticket.objects.create(owner=self.user, ceremony=self.ceremony, ticket_type=kind)
            response = self.client.post('/gate/scan/', {'code': ticket.code})
            self.assertEqual(response.json()['gate'], gate)
            self.assertEqual(response.json()['relay'], number)
            self.assertEqual(pulse.call_args.args[1], number)
            duplicate = self.client.post('/gate/scan/', {'code':ticket.code})
            self.assertEqual(duplicate.json()['result'], 'already_entered')
        entries = self.client.get('/gate/entries/?format=json').json()['entries']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['relay'], 1)
        self.assertEqual(entries[0]['status'], 'Pulse sent')

    def test_scanner_has_no_navigation_or_admin_selector(self):
        self.configure()
        response = self.client.get('/gate/scanner/')
        self.assertNotContains(response, 'Entrance for admin passes')
        self.assertNotContains(response, 'View admission log')
        self.assertNotContains(response, '<nav')
        self.assertContains(response, 'Admin passes grant access to both gates.')

    @patch('events.gate_views.relay.pulse')
    def test_invalid_and_disabled_pass_never_switches(self, pulse):
        self.configure()
        response = self.client.post('/gate/scan/', {'code':'INVALID'})
        self.assertEqual(response.json()['result'], 'invalid')
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.post('/gate/scan/', {'code':self.ticket.code}).status_code, 400)
        pulse.assert_not_called()

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse', side_effect=[None, relay.RelayError('Second relay failed')])
    def test_admin_partial_failure_is_held_without_repeating_first_relay(self, pulse, connection):
        self.configure()
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        self.assertEqual(self.client.post('/gate/scan/', {'code':ticket.code}).status_code, 503)
        self.assertEqual(list(GateAdmission.objects.filter(ticket=ticket).order_by('relay').values_list('status', flat=True)), ['sent', 'uncertain'])
        self.assertEqual(self.client.post('/gate/scan/', {'code':ticket.code}).status_code, 409)
        self.assertEqual(pulse.call_count, 2)

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse')
    def test_repeat_scan_includes_holder_and_entry_time(self, pulse, connection):
        self.configure()
        self.client.post('/gate/scan/', {'code':self.ticket.code})
        self.ticket.refresh_from_db()
        response = self.client.post('/gate/scan/', {'code':self.ticket.code})
        data = response.json()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(data['name'], self.user.username)
        self.assertEqual(data['type'], 'Student')
        self.assertFalse(data['admission_pending'])
        self.assertEqual(data['entry_time'], timezone.localtime(self.ticket.checked_in_at).strftime('%b %d, %Y %I:%M:%S %p'))
        self.assertEqual(pulse.call_count, 1)
        station = self.client.get('/gate/scanner/')
        self.assertNotContains(station, 'id="scan-result"')
        self.assertContains(station, 'id="camera-placeholder" role="status"')

    def test_entry_log_staff_only(self):
        self.configure()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/gate/entries/?format=json').status_code, 302)



class ProtocolTests(SimpleTestCase):
    @patch('events.relay.time.sleep')
    def test_binary_pulse_then_off(self, sleep):
        for channel in (1,2):
            device=MagicMock(); device.write.return_value=3
            relay.pulse(device,channel,1)
            self.assertEqual([c.args[0] for c in device.write.call_args_list],[bytes([255,channel,1]),bytes([255,channel,0])])

    def test_off_attempted_on_incomplete_on(self):
        device=MagicMock(); device.write.side_effect=[1,3]
        with self.assertRaises(relay.RelayError): relay.pulse(device,1,1)
        self.assertEqual(device.write.call_args.args[0],bytes([255,1,0]))
