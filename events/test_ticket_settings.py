from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from .models import Ceremony, Student, StudentProfile, Faculty, Ticket, GuestReservation, TicketTransfer


class TicketSettingsTests(TestCase):
    def setUp(self):
        self.ceremony = Ceremony.objects.create(ticket_workflow='selling', payment_qr='payment_qr/test.png', title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.admin = User.objects.create_user('admin', is_staff=True)
        self.student = User.objects.create_user('TUPC-22-0042')
        roster = Student.objects.create(tupc_id=self.student.username, name='Jamie Ramos', course='BSIT', section='4A')
        StudentProfile.objects.create(user=self.student, student=roster, contact_number='09123456789', access_code_digest='verified')
        self.client.force_login(self.student)

    def reserve(self, count=1):
        return self.client.post('/tickets/reserve/', {'count': count, 'relation': 'Relative', 'receipt': SimpleUploadedFile('proof.png', b'proof', content_type='image/png')})

    def test_defaults_and_admin_settings_validation(self):
        self.assertTrue(self.ceremony.auto_student_ticket)
        self.assertEqual(self.ceremony.student_ticket_limit, 3)
        self.client.post('/dashboard/', {'action': 'ticket_settings', 'student_ticket_limit': 8, 'faculty_ticket_limit': 4})
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.student_ticket_limit, 3)
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action': 'ticket_settings', 'student_ticket_limit': 8, 'faculty_ticket_limit': 4})
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.student_ticket_limit, 8)
        self.assertEqual(self.ceremony.faculty_ticket_limit, 4)
        self.assertFalse(self.ceremony.auto_student_ticket)
        for value in ('0', '-1', 'abc', '101'):
            response = self.client.post('/dashboard/', {'action': 'ticket_settings', 'student_ticket_limit': value, 'faculty_ticket_limit': 4})
            self.assertEqual(response.context['open_modal'], 'ticketSettingsModal')
            self.assertTrue(response.context['ticket_settings_form'].errors)
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.student_ticket_limit, 8)

    def test_student_total_includes_personal_and_pending_requests(self):
        self.ceremony.student_ticket_limit = 5
        self.ceremony.save()
        response = self.client.get('/tickets/')
        self.assertEqual(response.context['guest_slots'], 4)
        self.assertContains(response, 'value="4"')
        self.reserve(4)
        self.assertEqual(GuestReservation.objects.count(), 4)
        self.reserve(1)
        self.assertEqual(GuestReservation.objects.count(), 4)
        self.assertEqual(Ticket.objects.filter(ticket_type='STUDENT').count(), 1)
        self.assertEqual(self.client.get('/tickets/').context['guest_slots'], 0)

    def test_faculty_uses_separate_total_limit(self):
        faculty_user = User.objects.create_user('faculty')
        Faculty.objects.create(user=faculty_user, employee_id='F1', name='Faculty', department='IT', campus='Manila')
        Ticket.objects.create(owner=faculty_user, ceremony=self.ceremony, ticket_type='FACULTY')
        self.ceremony.faculty_ticket_limit = 2
        self.ceremony.student_ticket_limit = 7
        self.ceremony.save()
        self.client.force_login(faculty_user)
        self.assertEqual(self.client.get('/tickets/').context['guest_slots'], 1)
        self.reserve(2)
        self.assertFalse(GuestReservation.objects.exists())
        self.reserve(1)
        self.assertEqual(GuestReservation.objects.count(), 1)

    def test_manual_student_request_approval_and_duplicate_prevention(self):
        self.ceremony.auto_student_ticket = False
        self.ceremony.save()
        self.assertContains(self.client.get('/tickets/'), 'Request student ticket')
        self.assertFalse(Ticket.objects.exists())
        for _ in range(2):
            self.client.post('/tickets/reserve-student/')
        request = GuestReservation.objects.get()
        self.assertEqual(request.ticket_type, 'STUDENT')
        self.assertFalse(request.payment_receipt)
        self.assertNotContains(self.client.get('/tickets/'), 'Request student ticket')
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action': 'approve_reservation', 'reservation_id': request.pk})
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.ticket_type, 'STUDENT')
        self.assertEqual(ticket.price, 0)
        self.assertFalse(GuestReservation.objects.exists())
        self.client.force_login(self.student)
        self.client.post('/tickets/reserve-student/')
        self.assertFalse(GuestReservation.objects.exists())

    def test_manual_request_decline_allows_retry_and_is_account_scoped(self):
        self.ceremony.auto_student_ticket = False
        self.ceremony.save()
        self.client.post('/tickets/reserve-student/')
        request = GuestReservation.objects.get()
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action': 'decline_reservation', 'reservation_id': request.pk})
        self.client.force_login(self.student)
        self.assertContains(self.client.get('/tickets/'), 'Request student ticket')
        self.client.post('/tickets/reserve-student/')
        self.assertEqual(GuestReservation.objects.filter(status='pending').count(), 1)
        outsider = User.objects.create_user('outsider')
        self.client.force_login(outsider)
        self.client.post('/tickets/reserve-student/')
        self.assertFalse(GuestReservation.objects.filter(owner=outsider).exists())

    def test_lower_limit_preserves_tickets_and_blocks_approval_and_transfer(self):
        self.client.get('/tickets/')
        self.reserve()
        request = GuestReservation.objects.get()
        self.ceremony.student_ticket_limit = 1
        self.ceremony.save()
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action': 'approve_reservation', 'reservation_id': request.pk})
        self.assertTrue(GuestReservation.objects.filter(pk=request.pk, status='pending').exists())
        sender = User.objects.create_user('sender')
        guest = Ticket.objects.create(owner=sender, ceremony=self.ceremony, ticket_type='GUEST')
        transfer = TicketTransfer.objects.create(ticket=guest, sender=sender, recipient=self.student)
        self.client.force_login(self.student)
        self.client.post(f'/tickets/transfer/{transfer.pk}/accept/')
        guest.refresh_from_db()
        transfer.refresh_from_db()
        self.assertEqual(guest.owner, sender)
        self.assertIsNone(transfer.accepted_at)
        self.assertEqual(Ticket.objects.filter(owner=self.student).count(), 1)

    def test_automatic_mode_reenabled_does_not_duplicate_pending_personal_pass(self):
        self.ceremony.auto_student_ticket = False
        self.ceremony.save()
        self.client.post('/tickets/reserve-student/')
        self.ceremony.auto_student_ticket = True
        self.ceremony.save()
        self.client.get('/tickets/')
        self.assertFalse(Ticket.objects.exists())
        self.assertEqual(GuestReservation.objects.count(), 1)

    def test_registration_with_automatic_issuance_disabled(self):
        self.ceremony.auto_student_ticket = False
        self.ceremony.save()
        self.client.logout()
        Student.objects.create(tupc_id='TUPC-22-0043', name='Alex Ramos', course='BSIT', section='4A')
        response = self.client.post('/register/', {'username': 'TUPC-22-0043', 'first_name': 'Alex', 'last_name': 'Ramos', 'email': 'alex@example.com', 'contact_number': '09123456789'})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='TUPC-22-0043')
        self.assertTrue(user.student_profile.access_code_digest)
        self.assertFalse(user.tickets.exists())
        self.client.force_login(user)
        self.assertContains(self.client.get('/tickets/'), 'Request student ticket')
        self.assertFalse(user.tickets.exists())
