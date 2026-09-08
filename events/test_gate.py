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
    def test_admin_can_enter_each_gate_once(self, pulse, connection):
        self.configure()
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        for channel in (1, 2):
            response = self.client.post('/gate/scan/', {'code': ticket.code, 'admin_gate': channel})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(pulse.call_args.args[1], channel)
            self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code, 'admin_gate': channel}).status_code, 409)
        self.assertEqual(pulse.call_count, 2)
        self.assertEqual(GateAdmission.objects.filter(ticket=ticket).count(), 2)

    @patch('events.gate_views.relay.pulse')
    def test_admin_gate_validation_and_revoked_owner(self, pulse):
        self.configure('verify')
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code, 'admin_gate': '3'}).status_code, 400)
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code, 'admin_gate': '2'}).status_code, 200)
        ticket.owner = self.user
        ticket.save()
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code, 'admin_gate': '2'}).status_code, 400)
        pulse.assert_not_called()



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
