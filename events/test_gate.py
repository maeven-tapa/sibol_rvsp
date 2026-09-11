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

    @patch('events.gate_views.relay.ports')
    @patch('events.gate_views.relay.connection')
    def test_mobile_setup_only_offers_verification(self, connection, ports):
        for agent in ('Mozilla/5.0 (iPhone) Mobile', 'Mozilla/5.0 (Linux; Android 14)', 'Mozilla/5.0 (iPad)'):
            with self.subTest(agent=agent):
                response = self.client.get('/gate/', HTTP_USER_AGENT=agent)
                self.assertContains(response, 'Reservation check (Mobile)')
                self.assertNotContains(response, 'value="entry"')
                self.assertNotContains(response, 'value="in_out"')
                response = self.client.post('/gate/', {'mode': 'entry', 'port': 'COM3'}, HTTP_USER_AGENT=agent)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.client.session['gate_setup']['mode'], 'verify')
                self.assertEqual(self.client.session['gate_setup']['port'], '')
                station = self.client.get('/gate/scanner/', HTTP_USER_AGENT=agent)
                self.assertTemplateUsed(station, 'events/gate_mobile.html')
                self.assertContains(station, 'Reservation check (Mobile)')
        connection.assert_not_called()
        ports.assert_not_called()

    @patch('events.gate_views.relay.connection')
    def test_mobile_cannot_consume_ticket_from_desktop_session(self, connection):
        for mode in ('entry', 'in_out'):
            for headers, payload in (({'HTTP_USER_AGENT': 'iPhone Mobile'}, {}),
                                     ({'HTTP_SEC_CH_UA_MOBILE': '?1'}, {}),
                                     ({}, {'mobile': '1'})):
                self.configure(mode)
                response = self.client.post('/gate/scan/', {'code': self.ticket.code, **payload}, **headers)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()['admitted'])
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_used)
        self.assertIsNone(self.ticket.exited_at)
        self.assertFalse(self.ticket.admissions.exists())
        connection.assert_not_called()

    def test_client_detected_tablet_and_desktop_templates(self):
        self.configure()
        self.assertTemplateUsed(self.client.get('/gate/scanner/'), 'events/gate.html')
        self.assertTemplateUsed(self.client.get('/gate/scanner/?mobile=1'), 'events/gate_mobile.html')
        mobile = self.client.get('/gate/scanner/?mobile=1')
        self.assertNotContains(mobile, 'id="start-camera"')
        self.assertNotContains(mobile, 'id="stop-camera"')
        self.assertContains(mobile, 'SCAN A TICKET PASS')
        self.assertContains(self.client.get('/gate/scanner/'), 'SCAN A TICKET PASS')
        self.assertEqual(self.client.post('/gate/', {'mode': 'entry', 'mobile': '1'}).status_code, 302)
        self.assertTemplateUsed(self.client.get('/gate/scanner/'), 'events/gate_mobile.html')
        response = self.client.get('/gate/')
        self.assertContains(response, 'value="entry"')
        self.assertContains(response, 'value="in_out"')

    def test_csrf_required(self):
        client=Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post('/gate/scan/',{'code':self.ticket.code}).status_code,403)

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse_many')
    @patch('events.gate_views.relay.pulse')
    def test_in_out_entry_then_exit_for_every_ticket_type(self, pulse, both, connection):
        for swapped in ('0', '1'):
            response = self.client.post('/gate/', {'mode': 'in_out', 'port': 'COM3', 'duration': '1', 'swapped': swapped})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.session['gate_setup']['port'], '')
            for kind in ('STUDENT', 'FACULTY', 'GUEST', 'ADMIN'):
                ticket = Ticket.objects.create(owner=self.admin if kind == 'ADMIN' else self.user, ceremony=self.ceremony, ticket_type=kind)
                entry = self.client.post('/gate/scan/', {'code': ticket.code})
                self.assertEqual(entry.status_code, 200)
                self.assertEqual(entry.json()['direction'], 'entry')
                expected = 2 if kind == 'GUEST' else 1
                expected = 3 - expected if swapped == '1' else expected
                self.assertEqual(entry.json()['relays'], [])
                ticket.refresh_from_db()
                entered_at = ticket.checked_in_at
                response = self.client.post('/gate/scan/', {'code': ticket.code})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['direction'], 'exit')
                self.assertEqual(response.json()['gates'], [1, 2])
                both.assert_not_called(); pulse.assert_not_called(); connection.assert_not_called()
                ticket.refresh_from_db()
                self.assertIsNotNone(ticket.exited_at)
                self.assertEqual(ticket.checked_in_at, entered_at)
                self.assertEqual(ticket.admissions.filter(direction='exit', status='recorded').count(), 1)
                before = both.call_count
                self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code}).status_code, 409)
                self.assertEqual(both.call_count, before)
        self.assertContains(self.client.get('/gate/scanner/'), 'IN AND OUT')
        self.assertTrue(any(row['direction'] == 'Exit' for row in self.client.get('/gate/entries/?format=json').json()['entries']))

    @patch('events.gate_views.relay.connection', side_effect=AssertionError('Hardware must not be used'))
    def test_in_out_without_usb_settings_and_history(self, connection):
        self.assertEqual(self.client.post('/gate/', {'mode': 'in_out'}).status_code, 302)
        for direction in ('entry', 'exit'):
            response = self.client.post('/gate/scan/', {'code': self.ticket.code})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['direction'], direction)
        self.assertEqual(self.ticket.admissions.count(), 2)
        self.assertEqual(set(self.ticket.admissions.values_list('relay', flat=True)), {0})
        self.ceremony.is_active = False
        self.ceremony.save()
        session = self.client.session
        del session['gate_setup']
        session.save()
        other = Ceremony.objects.create(title='Other', starts_at=timezone.now(), venue='Hall')
        other_ticket = Ticket.objects.create(owner=self.user, ceremony=other, ticket_type='GUEST', guest_name='Other Guest')
        GateAdmission.objects.create(ticket=other_ticket, operator=self.admin, relay=0, port='', status='recorded')
        response = self.client.get(f'/history/?ceremony={self.ceremony.pk}')
        self.assertContains(response, 'Entry log')
        self.assertContains(response, 'Recorded', count=2)
        self.assertNotContains(response, 'Other Guest')
        self.assertContains(self.client.get(f'/history/?ceremony={self.ceremony.pk}&entries_q=missing'), 'No entries match your search.')
        connection.assert_not_called()

    @patch('events.gate_views.relay.connection')
    @patch('events.gate_views.relay.pulse_many')
    def test_admin_opens_both_gates_without_selector_and_blocks_repeat(self, pulse, connection):
        self.configure()
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        response = self.client.post('/gate/scan/', {'code': ticket.code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['relays'], [1, 2])
        pulse.assert_called_once_with(connection.return_value.__enter__.return_value, [1, 2], 1)
        self.assertEqual(self.client.post('/gate/scan/', {'code': ticket.code}).status_code, 409)
        self.assertEqual(pulse.call_count, 1)
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
    @patch('events.gate_views.relay.pulse_many', side_effect=relay.RelayError('Second relay failed'))
    def test_admin_partial_failure_is_held_without_repeating_first_relay(self, pulse, connection):
        self.configure()
        ticket = Ticket.objects.create(owner=self.admin, ceremony=self.ceremony, ticket_type='ADMIN')
        self.assertEqual(self.client.post('/gate/scan/', {'code':ticket.code}).status_code, 503)
        self.assertEqual(list(GateAdmission.objects.filter(ticket=ticket).order_by('relay').values_list('status', flat=True)), ['uncertain', 'uncertain'])
        self.assertEqual(self.client.post('/gate/scan/', {'code':ticket.code}).status_code, 409)
        self.assertEqual(pulse.call_count, 1)

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
    def test_both_relays_on_before_waiting_then_both_off(self, sleep):
        device = MagicMock()
        device.write.return_value = 3
        sleep.side_effect = lambda duration: self.assertEqual(
            [call.args[0] for call in device.write.call_args_list],
            [bytes([255, 1, 1]), bytes([255, 2, 1])],
        )
        relay.pulse_many(device, [1, 2], 1)
        sleep.assert_called_once_with(1)
        self.assertEqual([call.args[0] for call in device.write.call_args_list],
                         [bytes([255, 1, 1]), bytes([255, 2, 1]), bytes([255, 1, 0]), bytes([255, 2, 0])])

    @patch('events.relay.time.sleep')
    def test_both_off_attempted_when_first_off_fails(self, sleep):
        device = MagicMock()
        device.write.side_effect = [3, 3, 1, 3]
        with self.assertRaises(relay.RelayError):
            relay.pulse_many(device, [1, 2], 1)
        self.assertEqual(device.write.call_args.args[0], bytes([255, 2, 0]))

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
