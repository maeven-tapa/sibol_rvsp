from io import BytesIO
from PIL import Image
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from .models import Ceremony, Ticket, GuestReservation


class StartTicketsTests(TestCase):
    def setUp(self):
        self.ceremony = Ceremony.objects.create(title='Ceremony', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.admin = User.objects.create_user('admin', is_staff=True)
        self.student = User.objects.create_user('student')
        self.client.force_login(self.admin)

    def qr(self):
        buffer = BytesIO()
        Image.new('RGB', (20, 20), 'white').save(buffer, format='PNG')
        return SimpleUploadedFile('qrph.png', buffer.getvalue(), content_type='image/png')

    def start(self, mode, **extra):
        return self.client.post('/dashboard/', {'action': 'start_tickets', 'ticket_workflow': mode, **extra})

    def reserve(self, **extra):
        self.client.force_login(self.student)
        return self.client.post('/tickets/reserve/', {'count': 1, 'relation': 'Friend', 'guest_name': 'Guest', **extra})

    def test_initial_audit_only_has_start_button_and_reservations_are_closed(self):
        response = self.client.get('/dashboard/')
        self.assertContains(response, 'ticket-start-card')
        self.assertNotContains(response, 'id="tickets-table"')
        self.reserve()
        self.assertFalse(GuestReservation.objects.exists())
        self.assertNotContains(self.client.get('/tickets/'), '+ Reserve ticket')

    def test_selling_requires_valid_qr_image_and_displays_upload_in_portal(self):
        response = self.start('selling')
        self.assertTrue(response.context['start_tickets_form'].errors)
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.ticket_workflow, '')
        response = self.start('selling', payment_qr=SimpleUploadedFile('fake.png', b'not an image', content_type='image/png'))
        self.assertTrue(response.context['start_tickets_form'].errors)
        self.assertEqual(self.start('selling', payment_qr=self.qr()).status_code, 302)
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.ticket_workflow, 'selling')
        self.assertContains(self.client.get('/dashboard/'), 'id="tickets-table"')
        self.reserve()
        self.assertFalse(GuestReservation.objects.exists())
        response = self.client.get('/tickets/')
        self.assertContains(response, self.ceremony.payment_qr.url)
        self.assertContains(response, 'Pay with QR Ph')
        self.assertNotContains(response, '/static/images/qrpay.png')
        self.reserve(receipt=SimpleUploadedFile('receipt.pdf', b'proof'))
        self.assertEqual(GuestReservation.objects.count(), 1)

    def test_request_only_has_no_qr_and_allows_no_receipt_or_optional_receipt(self):
        self.start('requests')
        self.reserve()
        self.assertFalse(GuestReservation.objects.get().payment_receipt)
        response = self.client.get('/tickets/')
        self.assertNotContains(response, 'Pay with QR Ph')
        self.assertNotContains(response, 'QR Ph payment code')
        self.assertNotContains(response, '150 each')
        self.assertContains(response, 'Upload receipt (optional)')
        self.reserve(receipt=SimpleUploadedFile('optional.pdf', b'proof'))
        self.assertEqual(GuestReservation.objects.exclude(payment_receipt='').count(), 1)
        reservation = GuestReservation.objects.first()
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action': 'approve_reservation', 'reservation_id': reservation.pk})
        self.assertEqual(Ticket.objects.get(ticket_type='GUEST').price, 0)

    def test_only_staff_can_start_and_started_workflow_cannot_be_replaced(self):
        self.client.force_login(self.student)
        self.start('requests')
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.ticket_workflow, '')
        self.client.force_login(self.admin)
        self.start('requests')
        self.start('selling', payment_qr=self.qr())
        self.ceremony.refresh_from_db()
        self.assertEqual(self.ceremony.ticket_workflow, 'requests')
        self.assertFalse(self.ceremony.payment_qr)

    def test_existing_ticket_prices_survive_workflow_setup(self):
        old = Ticket.objects.create(owner=self.student, ceremony=self.ceremony, ticket_type='GUEST')
        self.start('requests')
        old.refresh_from_db()
        self.assertEqual(old.price, 150)

    def test_history_keeps_ticket_audit_without_start_button(self):
        self.ceremony.is_active = False
        self.ceremony.save()
        response = self.client.get(f'/history/?ceremony={self.ceremony.pk}')
        self.assertContains(response, 'id="tickets-table"')
        self.assertNotContains(response, 'ticket-start-card')
