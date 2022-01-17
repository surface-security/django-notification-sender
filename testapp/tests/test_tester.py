from io import StringIO

from django.test import TestCase
from django.core.management import call_command

from notifications import models


class Test(TestCase):
    def test_command(self):
        out = StringIO()
        e = models.Event.objects.create(name='test_event')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.SLACK, target='@someone')
        call_command('notification_test', 'test_event', 'Hello World!', stdout=out)
        self.assertEqual(models.Notification.objects.count(), 1)
        n = models.Notification.objects.first()
        self.assertEqual(n.message, 'Hello World!')
        self.assertEqual(n.status, models.Notification.STATUS_PENDING)
        self.assertEqual(out.getvalue().strip(), '1 notifications created')
