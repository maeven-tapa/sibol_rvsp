from django.db import migrations, models


def rename_ticket_types(apps, schema_editor):
    Ticket = apps.get_model('events', 'Ticket')
    Ticket.objects.filter(ticket_type='REGULAR').update(ticket_type='STUDENT')
    Ticket.objects.filter(ticket_type='VIP').update(ticket_type='GUEST')


class Migration(migrations.Migration):
    dependencies = [('events', '0005_ceremony_campus_ceremony_completed_at')]

    operations = [
        migrations.RunPython(rename_ticket_types, migrations.RunPython.noop),
        migrations.AlterField(model_name='ticket', name='ticket_type', field=models.CharField(choices=[('STUDENT', 'Student'), ('GUEST', 'Guest')], max_length=10)),
    ]
