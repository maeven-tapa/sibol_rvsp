from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('events', '0006_student_and_guest_tickets'),
    ]

    operations = [
        migrations.CreateModel(
            name='Faculty',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=300)),
                ('department', models.CharField(max_length=180, verbose_name='Department / Office')),
                ('campus', models.CharField(choices=[('Cavite', 'Cavite'), ('Manila', 'Manila'), ('Taguig', 'Taguig'), ('Batangas', 'Batangas')], max_length=20)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='faculty_profile', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterField(
            model_name='ticket',
            name='ticket_type',
            field=models.CharField(choices=[('STUDENT', 'Student'), ('FACULTY', 'Faculty'), ('GUEST', 'Guest')], max_length=10),
        ),
    ]
