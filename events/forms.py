from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.db import transaction
from .models import StudentProfile, Student, Ceremony, Faculty, ProgramItem

class SignUpForm(forms.ModelForm):
    username = forms.RegexField(regex=r"^TUP[A-Z]?-\d{2}-\d{4}$", label="TUP ID", error_messages={"invalid": "Use the format TUP-22-0042."}, widget=forms.TextInput(attrs={"placeholder": "TUP-22-0042", "autocomplete": "username", "pattern": "TUP[A-Z]?-[0-9]{2}-[0-9]{4}"}))
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True)
    contact_number = forms.RegexField(regex=r"^\+?[0-9][0-9 ()-]{6,23}$", label="Contact number", widget=forms.TextInput(attrs={"type": "tel", "placeholder": "09XX XXX XXXX", "autocomplete": "tel"}), error_messages={"invalid": "Enter a valid contact number (digits, spaces, +, or hyphens)."})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields['first_name'].widget.attrs['readonly'] = True
        self.fields['last_name'].widget.attrs['readonly'] = True

    def clean_username(self):
        value = self.cleaned_data["username"].strip().upper()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("This student ID already has an account. Please sign in.")
        if not Student.objects.filter(tupc_id=value).exists():
            raise forms.ValidationError("This TUP ID is not on the student roster. Please contact the administrator.")
        return value

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        if commit:
            student = Student.objects.get(tupc_id=user.username)
            user.first_name, _, user.last_name = student.name.partition(' ')
            user.save(update_fields=['first_name', 'last_name'])
            StudentProfile.objects.create(user=user, student=student, contact_number=self.cleaned_data["contact_number"])
        return user
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "contact_number")


class StudentForm(forms.ModelForm):
    tupc_id = forms.RegexField(regex=r'^TUP[A-Z]?-\d{2}-\d{4}$', label='TUP ID', widget=forms.TextInput(attrs={'placeholder': 'TUP-22-0042'}))

    class Meta:
        model = Student
        fields = ('tupc_id', 'name', 'course', 'section')

    def clean_tupc_id(self):
        return self.cleaned_data['tupc_id'].upper()


class FacultyForm(forms.ModelForm):
    email = forms.EmailField(label="Email", max_length=254)
    employee_id = forms.CharField(max_length=60, label="Employee Faculty ID")

    def clean_employee_id(self):
        value = self.cleaned_data["employee_id"].strip().upper()
        if Faculty.objects.filter(employee_id__iexact=value).exists():
            raise forms.ValidationError("This Employee Faculty ID is already registered.")
        return value

    class Meta:
        model = Faculty
        fields = ('employee_id', 'name', 'email', 'department', 'campus')


class CeremonyForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['campus'].widget = forms.HiddenInput()
        self.fields['venue'].widget = forms.HiddenInput()
        if not self.is_bound:
            self.fields['campus'].initial = ''
            self.fields['venue'].initial = ''

    class Meta:
        model = Ceremony
        fields = ('title', 'theme', 'batch_name', 'commencement_number', 'campus', 'starts_at', 'venue')
        labels = {'starts_at': 'Ceremony date & time (Philippine time)'}
        widgets = {'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}


class ProgramItemForm(forms.ModelForm):
    class Meta:
        model = ProgramItem
        fields = ('item_type', 'title', 'description', 'speaker', 'hymn_language')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe this program item'}),
            'speaker': forms.TextInput(attrs={'placeholder': 'Name, office, group, or performer'}),
        }


class AccessCodeForm(forms.Form):
    access_code = forms.RegexField(regex=r'^TUP[MTCB]-[A-Z0-9]{4}$', label='Access code', widget=forms.TextInput(attrs={'placeholder': 'TUPM-A7B2', 'autocomplete': 'off', 'autocapitalize': 'characters', 'spellcheck': 'false', 'maxlength': 9}))

    def __init__(self, *args, **kwargs):
        if args and args[0] is not None:
            data = args[0].copy()
            data['access_code'] = data.get('access_code', '').strip().upper()
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)


class AdminLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError('This sign-in is for administrators only.', code='invalid_login')
