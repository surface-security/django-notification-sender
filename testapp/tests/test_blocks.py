from unittest import mock
from slack_sdk.errors import SlackApiError

from django.core import mail
from django.test import TestCase, override_settings

from notifications import models, blocks
from notifications import utils
from notifications.management.commands import notification_sender


@override_settings(
    NOTIFICATIONS_MAIL_FROM='some@mail.com', NOTIFICATIONS_SLACK_URL='slack.url', NOTIFICATIONS_SLACK_NAME='TestBot'
)
class Test(TestCase):
    """
    Asserts outputs with non-blocks (old) call and the matching blocks version
    """

    def setUp(self):
        super().setUp()
        p = mock.patch('notifications.management.commands.notification_sender.WebClient')
        self.sc_mock = p.start()
        self.sc_mock.return_value.chat_postMessage.return_value = {'ok': True}
        self.addCleanup(p.stop)
        self.ev1 = models.Event.objects.create(
            name='test_event',
            slack_username='NotTestBot',
            slack_icon=':something:',
            slack_unfurl_links=False,
            mail_from='not.surface@betfair.com',
        )
        self.sub1 = models.Subscription.objects.create(
            event=self.ev1, service=models.Subscription.Service.SLACK, target='@someone'
        )
        self.sub2 = models.Subscription.objects.create(
            event=self.ev1, service=models.Subscription.Service.MAIL, target='at@mail.com'
        )
        self.cmd = notification_sender.Command()

    def test_templated(self):
        self.assertEqual(
            utils.notify(
                'test_event',
                'dull version',
                template='random',
                context={'target': 'example.com', 'status': 'down'},
            ),
            2,
        )
        self.assertEqual(
            utils.notify(
                'test_event',
                blocks.TemplatedMail('dull version', 'random', {'target': 'example.com', 'status': 'down'}),
            ),
            2,
        )
        self.assertEqual(models.Notification.objects.count(), 4)

        self.cmd.handle_tick()

        # notification was sent
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_SENT).count(), 4)
        # proper template was rendered - html version *and* plaintext one (taken from the html)
        # two mails, both should look exactly the same
        self.assertEqual(len(mail.outbox), 2)
        for m in mail.outbox:
            self.assertEqual(m.from_email, 'not.surface@betfair.com')
            self.assertEqual(m.subject, 'example.com status')
            self.assertEqual(m.body, 'example.com is down\n\n')
            self.assertEqual(
                m.alternatives[0][0], '\n<!doctype html>\n<html>\n<body>\nexample.com is down\n</body>\n</html>\n'
            )
            self.assertEqual(m.to, ['at@mail.com'])
        # slack was properly formatted - with `message` only and same for block and non-block calls
        self.assertEqual(self.sc_mock.return_value.chat_postMessage.call_count, 2)
        for call in self.sc_mock.return_value.chat_postMessage.call_args_list:
            self.assertEqual(
                call,
                mock.call(
                    as_user=0,
                    blocks=[{'type': 'section', 'text': {'type': 'mrkdwn', 'text': 'dull version'}}],
                    channel='@someone',
                    icon_emoji=':something:',
                    text='dull version',
                    unfurl_links=0,
                    username='NotTestBot',
                ),
            )

    def test_message_blocks(self):
        list1 = ['apple']
        list2 = ['fiat', 'tesla']

        nblocks = blocks.Message()
        nblocks.append(blocks.Section(f"*Fruits in bag:* {len(list1)}"))
        nblocks.append(blocks.Context(list1))
        nblocks.append(blocks.Section(f"*Cars in garage:* {len(list2)}"))
        nblocks.append(blocks.Context(list2))
        self.assertEqual(
            utils.notify(self.ev1.name, nblocks),
            2,
        )

        self.cmd.handle_tick()

        # notification was sent
        self.assertEqual(models.Notification.objects.filter(status=models.Notification.STATUS_SENT).count(), 2)
        # proper template was rendered - html version *and* plaintext one (taken from the html)
        # two mails, both should look exactly the same
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        # self.assertEqual(m.from_email, 'not.surface@betfair.com')
        self.assertEqual(m.subject, None)
        self.assertEqual(
            m.body,
            '''\
*Fruits in bag:* 1
apple
*Cars in garage:* 2
fiat
tesla''',
        )
        self.assertEqual(len(m.alternatives), 0)
        self.assertEqual(m.to, ['at@mail.com'])
        # slack was properly formatted
        self.assertEqual(self.sc_mock.return_value.chat_postMessage.call_count, 1)
        self.sc_mock.return_value.chat_postMessage.assert_called_once_with(
            text='*Fruits in bag:* 1\napple\n*Cars in garage:* 2\nfiat\ntesla',
            channel='@someone',
            unfurl_links=0,
            username='NotTestBot',
            as_user=0,
            icon_emoji=':something:',
            blocks=[
                {'type': 'section', 'text': {'type': 'mrkdwn', 'text': '*Fruits in bag:* 1'}},
                {'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': 'apple'}]},
                {'type': 'section', 'text': {'type': 'mrkdwn', 'text': '*Cars in garage:* 2'}},
                {
                    'type': 'context',
                    'elements': [{'type': 'mrkdwn', 'text': 'fiat'}, {'type': 'mrkdwn', 'text': 'tesla'}],
                },
            ],
        )
