from unittest import mock
from slack_sdk.errors import SlackApiError

from django.core import mail
from django.test import TestCase, override_settings
from django.core.management import call_command

from notifications import models
from notifications import utils
from notifications.management.commands import notification_sender


@override_settings(
    NOTIFICATIONS_MAIL_FROM='some@mail.com', NOTIFICATIONS_SLACK_URL='slack.url', NOTIFICATIONS_SLACK_NAME='TestBot'
)
class SenderTest(TestCase):
    def setUp(self):
        super().setUp()
        p = mock.patch('notifications.management.commands.notification_sender.WebClient')
        self.sc_mock = p.start()
        self.addCleanup(p.stop)

    def test_can_send_notifications_by_type(self):
        self.sc_mock.return_value.chat_postMessage.return_value = {'ok': True}
        # GIVEN an event that creates a slack and email notification
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
        # WHEN the command to send them is ran
        call_command('notification_sender', run_once=True)
        # THEN both notifications should change to SENT State
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_SENT).count(), 2)
        # AND THEN the email outbox should contain one email
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.from_email, 'not.surface@betfair.com')
        self.assertEqual(m.subject, None)
        self.assertEqual(m.body, 'hello')
        self.assertEqual(m.to, ['at@mail.com'])
        # AND THEN the slack_api_call should be one.
        self.sc_mock.return_value.chat_postMessage.assert_called_once_with(
            as_user=0,
            blocks=[{'type': 'section', 'text': {'type': 'mrkdwn', 'text': 'hello'}}],
            channel='@someone',
            icon_emoji=':something:',
            text='hello',
            unfurl_links=0,
            username='NotTestBot',
        )

    def test_handle_slack_random_error(self):
        self.sc_mock.return_value.chat_postMessage.side_effect = SlackApiError('none', {'error': 'random'})
        e = models.Event.objects.create(
            name='test_event',
            slack_username='NotTestBot',
            slack_icon=':something:',
            slack_unfurl_links=False,
            mail_from='not.surface@betfair.com',
        )
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.SLACK, target='@someone')
        self.assertEqual(utils.notify('test_event', 'hello'), 1)
        call_command('notification_sender', run_once=True)
        # status changed to ERROR
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_ERROR).count(), 1)
        self.sc_mock.return_value.chat_postMessage.assert_called_once()

    def test_handle_slack_rate_limit(self):
        cmd = notification_sender.Command()
        self.sc_mock.return_value.chat_postMessage.side_effect = SlackApiError(
            'none',
            mock.MagicMock(
                get=lambda x: 'ratelimited' if x == 'error' else None,
                headers={'retry-after': '2'},
            ),
        )
        e = models.Event.objects.create(
            name='test_event',
            slack_username='NotTestBot',
            slack_icon=':something:',
            slack_unfurl_links=False,
            mail_from='not.surface@betfair.com',
        )
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.SLACK, target='@someone')
        self.assertEqual(utils.notify('test_event', 'hello'), 1)

        cmd.handle_tick()
        # message posted but status still in PENDING (failed to rate limit)
        self.sc_mock.return_value.chat_postMessage.assert_called_once()
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_PENDING).count(), 1)

        self.sc_mock.return_value.chat_postMessage.reset_mock()
        cmd.handle_tick()
        # status still in PENDING and post was not retried
        self.sc_mock.return_value.chat_postMessage.assert_not_called()
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_PENDING).count(), 1)

        with mock.patch('time.time', return_value=cmd._Command__slack_limited + 2):
            self.sc_mock.return_value.chat_postMessage.side_effect = ['ok']
            cmd.handle_tick()
            # post retried, sent and status updated
            self.sc_mock.return_value.chat_postMessage.assert_called_once()
            self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_SENT).count(), 1)

    def test_templated_email(self):
        e = models.Event.objects.create(
            name='test_event',
            slack_username='NotTestBot',
            slack_icon=':something:',
            slack_unfurl_links=False,
            mail_from='not.surface@betfair.com',
        )
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.SLACK, target='@someone')
        models.Subscription.objects.create(event=e, service=models.Subscription.Service.MAIL, target='at@mail.com')
        self.assertEqual(
            utils.notify(
                'test_event',
                'dull version',
                template='random',
                context={'target': 'example.com', 'status': 'down'},
            ),
            2,
        )
        self.assertEqual(models.Notification.objects.count(), 2)

        call_command('notification_sender', run_once=True)

        # notification was sent
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_SENT).count(), 2)
        # proper template was rendered - html version *and* plaintext one (taken from the html)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.from_email, 'not.surface@betfair.com')
        self.assertEqual(m.subject, 'example.com status')
        self.assertEqual(m.body, 'example.com is down\n\n')
        self.assertEqual(
            m.alternatives[0][0], '\n<!doctype html>\n<html>\n<body>\nexample.com is down\n</body>\n</html>\n'
        )
        self.assertEqual(m.to, ['at@mail.com'])
        # slack was properly formatted - with `message` only
        self.sc_mock.return_value.chat_postMessage.assert_called_once_with(
            as_user=0,
            blocks=[{'type': 'section', 'text': {'type': 'mrkdwn', 'text': 'dull version'}}],
            channel='@someone',
            icon_emoji=':something:',
            text='dull version',
            unfurl_links=0,
            username='NotTestBot',
        )
