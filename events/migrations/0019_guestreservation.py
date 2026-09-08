from django.db import migrations, models
import django.db.models.deletion


def move_pending_guest_tickets_to_requests(apps, schema_editor):
    Ticket = apps.get_model('events', 'Ticket')
    GuestReservation = apps.get_model('events', 'GuestReservation')
    for ticket in Ticket.objects.filter(ticket_type='GUEST', reservation_status='pending').iterator():
        GuestReservation.objects.create(
            owner_id=ticket.owner_id,
            ceremony_id=ticket.ceremony_id,
            guest_relation=ticket.guest_relation,
            guest_name=ticket.guest_name,
            payment_receipt=ticket.payment_receipt.name,
            status='pending',
            created_at=ticket.purchased_at,
        )
        ticket.delete()


class Migration(migrations.Migration):

    dependencies = [('events', '0018_ceremony_program_saved_at_faculty_archived_ceremony_and_more')]

    operations = [
        migrations.CreateModel(
            name='GuestReservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('guest_relation', models.CharField(max_length=20)),
                ('guest_name', models.CharField(blank=True, max_length=150)),
                ('payment_receipt', models.FileField(upload_to='receipts/')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('declined', 'Declined')], default='pending', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ceremony', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='guest_reservations', to='events.ceremony')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='guest_reservations', to='auth.user')),
            ],
        ),
        migrations.RunPython(move_pending_guest_tickets_to_requests, migrations.RunPython.noop),
    ]
