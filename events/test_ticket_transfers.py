from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Ceremony, Student, StudentProfile, Ticket, TicketTransfer


class TicketTransferTests(TestCase):
    def student(self, name, verified=True):
        user = User.objects.create_user(username=name)
        roster = Student.objects.create(tupc_id=name, name=name, course='BSIT', section='4A')
        StudentProfile.objects.create(user=user, student=roster, contact_number='09000000000', access_code_digest=name if verified else None)
        return user

    def setUp(self):
        self.sender = self.student('TUP-22-0001')
        self.recipient = self.student('TUP-22-0002')
        self.unverified = self.student('TUP-22-0003', False)
        self.ceremony = Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.ticket = Ticket.objects.create(owner=self.sender, ceremony=self.ceremony, ticket_type='GUEST')
        self.client.force_login(self.sender)

    def send(self, recipient):
        return self.client.post('/tickets/transfer/', {'ticket_id': self.ticket.pk, 'recipient_id': recipient.username})

    def test_popup_lists_only_other_verified_students(self):
        response = self.client.get('/tickets/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['transfer_recipients']), [self.recipient])
        self.assertContains(response, 'id="system-clock"')
        self.assertContains(response, 'Transfer mode')
        self.assertContains(response, 'id="transfer-recipient"')
        self.assertContains(response, 'data-ticket="' + str(self.ticket.pk) + '"')

    def test_unverified_self_and_inactive_recipients_rejected(self):
        for recipient in [self.sender, self.unverified]:
            self.send(recipient)
            self.assertFalse(TicketTransfer.objects.exists())
        self.recipient.is_active = False
        self.recipient.save()
        self.send(self.recipient)
        self.assertFalse(TicketTransfer.objects.exists())

    def test_transfer_requires_acceptance(self):
        self.send(self.recipient)
        transfer = TicketTransfer.objects.get()
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.owner, self.sender)
        self.client.force_login(self.recipient)
        response = self.client.post(f'/tickets/transfer/{transfer.pk}/accept/')
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.owner, self.recipient)

    def test_used_ticket_cannot_be_accepted(self):
        self.send(self.recipient)
        transfer = TicketTransfer.objects.get()
        self.ticket.checked_in_at = timezone.now()
        self.ticket.save()
        self.client.force_login(self.recipient)
        self.client.post(f'/tickets/transfer/{transfer.pk}/accept/')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.owner, self.sender)

    def test_student_pass_cannot_be_transferred(self):
        self.ticket.ticket_type = 'STUDENT'
        self.ticket.save()
        self.assertEqual(self.send(self.recipient).status_code, 404)
        self.assertFalse(TicketTransfer.objects.exists())

    def test_pending_transfer_not_offered_again(self):
        self.send(self.recipient)
        response = self.client.get('/tickets/')
        self.assertNotContains(response, 'data-ticket="' + str(self.ticket.pk) + '"')
        self.assertContains(response, 'Transfer awaiting acceptance')
