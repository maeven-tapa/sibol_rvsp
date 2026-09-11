import csv
import io

from django.contrib.auth.decorators import user_passes_test
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .forms import StudentForm
from .models import Ceremony

# Pareho ang column order ng template at upload para tama ang mapping ng student data.
HEADERS = ['TUP ID', 'Last Name', 'First Name', 'MI', 'Program/Major/Year & Section']


@user_passes_test(lambda user: user.is_staff)
@require_GET
def download_template(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="eligible-students-template.csv"'
    # May BOM para mabasa rin nang tama sa Excel ang UTF-8 names.
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(HEADERS)
    writer.writerow(['TUP-22-0042', 'Reyes', 'Alex', 'M', 'BET-COET-4A'])
    return response


def parse_students(upload):
    # Validate muna ang buong file; wala pang ise-save habang ginagawa ang preview.
    if not upload or not upload.name.lower().endswith('.csv'):
        raise ValueError('Select a CSV file.')
    if upload.size > 2 * 1024 * 1024:
        raise ValueError('The CSV must be 2 MB or smaller.')
    try:
        reader = csv.reader(io.StringIO(upload.read().decode('utf-8-sig'), newline=''), strict=True)
        header = next(reader, [])
        if [value.strip().casefold() for value in header] != [value.casefold() for value in HEADERS]:
            raise ValueError('Use the template column headings in their original order.')
        students, rows, seen, errors = [], [], set(), []
        for number, values in enumerate(reader, 2):
            if not any(value.strip() for value in values):
                continue
            if len(rows) >= 1000:
                raise ValueError('Import at most 1,000 students at a time.')
            if len(values) != 5:
                raise ValueError(f'Row {number}: expected five columns.')
            tup_id, last, first, mi, program = [value.strip() for value in values]
            tup_id = tup_id.upper()
            rows.append([tup_id, last, first, mi, program])
            if not first or not last or len(first) > 150 or len(last) > 150 or len(mi) > 10:
                errors.append(f'Row {number}: first and last names are required (150 characters maximum); MI allows 10 characters.')
            if tup_id in seen:
                errors.append(f'Row {number}: duplicate TUP ID {tup_id} in this file.')
            seen.add(tup_id)
            # Gamit ang parehong form rules ng Add student, kasama ang existing ID checks.
            form = StudentForm({'tupc_id': tup_id, 'name': ' '.join(filter(None, [first, mi, last])), 'program_section': program})
            if not form.is_valid():
                errors.extend(f'Row {number}: {field}: {message}' for field, messages in form.errors.items() for message in messages)
            else:
                student = form.save(commit=False)
                student.first_name, student.last_name, student.middle_initial = first, last, mi
                students.append(student)
        if not rows:
            raise ValueError('The CSV contains no students.')
        return students, rows, errors
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError('Unable to read this CSV. Save it as UTF-8 CSV and try again.') from exc


@user_passes_test(lambda user: user.is_staff)
@require_POST
def import_students(request):
    if not Ceremony.objects.filter(is_active=True).exists():
        return JsonResponse({'errors': ['Start a ceremony before importing students.']}, status=400)
    try:
        students, rows, errors = parse_students(request.FILES.get('file'))
        if errors:
            return JsonResponse({'rows': rows, 'errors': errors}, status=400)
        # Revalidated ang upload sa Add; isang transaction para walang partial import.
        if request.POST.get('action') == 'add':
            with transaction.atomic():
                if not Ceremony.objects.select_for_update().filter(is_active=True).exists():
                    raise ValueError('The active ceremony has ended. Reload the dashboard.')
                for student in students:
                    student.save()
            return JsonResponse({'added': len(students)})
        return JsonResponse({'rows': rows, 'errors': []})
    except ValueError as exc:
        return JsonResponse({'errors': [str(exc)]}, status=400)
    except IntegrityError:
        return JsonResponse({'errors': ['A TUP ID was added by another request. Preview the file again. No students were imported.']}, status=400)
