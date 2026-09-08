from django.test import TestCase
from django.utils import timezone
from .models import Ceremony, ProgramItem


class ProgramFlowTests(TestCase):
    def setUp(self):
        self.ceremony = Ceremony.objects.create(title='Commencement', starts_at=timezone.now(), venue='PICC', theme='New beginnings', is_active=True)

    def test_only_configured_language_is_rendered(self):
        item = ProgramItem.objects.create(ceremony=self.ceremony, item_type='song', title='University hymn', hymn_language='tagalog')
        for language, other, lang in [('tagalog', 'english', 'tl'), ('english', 'tagalog', 'en')]:
            with self.subTest(language=language):
                item.hymn_language = language
                item.save()
                response = self.client.get('/program-flow/')
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'id="hymn-{language}"', count=1)
                self.assertNotContains(response, f'id="hymn-{other}"')
                self.assertContains(response, f'lang="{lang}"')
                self.assertNotContains(response, 'hymn-tabs')
                self.assertContains(response, '<strong>Theme:</strong> New beginnings')

    def test_no_selected_hymn_has_no_lyrics_panel(self):
        response = self.client.get('/program-flow/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="hymn-panel"')
        self.assertContains(response, 'Program flow coming soon')

    def test_repeated_language_has_one_panel(self):
        for position in range(2):
            ProgramItem.objects.create(ceremony=self.ceremony, item_type='song', title='Hymn', hymn_language='english', position=position)
        response = self.client.get('/program-flow/')
        self.assertContains(response, 'id="hymn-english"', count=1)
