from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.contrib.admin.sites import AdminSite
from django.urls import reverse

from notifications import models, utils, admin


class Test(TestCase):
    @override_settings(NOTIFICATIONS_SLACK_URL='slack.url', NOTIFICATIONS_SLACK_NAME='TestBot')
    def test_create_slack_notifications(self):
        e = models.Event.objects.create(name='test_event')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.SLACK, target='@someone')
        self.assertEqual(utils.notify('test_event', 'Hello World!'), 1)
        self.assertEqual(models.Notification.objects.count(), 1)
        n = models.Notification.objects.first()
        self.assertEqual(n.message, 'Hello World!')
        self.assertEqual(n.status, models.Notification.STATUS_PENDING)

        self.assertEqual(utils.notify('test_event', 'Bye World...'), 1)
        self.assertEqual(models.Notification.objects.count(), 2)
        n = models.Notification.objects.last()
        self.assertEqual(n.message, 'Bye World...')
        self.assertEqual(n.status, models.Notification.STATUS_PENDING)

    @override_settings(NOTIFICATIONS_MAIL_FROM='some@mail.com')
    def test_create_email_notification(self):
        e = models.Event.objects.create(name='test_event')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='a@a.com')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='b@a.com')
        self.assertEqual(utils.notify('test_event', 'Hello World!'), 2)
        self.assertEqual(len(mail.outbox), 0)

    def test_api_notify(self):
        e = models.Event.objects.create(name='test_event')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='a@a.com')
        # TODO test url should be related to app (only /notify/), not project... how to?
        r = self.client.get(reverse('notifications:notify'))
        self.assertEqual(r.status_code, 400)

        r = self.client.post(reverse('notifications:notify'))
        self.assertEqual(r.status_code, 404)

        r = self.client.post(reverse('notifications:notify'), data={'event': 'some'})
        self.assertEqual(r.status_code, 404)

        r = self.client.post(reverse('notifications:notify'), data={'event': 'test_event'})
        self.assertEqual(r.status_code, 403)

        e.external_token = '123'
        e.save()

        r = self.client.post(reverse('notifications:notify'), data={'event': 'test_event', 'token': '321'})
        self.assertEqual(r.status_code, 403)

        r = self.client.post(reverse('notifications:notify'), data={'event': 'test_event', 'token': '123'})
        self.assertEqual(r.status_code, 400)

        r = self.client.post(
            reverse('notifications:notify'), data={'event': 'test_event', 'token': '123', 'message': 'hello'}
        )
        self.assertEqual(r.status_code, 200)
        self.assertJSONEqual(r.content, {'notifications': 1})
        self.assertEqual(len(mail.outbox), 0)

    def test_api_notify_multiline(self):
        e = models.Event.objects.create(name='test_event', external_token='123')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='a@a.com\nb@a.com')

        r = self.client.post(
            reverse('notifications:notify'), data={'event': 'test_event', 'token': '123', 'message': 'hello'}
        )
        self.assertEqual(r.status_code, 200)
        self.assertJSONEqual(r.content, {'notifications': 1})
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_custom_mail_and_slack_options(self):
        with override_settings(
            NOTIFICATIONS_MAIL_FROM='other.surface@betfair.com',
            NOTIFICATIONS_SLACK_URL='slack.url',
            NOTIFICATIONS_SLACK_NAME='TestBot',
        ):
            e = models.Event.objects.create(
                name='test_event',
                slack_username='NotTestBot',
                slack_icon=':something:',
                slack_unfurl_links=False,
                mail_from='not.surface@betfair.com',
            )
            models.Subscription.objects.create(event=e, service=models.Subscription.Service.SLACK, target='@someone')
            models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='at@mail.com')
            self.assertEqual(utils.notify('test_event', 'hello'), 2)
            self.assertEqual(models.Notification.objects.count(), 2)
            self.assertEqual(len(mail.outbox), 0)

    def test_api_notify_disabled_subscription(self):
        e = models.Event.objects.create(name='test_event', external_token='123')
        s = models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='f@b.com')

        r = self.client.post(
            reverse('notifications:notify'), data={'event': 'test_event', 'token': '123', 'message': 'hello'}
        )
        self.assertEqual(r.status_code, 200)
        self.assertJSONEqual(r.content, {'notifications': 1})

        s.enabled = False
        s.save()

        r = self.client.post(
            reverse('notifications:notify'), data={'event': 'test_event', 'token': '123', 'message': 'hello'}
        )
        self.assertEqual(r.status_code, 200)
        self.assertJSONEqual(r.content, {'notifications': 0})

    def test_admin_notification_test(self):
        e1 = models.Event.objects.create(name='test_event')
        s1 = models.Subscription.objects.create(event=e1, service=models.Subscription.Service.SLACK, target='@someone')
        sa1 = admin.SubscriptionAdmin(models.Subscription, AdminSite())
        m = mock.MagicMock()
        sa1.test_notification(m, models.Subscription.objects.filter(pk=s1.pk))
        m._messages.add.assert_called_with(20, '1 notifications created', '')
        self.assertEqual(models.Notification.objects.count(), 1)
        n = models.Notification.objects.first()
        self.assertEqual(n.message, 'Test notification')
        self.assertEqual(n.status, models.Notification.STATUS_PENDING)

    @mock.patch('slack_sdk.WebClient.chat_postMessage', return_value={'ok': True})
    def test_admin_target_validation(self, slack_mock):
        e1 = models.Event.objects.create(name='test_event')
        sub = models.Subscription.objects.create(event=e1, service=models.Subscription.Service.SLACK, target='@someone')
        subadmin = admin.SubscriptionAdmin(models.Subscription, AdminSite())
        form = subadmin.get_form(None)
        f1 = form(instance=sub)
        f1_initial = f1.initial
        # no data passed, not valid
        self.assertFalse(f1.is_valid())
        slack_mock.assert_not_called()
        # input same as initial data, all good
        f1 = form(f1_initial, instance=sub)
        self.assertTrue(f1.is_valid())
        slack_mock.assert_not_called()
        f1_initial['target'] = '@someone\n@otherone'
        f1 = form(f1_initial, instance=sub)
        self.assertTrue(f1.is_valid())
        # assert API is called only with the new target
        slack_mock.assert_called_once_with(
            channel='@otherone', text=':mega:  This channel just subscribed event *test_event* :newspaper:'
        )
