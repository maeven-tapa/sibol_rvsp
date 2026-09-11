import secrets
import string
from django.db import IntegrityError, transaction
from django.utils.crypto import salted_hmac
from .models import StudentProfile, Ceremony


# I-normalize muna ang code bago gumawa ng HMAC digest na pang-login lookup.
def code_digest(code):
    return salted_hmac('student-access-code', code.strip().upper(), algorithm='sha256').hexdigest()


def issue_access_code(profile):
    prefix = profile.student.tupc_id.split('-')[0] if profile.student else ''
    if prefix not in ('TUPM', 'TUPT', 'TUPC', 'TUPB'):
        campus = Ceremony.objects.filter(is_active=True).values_list('campus', flat=True).first()
        prefix = {'Manila': 'TUPM', 'Taguig': 'TUPT', 'Cavite': 'TUPC', 'Batangas': 'TUPB'}.get(campus, 'TUPM')
    # Gumawa ng bagong random code; uulit kapag may duplicate o invalid na suffix.
    for _ in range(100):
        suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        if not (any(c.isalpha() for c in suffix) and any(c.isdigit() for c in suffix)):
            continue
        code = f'{prefix}-{suffix}'
        if code_digest(code) == profile.access_code_digest:
            continue
        try:
            with transaction.atomic():
                profile.access_code_digest = code_digest(code)
                profile.current_access_code = code
                profile.save(update_fields=['access_code_digest', 'current_access_code'])
            return code
        except IntegrityError:
            continue
    raise RuntimeError('Unable to allocate an access code. Please try again.')
