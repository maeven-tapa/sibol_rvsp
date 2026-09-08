from django.test import TestCase
from django.contrib.auth.models import User
from .forms import SignUpForm
from .models import Student, Ceremony, Ticket, Faculty
from django.utils import timezone


class RegistrationTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(tupc_id='TUPC-22-0042', name='Jamie Ramos', course='BSIT', section='4A')

    def details(self, **overrides):
        return dict(username='TUPC-22-0042', first_name='Jamie', last_name='Ramos', email='jamie@example.com', contact_number='09123456789', password1='Test-pass-4829!', password2='Test-pass-4829!', **overrides)

    def test_registration_persists_contact_and_issues_access_code(self):
        data = self.details()
        response = self.client.post('/register/', data)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username=data['username'])
        self.assertEqual(user.student_profile.contact_number, data['contact_number'])
        self.assertFalse(user.has_usable_password())
        self.assertRegex(self.client.session['registration_code'], r'^TUPC-[A-Z0-9]{4}$')
        self.assertTrue(user.student_profile.access_code_digest)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.student_profile.student, self.student)

    def test_registration_issues_included_student_ticket_when_ceremony_is_active(self):
        Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.client.post('/register/', self.details())
        self.assertTrue(Ticket.objects.filter(owner__username='TUPC-22-0042', ticket_type=Ticket.TicketType.STUDENT).exists())

    def test_unlisted_id_cannot_register_even_by_direct_post(self):
        data = self.details()
        data['username'] = 'TUPC-22-9999'
        response = self.client.post('/register/', data)
        self.assertContains(response, 'not on the student roster')
        self.assertFalse(User.objects.exists())

    def test_first_step_returns_roster_identity(self):
        response = self.client.post('/register/check-id/', {'tupc_id': self.student.tupc_id})
        self.assertEqual(response.json()['course'], 'BSIT')
        self.assertEqual(response.json()['first_name'], 'Jamie')

    def test_login_uses_access_code(self):
        self.client.post('/register/', self.details())
        code = self.client.session['registration_code']
        response = self.client.post('/login/', {'access_code': code.lower()})
        self.assertRedirects(response, '/tickets/')

    def test_invalid_and_duplicate_student_ids_rejected(self):
        data = self.details()
        data['username'] = 'invalid'
        self.assertIn('username', SignUpForm(data).errors)
        User.objects.create_user(username='TUPC-22-0042')
        self.assertIn('username', SignUpForm(self.details()).errors)

    def test_password_fields_removed_and_invalid_contact_rejected(self):
        data = self.details()
        data.update(password2='different-password', contact_number='abc')
        form = SignUpForm(data)
        self.assertNotIn('password2', form.fields)
        self.assertIn('contact_number', form.errors)
        self.assertEqual(User.objects.count(), 0)


class CeremonyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin', is_staff=True)
        self.attendee = User.objects.create_user('TUPC-22-0042')

    def test_no_ceremony_hides_cards_and_blocks_purchase(self):
        self.assertNotContains(self.client.get('/'), 'class="info-card')
        self.client.force_login(self.attendee)
        self.client.post('/buy/GUEST/')
        self.assertFalse(Ticket.objects.exists())
        self.assertContains(self.client.get('/tickets/'), 'No ceremony announced yet.')

    def test_staff_can_add_roster_student(self):
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action':'ceremony','commencement_number':'2','title':'Sibol 2027','campus':'Manila','starts_at':'2027-06-01T16:00','venue':'New Auditorium'})
        response = self.client.post('/dashboard/', {'action':'student','tupc_id':'TUPC-22-0001','name':'Alex Reyes','course':'BSIT','section':'4B'})
        self.assertRedirects(response, '/dashboard/')
        self.assertTrue(Student.objects.filter(tupc_id='TUPC-22-0001').exists())

    def test_only_staff_can_manage_ceremonies(self):
        self.client.force_login(self.attendee)
        response = self.client.post('/dashboard/', {'action':'ceremony','commencement_number':'2','title':'Unauthorized','campus':'Manila','starts_at':'2027-06-01T16:00','venue':'Hall'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Ceremony.objects.exists())

    def test_ceremony_drives_home_tickets_and_gate(self):
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action':'ceremony','commencement_number':'2','title':'Sibol 2027','campus':'Manila','starts_at':'2027-06-01T16:00','venue':'New Auditorium'})
        ceremony = Ceremony.objects.get(is_active=True)
        self.client.logout()
        response = self.client.get('/')
        self.assertContains(response, 'The 2nd Commencement Exercise')
        self.assertContains(response, 'New Auditorium')
        self.assertContains(response, 'class="info-card')
        self.client.force_login(self.attendee)
        self.assertEqual(self.client.get('/buy/GUEST/').status_code, 405)
        self.client.post('/buy/GUEST/')
        ticket = Ticket.objects.get(ticket_type=Ticket.TicketType.GUEST)
        self.assertEqual(ticket.ceremony, ceremony)
        self.assertContains(self.client.get('/tickets/'), 'New Auditorium')
        self.client.force_login(self.admin)
        self.client.post('/dashboard/', {'action':'ceremony','commencement_number':'2','title':'Sibol 2028','campus':'Taguig','starts_at':'2028-06-01T16:00','venue':'Next Hall'})
        self.assertEqual(Ceremony.objects.filter(is_active=True).count(), 1)
        self.client.post('/gate/', {'mode':'verify','duration':'1'})
        response = self.client.post('/gate/scan/', {'code':ticket.code})
        self.assertIn('not for the active ceremony', response.json()['error'])
        ticket.refresh_from_db()
        self.assertFalse(ticket.is_used)
        self.assertEqual(ticket.ceremony.venue, 'New Auditorium')

    def test_student_can_reserve_at_most_two_guest_tickets(self):
        Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.client.force_login(self.attendee)
        for _ in range(3):
            self.client.post('/buy/GUEST/')
        self.assertEqual(Ticket.objects.filter(owner=self.attendee, ticket_type=Ticket.TicketType.GUEST).count(), 2)

    def test_staff_adds_faculty_account_with_gate_one_pass(self):
        ceremony = Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.client.force_login(self.admin)
        response = self.client.post('/dashboard/', {'action': 'faculty', 'email': 'faculty@example.com', 'employee_id': 'EMP-001', 'name': 'Dr. Ana Reyes', 'department': 'Registrar', 'campus': 'Manila'})
        self.assertRedirects(response, '/dashboard/')
        faculty = Faculty.objects.get(name='Dr. Ana Reyes')
        ticket = Ticket.objects.get(owner=faculty.user, ceremony=ceremony)
        self.assertEqual(ticket.ticket_type, Ticket.TicketType.FACULTY)
        self.assertEqual(ticket.gate, 'Student & Faculty Gate')

    def test_active_dashboard_hides_start_form_and_has_completion_confirmation(self):
        Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.client.force_login(self.admin)
        response = self.client.get('/dashboard/')
        self.assertNotContains(response, 'id="ceremony-form"')
        self.assertContains(response, 'Current Ceremony Overview')
        self.assertContains(response, 'completeCeremonyModal')


class AdminDashboardUpdatesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('dashboard-admin', is_staff=True)
        self.ceremony = Ceremony.objects.create(title='Sibol', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.client.force_login(self.admin)

    def test_admin_ticket_is_marked_displayed_and_excluded_from_totals(self):
        for _ in range(2):
            self.assertRedirects(self.client.post('/dashboard/', {'action': 'admin_ticket'}), '/dashboard/')
        ticket = Ticket.objects.get(owner=self.admin)
        self.assertEqual(ticket.ticket_type, Ticket.TicketType.ADMIN)
        ticket.checked_in_at = timezone.now()
        ticket.save()
        response = self.client.get('/dashboard/')
        self.assertEqual(response.context['total'], 0)
        self.assertEqual(response.context['used'], 0)
        self.assertEqual(response.context['revenue'], 0)
        self.assertContains(response, 'Admin account ticket')
        self.assertContains(response, ticket.code)
        self.assertContains(response, 'data:image/svg+xml;base64,')
        self.assertNotContains(response, '/admin/events/ticket/')

    def test_admin_ticket_requires_staff_and_active_ceremony(self):
        self.ceremony.is_active = False
        self.ceremony.save()
        self.client.post('/dashboard/', {'action': 'admin_ticket'})
        self.assertFalse(Ticket.objects.exists())
        self.client.force_login(User.objects.create_user('attendee'))
        self.client.post('/dashboard/', {'action': 'admin_ticket'})
        self.assertFalse(Ticket.objects.exists())

    def test_employee_id_required_and_duplicate_rejected(self):
        data = {'action': 'faculty', 'email': 'faculty@example.com', 'name': 'Ana', 'department': 'Registrar', 'campus': 'Manila'}
        response = self.client.post('/dashboard/', data)
        self.assertEqual(response.context['open_modal'], 'facultyModal')
        self.assertFalse(Faculty.objects.exists())
        data['employee_id'] = 'emp-001'
        self.client.post('/dashboard/', data)
        self.assertEqual(Faculty.objects.get().employee_id, 'EMP-001')
        data['employee_id'] = 'EMP-001'
        response = self.client.post('/dashboard/', data)
        self.assertEqual(response.context['open_modal'], 'facultyModal')
        self.assertEqual(Faculty.objects.count(), 1)

    def test_general_tup_id_registration_and_login(self):
        self.client.post('/dashboard/', {'action': 'student', 'tupc_id': 'TUP-22-0001', 'name': 'Alex Reyes', 'course': 'BSIT', 'section': '4B'})
        self.client.logout()
        self.assertRedirects(self.client.post('/register/', {'username': 'TUP-22-0001', 'first_name': 'Alex', 'last_name': 'Reyes', 'email': 'alex@example.com', 'contact_number': '09123456789', 'password1': 'Test-pass-4829!', 'password2': 'Test-pass-4829!'}), '/register/details/')
        code = self.client.session['registration_code']
        self.assertRedirects(self.client.post('/login/', {'access_code': code}), '/tickets/')


class CeremonyHistoryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('history-admin', is_staff=True)
        self.client.force_login(self.admin)
        self.ceremony = Ceremony.objects.create(title='Historic graduation', starts_at=timezone.now(), venue='Old Hall', is_active=True)

    def test_completion_preserves_roster_and_read_only_dashboard(self):
        student = Student.objects.create(tupc_id='TUP-22-1000', name='Original Student', course='BSIT', section='4A')
        self.client.post('/dashboard/', {'action': 'faculty', 'employee_id': 'EMP-HISTORY', 'name': 'Original Faculty', 'email': 'faculty@example.com', 'department': 'Registrar', 'campus': 'Manila'})
        ticket = Ticket.objects.get(ticket_type='FACULTY')
        response = self.client.post('/dashboard/', {'action': 'close_ceremony'})
        history_url = f'/history/?ceremony={self.ceremony.pk}'
        self.assertRedirects(response, history_url)
        self.ceremony.refresh_from_db()
        self.assertIsNotNone(self.ceremony.completed_at)
        student.name = 'Changed Student'
        student.save()
        faculty = Faculty.objects.get()
        self.assertEqual(faculty.user.email, 'faculty@example.com')
        faculty.name = 'Changed Faculty'
        faculty.save()
        newer = Ceremony.objects.create(title='Next graduation', starts_at=timezone.now(), venue='New Hall', is_active=True)
        Ticket.objects.create(owner=self.admin, ceremony=newer, ticket_type='GUEST')
        response = self.client.get(history_url)
        for text in ['Original Student', 'Original Faculty', 'faculty@example.com', 'Faculty Attendees', 'Ceremony history', ticket.code]:
            self.assertContains(response, text)
        for text in ['Changed Student', 'Changed Faculty', 'Generate admin ticket', 'Mark as complete', 'id="facultyModal"', 'id="studentModal"', 'id="campusModal"', 'id="ceremony-form"', 'Manage tickets in Django admin', 'FACULTY ACCOUNTS']:
            self.assertNotContains(response, text)
        self.assertEqual(response.context['total'], 1)
        self.assertEqual(response.context['revenue'], 0)
        self.assertEqual(self.client.post(history_url, {'action': 'close_ceremony'}).status_code, 405)
        newer.refresh_from_db()
        self.assertTrue(newer.is_active)
        current = self.client.get('/dashboard/')
        self.assertEqual(current.context['total'], 1)
        self.assertEqual(current.context['revenue'], 150)
        self.assertNotContains(current, 'Original Faculty')

    def test_invalid_or_active_history_selection_rejected(self):
        for value in ['invalid', '999999', str(self.ceremony.pk)]:
            self.assertEqual(self.client.get('/history/', {'ceremony': value}).status_code, 404)

    def test_history_landing_and_dashboard_are_separate(self):
        response = self.client.get('/history/')
        self.assertContains(response, 'No past ceremonies yet.')
        self.assertNotContains(response, 'id="ceremony-form"')
        self.assertNotContains(response, 'Expected participants')
        self.assertEqual(self.client.post('/history/', {'action': 'close_ceremony'}).status_code, 405)
        self.ceremony.refresh_from_db()
        self.assertTrue(self.ceremony.is_active)
        response = self.client.get('/dashboard/')
        self.assertContains(response, 'href="/history/"')
        self.assertNotContains(response, 'id="ceremony-history"')
        self.client.post('/dashboard/', {'action': 'close_ceremony'})
        response = self.client.get('/history/')
        self.assertContains(response, 'Choose a ceremony above')
        self.assertContains(response, 'Historic graduation')
        self.assertNotContains(response, 'id="ceremony-form"')
        self.assertRedirects(self.client.get(f'/dashboard/?ceremony={self.ceremony.pk}'), f'/history/?ceremony={self.ceremony.pk}')

    def test_history_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get('/history/').status_code, 302)
        self.client.force_login(User.objects.create_user('history-student'))
        self.assertEqual(self.client.get('/history/').status_code, 302)

    def test_faculty_email_validation(self):
        data = {'action': 'faculty', 'employee_id': 'EMP-EMAIL', 'name': 'Faculty', 'department': 'Registrar', 'campus': 'Manila'}
        for email in ['', 'invalid']:
            response = self.client.post('/dashboard/', {**data, 'email': email})
            self.assertIn('email', response.context['faculty_form'].errors)
            self.assertEqual(response.context['open_modal'], 'facultyModal')
        self.assertFalse(Faculty.objects.exists())

    def test_legacy_completed_ceremony_is_available(self):
        self.ceremony.is_active = False
        self.ceremony.save()
        response = self.client.get('/history/', {'ceremony': self.ceremony.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Historic graduation')
        self.assertContains(response, 'No students recorded for this ceremony.')


class DashboardTableTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('table-admin', is_staff=True)
        self.client.force_login(self.admin)
        self.ceremony = Ceremony.objects.create(title='Tables', starts_at=timezone.now(), venue='Hall', is_active=True)
        for number in range(31):
            Student.objects.create(tupc_id=f'TUP-22-{number:04}', name=f'Student {number:02}', course='BSIT', section='4A')
            user = User.objects.create_user(f'faculty-{number}', email=f'faculty{number}@example.com')
            Faculty.objects.create(user=user, employee_id=f'EMP-{number:02}', name=f'Faculty {number:02}', department='Registrar', campus='Manila')
            Ticket.objects.create(owner=user, ceremony=self.ceremony, ticket_type='FACULTY')

    def test_independent_pagination_and_card_order(self):
        response = self.client.get('/dashboard/')
        for key in ['tickets', 'students', 'faculty_accounts']:
            self.assertEqual(len(response.context[key]), 20)
            self.assertEqual(response.context[key].paginator.count, 31)
        html = response.content.decode()
        self.assertLess(html.index('id="tickets-table"'), html.index('id="students-table"'))
        self.assertContains(response, 'badge rounded-pill text-bg-secondary')
        response = self.client.get('/dashboard/', {'students_page': 2})
        self.assertEqual(len(response.context['students']), 11)
        self.assertEqual(response.context['tickets'].number, 1)
        self.assertContains(response, 'Student 30')
        self.assertEqual(response.context['total'], 31)

    def test_search_all_records_without_changing_totals(self):
        response = self.client.get('/dashboard/', {'students_q': 'Student 30', 'faculty_q': 'faculty30@example.com', 'tickets_q': 'faculty-30'})
        for key in ['tickets', 'students', 'faculty_accounts']:
            self.assertEqual(len(response.context[key]), 1)
        self.assertEqual(response.context['total'], 31)
        self.assertContains(response, 'Student 30')
        self.assertContains(response, 'Faculty 30')
        response = self.client.get('/dashboard/', {'students_q': 'does-not-exist'})
        self.assertContains(response, 'No students match your search.')

    def test_history_search_and_page_links_preserve_selection(self):
        self.client.post('/dashboard/', {'action': 'close_ceremony'})
        response = self.client.get('/history/', {'ceremony': self.ceremony.pk, 'students_q': 'Student', 'faculty_q': 'faculty30@example.com', 'students_page': 2})
        self.assertEqual(len(response.context['students']), 11)
        self.assertEqual(len(response.context['faculty_accounts']), 1)
        self.assertIn(f'ceremony={self.ceremony.pk}', response.context['student_table']['previous'])
        self.assertIn('faculty_q=faculty30%40example.com', response.context['student_table']['previous'])
        self.assertNotContains(response, '+ Add student')

    def test_page_navigation_for_twenty_one_records(self):
        Student.objects.filter(tupc_id__gte='TUP-22-0021').delete()
        response = self.client.get('/dashboard/', {'students_page': 'invalid'})
        self.assertEqual(len(response.context['students']), 20)
        self.assertTrue(response.context['students'].has_next())
        response = self.client.get('/dashboard/', {'students_page': 999})
        self.assertEqual(len(response.context['students']), 1)


class AccessCodeTests(TestCase):
    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.student = Student.objects.create(tupc_id='TUPT-22-1111', name='Code Student', course='BSIT', section='4A')

    def register(self):
        response = self.client.post('/register/', {'username': self.student.tupc_id, 'first_name': 'Code', 'last_name': 'Student', 'email': 'code@example.com', 'contact_number': '09123456789'})
        self.assertRedirects(response, '/register/details/')
        return self.client.session['registration_code']

    def test_code_details_and_single_input_login(self):
        code = self.register()
        self.assertRegex(code, r'^TUPT-[A-Z0-9]{4}$')
        self.assertTrue(any(c.isdigit() for c in code[-4:]))
        self.assertTrue(any(c.isalpha() for c in code[-4:]))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(self.client.get('/register/details/'), code)
        response = self.client.get('/login/')
        self.assertEqual(list(response.context['form'].fields), ['access_code'])
        self.assertNotContains(response, 'type="password"')
        self.assertRedirects(self.client.post('/login/', {'access_code': code}), '/tickets/')
        self.assertNotIn('registration_code', self.client.session)

    def test_admin_password_login_is_staff_only(self):
        user = User.objects.create_user('ordinary', password='test-password')
        response = self.client.post('/admin-login/', {'username': user.username, 'password': 'test-password'})
        self.assertContains(response, 'administrators only')
        user.is_staff = True
        user.save()
        self.assertRedirects(self.client.post('/admin-login/', {'username': user.username, 'password': 'test-password'}), '/dashboard/')

    def test_code_reissue_invalidates_old_and_supports_existing_students(self):
        from .access_codes import code_digest
        old = self.register()
        profile = User.objects.get(username=self.student.tupc_id).student_profile
        self.assertEqual(profile.access_code_digest, code_digest(old))
        admin = User.objects.create_user('code-admin', is_staff=True)
        self.client.force_login(admin)
        response = self.client.post('/dashboard/', {'action': 'student_access_code', 'student_id': self.student.pk}, follow=True)
        new = response.context['issued_student_code']['code']
        self.assertNotEqual(old, new)
        self.client.logout()
        self.assertContains(self.client.post('/login/', {'access_code': old}), 'Invalid access code')
        self.assertRedirects(self.client.post('/login/', {'access_code': new}), '/tickets/')

    def test_invalid_attempts_are_limited_and_inactive_account_rejected(self):
        code = self.register()
        user = User.objects.get(username=self.student.tupc_id)
        user.is_active = False
        user.save()
        self.assertContains(self.client.post('/login/', {'access_code': code}), 'Invalid access code')
        for _ in range(9):
            self.client.post('/login/', {'access_code': 'TUPT-Z9Z9'})
        self.assertContains(self.client.post('/login/', {'access_code': code}), 'Too many attempts')


class StudentActionTests(TestCase):
    def setUp(self):
        from .models import StudentProfile
        self.admin = User.objects.create_user('student-manager', is_staff=True)
        self.client.force_login(self.admin)
        self.ceremony = Ceremony.objects.create(title='Current', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.student = Student.objects.create(tupc_id='TUP-22-9000', name='Original Name', course='BSIT', section='4A')
        self.user = User.objects.create_user(self.student.tupc_id)
        self.profile = StudentProfile.objects.create(student=self.student, user=self.user, contact_number='09123456789')
        self.ticket = Ticket.objects.create(owner=self.user, ceremony=self.ceremony, ticket_type='STUDENT')

    def test_edit_updates_roster_and_account(self):
        response = self.client.post('/dashboard/', {'action': 'student_edit', 'student_id': self.student.pk, 'edit-tupc_id': 'TUP-22-9001', 'edit-name': 'Updated Name', 'edit-course': 'BSEE', 'edit-section': '4B'})
        self.assertRedirects(response, '/dashboard/')
        self.student.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.student.course, 'BSEE')
        self.assertEqual(self.student.section, '4B')
        self.assertEqual(self.user.username, 'TUP-22-9001')
        self.assertEqual(self.user.get_full_name(), 'Updated Name')
        self.assertEqual(Ticket.objects.get(pk=self.ticket.pk).owner_id, self.user.pk)

    def test_invalid_edit_reopens_panel_without_saving(self):
        response = self.client.post('/dashboard/', {'action': 'student_edit', 'student_id': self.student.pk, 'edit-tupc_id': 'invalid', 'edit-name': 'Changed', 'edit-course': 'BSIT', 'edit-section': '4A'})
        self.assertEqual(response.context['open_modal'], 'studentEditModal')
        self.assertTrue(response.context['student_edit_form'].errors)
        self.student.refresh_from_db()
        self.assertEqual(self.student.name, 'Original Name')

    def test_disable_enable_and_registration_check(self):
        self.client.post('/dashboard/', {'action': 'student_disable', 'student_id': self.student.pk})
        self.student.refresh_from_db()
        self.user.refresh_from_db()
        self.assertFalse(self.student.is_active)
        self.assertFalse(self.user.is_active)
        self.assertContains(self.client.get('/dashboard/'), 'Enable student')
        self.client.post('/dashboard/', {'action': 'student_enable', 'student_id': self.student.pk})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        unregistered = Student.objects.create(tupc_id='TUP-22-9002', name='New Student', course='BSIT', section='4A')
        self.client.post('/dashboard/', {'action': 'student_disable', 'student_id': unregistered.pk})
        self.assertEqual(self.client.post('/register/check-id/', {'tupc_id': unregistered.tupc_id}).status_code, 400)
        form = SignUpForm()
        form.cleaned_data = {'username': unregistered.tupc_id}
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            form.clean_username()

    def test_delete_retains_ticket_and_account_record(self):
        self.assertRedirects(self.client.post('/dashboard/', {'action': 'student_delete', 'student_id': self.student.pk}), '/dashboard/')
        self.assertFalse(Student.objects.filter(pk=self.student.pk).exists())
        self.profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertIsNone(self.profile.student_id)
        self.assertFalse(self.user.is_active)
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())

    def test_actions_require_staff_and_current_dashboard(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/dashboard/', {'action': 'student_delete', 'student_id': self.student.pk}).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post('/history/', {'action': 'student_delete', 'student_id': self.student.pk}).status_code, 405)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())


class ProgramEditorTests(TestCase):
    def setUp(self):
        from .models import ProgramItem
        self.admin = User.objects.create_user('program-editor', is_staff=True)
        self.client.force_login(self.admin)
        self.ceremony = Ceremony.objects.create(title='Program', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.first = ProgramItem.objects.create(ceremony=self.ceremony, item_type='speaker', title='First', speaker='N/A', position=0)
        self.second = ProgramItem.objects.create(ceremony=self.ceremony, item_type='song', title='Second', position=1)

    def save_items(self, items):
        import json
        return self.client.post('/dashboard/', {'action': 'program_flow_save', 'items': json.dumps(items)})

    def test_batch_add_edit_reorder_and_remove(self):
        response = self.save_items([
            {'id': self.second.pk, 'item_type': 'song', 'title': 'Second updated', 'speaker': ' n/a ', 'hymn_language': 'english'},
            {'item_type': 'speaker', 'title': 'New speaker', 'speaker': 'Dean'},
        ])
        self.assertEqual(response.status_code, 200)
        rows = list(self.ceremony.program_items.all())
        self.assertEqual([row.title for row in rows], ['Second updated', 'New speaker'])
        self.assertEqual([row.position for row in rows], [0, 1])
        self.assertEqual(rows[0].speaker, '')
        self.assertFalse(self.ceremony.program_items.filter(pk=self.first.pk).exists())
        response = self.client.get('/program-flow/')
        self.assertContains(response, 'Dean')
        self.assertLess(response.content.index(b'Second updated'), response.content.index(b'New speaker'))

    def test_invalid_batch_leaves_existing_program_unchanged(self):
        response = self.save_items([{'id': self.first.pk, 'item_type': 'speaker', 'title': 'Changed'}, {'item_type': 'invalid', 'title': ''}])
        self.assertEqual(response.status_code, 400)
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, 'First')
        self.assertEqual(self.ceremony.program_items.count(), 2)
        self.assertEqual(self.save_items([{'id': 99999, 'item_type': 'song', 'title': 'Invalid'}]).status_code, 400)
        self.assertEqual(self.save_items({'title': 'bad'}).status_code, 400)

    def test_speaker_placeholders_hidden_and_normalized(self):
        from .forms import ProgramItemForm
        for speaker in ['NA', 'na', 'N/A', ' n/a ', '']:
            form = ProgramItemForm({'item_type': 'speaker', 'title': 'Welcome', 'speaker': speaker})
            self.assertTrue(form.is_valid())
            self.assertEqual(form.cleaned_data['speaker'], '')
        self.assertNotContains(self.client.get('/program-flow/'), 'SPEAKER:')
        self.assertContains(self.client.get('/dashboard/'), 'program-draft-list')

    def test_history_and_nonstaff_cannot_save(self):
        self.assertEqual(self.client.post('/history/', {'action': 'program_flow_save', 'items': '[]'}).status_code, 405)
        self.client.force_login(User.objects.create_user('program-student'))
        self.assertEqual(self.save_items([]).status_code, 302)
        self.assertEqual(self.ceremony.program_items.count(), 2)


class CeremonyArchiveLifecycleTests(TestCase):
    def setUp(self):
        from .models import StudentProfile
        self.admin = User.objects.create_user('archive-admin', is_staff=True)
        self.client.force_login(self.admin)
        self.ceremony = Ceremony.objects.create(title='First ceremony', starts_at=timezone.now(), venue='Hall', is_active=True)
        self.student = Student.objects.create(tupc_id='TUP-22-7777', name='Archived Student', course='BSIT', section='4A')
        self.user = User.objects.create_user(self.student.tupc_id)
        StudentProfile.objects.create(user=self.user, student=self.student, contact_number='09123456789')
        self.ticket = Ticket.objects.create(owner=self.user, ceremony=self.ceremony, ticket_type='STUDENT')
        self.client.post('/dashboard/', {'action':'faculty', 'employee_id':'ARCH-001', 'name':'Archived Faculty', 'email':'archive@example.com', 'department':'Registrar', 'campus':'Manila'})
        self.faculty = Faculty.objects.get(employee_id='ARCH-001')

    def test_completion_archives_and_next_ceremony_starts_empty(self):
        from .views import ensure_student_ticket
        self.client.post('/dashboard/', {'action':'close_ceremony'})
        self.student.refresh_from_db()
        self.faculty.refresh_from_db()
        self.user.refresh_from_db()
        self.faculty.user.refresh_from_db()
        self.assertEqual(self.student.archived_ceremony_id, self.ceremony.pk)
        self.assertEqual(self.faculty.archived_ceremony_id, self.ceremony.pk)
        self.assertFalse(self.user.is_active)
        self.assertFalse(self.faculty.user.is_active)
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())
        history = self.client.get('/history/', {'ceremony': self.ceremony.pk})
        for text in ['Archived Student', 'Archived Faculty', self.ticket.code]:
            self.assertContains(history, text)
        self.client.post('/dashboard/', {'action':'ceremony','commencement_number':'2','title':'Second ceremony','campus':'Manila','starts_at':'2027-06-01T16:00','venue':'New Hall'})
        new = Ceremony.objects.get(is_active=True)
        dashboard = self.client.get('/dashboard/')
        self.assertEqual(dashboard.context['total'], 0)
        self.assertEqual(dashboard.context['students'].paginator.count, 0)
        self.assertEqual(dashboard.context['faculty_accounts'].paginator.count, 0)
        ensure_student_ticket(self.user, new)
        self.assertFalse(new.tickets.exists())
        self.assertEqual(self.client.post('/dashboard/', {'action':'student_enable', 'student_id':self.student.pk}).status_code, 404)
        self.client.post('/dashboard/', {'action':'student','tupc_id':'TUP-23-8888','name':'New Student','course':'BSIT','section':'4B'})
        dashboard = self.client.get('/dashboard/')
        self.assertEqual(dashboard.context['students'].paginator.count, 1)
        self.assertNotContains(dashboard, 'Archived Student')
        self.client.post('/dashboard/', {'action':'close_ceremony'})
        history = self.client.get('/history/', {'ceremony':new.pk})
        self.assertContains(history, 'New Student')
        self.assertNotContains(history, 'Archived Student')
        self.assertContains(self.client.get('/history/', {'ceremony':self.ceremony.pk}), 'Archived Student')

    def test_archived_unregistered_student_cannot_register(self):
        from .forms import SignUpForm
        from django.core.exceptions import ValidationError
        unregistered = Student.objects.create(tupc_id='TUP-22-7778', name='Unregistered', course='BSIT', section='4A')
        self.client.post('/dashboard/', {'action':'close_ceremony'})
        self.assertEqual(self.client.post('/register/check-id/', {'tupc_id':unregistered.tupc_id}).status_code, 400)
        form = SignUpForm()
        form.cleaned_data = {'username':unregistered.tupc_id}
        with self.assertRaises(ValidationError):
            form.clean_username()

    def test_program_button_changes_after_save_without_dashboard_card(self):
        import json
        response = self.client.get('/dashboard/')
        self.assertContains(response, '+ Add program flow')
        self.assertNotContains(response, 'class="program-summary"')
        payload = [{'item_type':'speaker','title':'Opening address','speaker':'Dean'}]
        self.assertEqual(self.client.post('/dashboard/', {'action':'program_flow_save','items':json.dumps(payload)}).status_code, 200)
        response = self.client.get('/dashboard/')
        self.assertContains(response, 'Edit program flow')
        self.assertNotContains(response, '+ Add program flow')
        self.assertNotContains(response, 'class="program-summary"')
        self.client.post('/dashboard/', {'action':'close_ceremony'})
        history = self.client.get('/history/', {'ceremony':self.ceremony.pk})
        self.assertContains(history, 'Opening address')
        self.assertContains(history, 'class="program-summary"')


class CeremonyTitleTests(TestCase):
    def test_number_generates_title_with_correct_ordinal(self):
        from .forms import CeremonyForm
        for number, ordinal in [(1,'1st'),(2,'2nd'),(3,'3rd'),(11,'11th'),(12,'12th'),(13,'13th'),(21,'21st'),(112,'112th')]:
            form = CeremonyForm({'commencement_number':number, 'title':'Ignored manual title', 'campus':'Manila', 'starts_at':'2027-06-01T16:00', 'venue':'Hall'})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertNotIn('title', form.fields)
            self.assertEqual(form.save(commit=False).title, f'The {ordinal} Commencement Exercise')

    def test_number_is_required_and_positive(self):
        from .forms import CeremonyForm
        for number in ['', '0', '-1']:
            form = CeremonyForm({'commencement_number':number, 'campus':'Manila', 'starts_at':'2027-06-01T16:00', 'venue':'Hall'})
            self.assertFalse(form.is_valid())
            self.assertIn('commencement_number', form.errors)


class StudentVerificationLabelTests(TestCase):
    def test_label_changes_only_after_portal_registration(self):
        from django.test import Client
        admin = User.objects.create_user('verification-admin', is_staff=True)
        Ceremony.objects.create(title='Ceremony', starts_at=timezone.now(), venue='Hall', is_active=True)
        Student.objects.create(tupc_id='TUP-22-6543', name='Portal Student', course='BSIT', section='4A')
        self.client.force_login(admin)
        self.assertContains(self.client.get('/dashboard/'), '>Not Verified</span>')
        portal = Client()
        response = portal.post('/register/', {'username':'TUP-22-6543', 'first_name':'Portal', 'last_name':'Student', 'email':'portal@example.com', 'contact_number':'09123456789'})
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get('/dashboard/')
        self.assertContains(dashboard, '>Verified</span>')
        self.assertNotContains(dashboard, '>Account created</span>')
