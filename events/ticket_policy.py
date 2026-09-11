from .models import Faculty, Ticket, GuestReservation


def ticket_limit(user, ceremony):
    return ceremony.faculty_ticket_limit if Faculty.objects.filter(user=user).exists() else ceremony.student_ticket_limit


def issued_count(user, ceremony):
    return Ticket.objects.filter(owner=user, ceremony=ceremony).exclude(ticket_type=Ticket.TicketType.ADMIN).exclude(reservation_status='declined').count()


def remaining_slots(user, ceremony):
    pending = GuestReservation.objects.filter(owner=user, ceremony=ceremony, status='pending').count()
    return max(0, ticket_limit(user, ceremony) - issued_count(user, ceremony) - pending)
