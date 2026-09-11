import csv
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import Ceremony, Student
from .student_import import HEADERS


# Check ang preview, validation, at actual import gamit ang sample CSV uploads.
class StudentImportTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('import-admin', is_staff=True))
        self.ceremony = Ceremony.objects.create(starts_at=timezone.now(), venue='Hall', is_active=True)
        self.row = ['TUP-22-0042', 'De la Cruz', 'Mary Jane', 'M.', 'BET-COET-4A']

    def upload(self, rows=None, action='preview', headers=None):
        content = io.StringIO(newline='')
        writer = csv.writer(content)
        writer.writerow(HEADERS if headers is None else headers)
        writer.writerows([self.row] if rows is None else rows)
        return self.client.post('/dashboard/students/import/', {
            'action': action,
            'file': SimpleUploadedFile('students.csv', content.getvalue().encode('utf-8-sig')),
        })

    def test_preview_then_add_and_registration_details(self):
        response = self.upload()
        self.assertEqual(response.json()['rows'], [self.row])
        self.assertFalse(Student.objects.exists())

        self.assertEqual(self.upload(action='add').json()['added'], 1)
        student = Student.objects.get()
        self.assertEqual(student.program_section, 'BET-COET-4A')
        self.assertEqual(student.name, 'Mary Jane M. De la Cruz')
        details = self.client.post('/register/check-id/', {'tupc_id': student.tupc_id}).json()
        self.assertEqual(details['first_name'], 'Mary Jane')
        self.assertEqual(details['last_name'], 'De la Cruz')
        self.assertEqual(details['program_section'], student.program_section)

    def test_duplicates_and_invalid_rows_do_not_partially_import(self):
        self.assertEqual(self.upload([self.row, self.row], action='add').status_code, 400)
        self.assertFalse(Student.objects.exists())
        invalid = ['invalid', 'Reyes', 'Alex', '', 'BET-COET-4A']
        self.assertEqual(self.upload([self.row, invalid], action='add').status_code, 400)
        self.assertFalse(Student.objects.exists())
        self.upload(action='add')
        self.assertEqual(self.upload(action='add').status_code, 400)
        self.assertEqual(Student.objects.count(), 1)

    def test_empty_and_wrong_headers(self):
        self.assertEqual(self.upload([]).status_code, 400)
        self.assertEqual(self.upload(headers=['ID', 'Name']).status_code, 400)

    def test_optional_mi_and_quoted_names(self):
        row = ['TUP-22-0043', 'Reyes, Jr.', 'Alex', '', 'BET-COET-4A']
        self.assertEqual(self.upload([row]).json()['rows'], [row])
        self.assertEqual(self.upload([row], action='add').status_code, 200)

    def test_template_and_dashboard(self):
        response = self.client.get('/dashboard/students/template/')
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[0], HEADERS)
        self.assertEqual(len(rows[1]), 5)
        self.assertContains(self.client.get('/dashboard/'), 'studentImportModal')

    def test_requires_staff_and_active_ceremony(self):
        self.ceremony.is_active = False
        self.ceremony.save()
        self.assertEqual(self.upload(action='add').status_code, 400)
        self.client.force_login(User.objects.create_user('ordinary-student'))
        self.assertEqual(self.upload(action='add').status_code, 302)
        self.assertEqual(self.client.get('/dashboard/students/template/').status_code, 302)
        self.assertFalse(Student.objects.exists())


# Siguraduhing napapanatili ang roster at history data kapag nag-migrate.
class StudentProgramMigrationTests(TransactionTestCase):
    def test_combines_existing_roster_and_history(self):
        executor = MigrationExecutor(connection)
        old_target = [('events', '0024_ticket_price_amount')]
        new_target = [('events', '0025_student_program_section')]
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            old_students = apps.get_model('events', 'Student')
            student = old_students.objects.create(tupc_id='TUP-22-1234', name='Alex Reyes', course='BET-COET', section='4A')
            ceremony = apps.get_model('events', 'Ceremony').objects.create(
                starts_at=timezone.now(), venue='Hall',
                roster_snapshot={'students': [{'course': 'BET-COET', 'section': '4A'}], 'faculty': []},
            )
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            self.assertEqual(Student.objects.get(pk=student.pk).program_section, 'BET-COET-4A')
            self.assertEqual(Ceremony.objects.get(pk=ceremony.pk).roster_snapshot['students'][0]['program_section'], 'BET-COET-4A')
        finally:
            MigrationExecutor(connection).migrate(new_target)
