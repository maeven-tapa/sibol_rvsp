from .models import Faculty, Ticket, GuestReservation


# Magkaiba ang allowed total depende kung faculty o student ang account.
def ticket_limit(user, ceremony):
    return ceremony.faculty_ticket_limit if Faculty.objects.filter(user=user).exists() else ceremony.student_ticket_limit


# Hindi kasama sa bilang ang admin passes at declined tickets.
def issued_count(user, ceremony):
    return Ticket.objects.filter(owner=user, ceremony=ceremony).exclude(ticket_type=Ticket.TicketType.ADMIN).exclude(reservation_status='declined').count()


def remaining_slots(user, ceremony):
    # Bawas din ang pending requests para hindi lumampas sa limit kapag na-approve.
    pending = GuestReservation.objects.filter(owner=user, ceremony=ceremony, status='pending').count()
    return max(0, ticket_limit(user, ceremony) - issued_count(user, ceremony) - pending)
