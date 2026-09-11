from django.db import migrations, models


def combine(apps, schema_editor):
    # Pagsamahin muna ang lumang course at section bago alisin ang old columns.
    Student = apps.get_model('events', 'Student')
    for student in Student.objects.all().iterator():
        student.program_section = '-'.join(filter(None, [student.course.strip(), student.section.strip()]))
        student.save(update_fields=['program_section'])
    # I-update rin ang saved history para pareho ang display ng past ceremonies.
    Ceremony = apps.get_model('events', 'Ceremony')
    for ceremony in Ceremony.objects.exclude(roster_snapshot=None).iterator():
        for row in ceremony.roster_snapshot.get('students', []):
            row['program_section'] = '-'.join(filter(None, [row.get('course', '').strip(), row.get('section', '').strip()]))
        ceremony.save(update_fields=['roster_snapshot'])


class Migration(migrations.Migration):
    dependencies = [('events', '0024_ticket_price_amount')]
    operations = [
        migrations.AddField('student', 'program_section', models.CharField('Program/Major/Year & Section', max_length=181, default=''), preserve_default=False),
        migrations.AddField('student', 'first_name', models.CharField(max_length=150, blank=True)),
        migrations.AddField('student', 'last_name', models.CharField(max_length=150, blank=True)),
        migrations.AddField('student', 'middle_initial', models.CharField(max_length=10, blank=True)),
        migrations.RunPython(combine, migrations.RunPython.noop),
        migrations.RemoveField('student', 'course'),
        migrations.RemoveField('student', 'section'),
    ]
