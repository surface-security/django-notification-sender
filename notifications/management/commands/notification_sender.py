import json
import logging
import time

from pathlib import Path
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management import BaseCommand
from slack_sdk import WebClient, errors

from database_locks import locked
from notifications.models import Notification, Subscription
from django.conf import settings

logger = logging.getLogger(__name__)


@locked
class Command(BaseCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__sc = WebClient(settings.NOTIFICATIONS_SLACK_APP_TOKEN)
        self.__slack_limited = time.time()

    def add_arguments(self, parser):
        parser.add_argument('-1', '--run-once', action='store_true', default=False, help='Run only one check')

    def handle_tick(self):
        for notification in Notification.objects.filter(status=Notification.STATUS_PENDING).select_related(
            'subscription'
        ):
            try:
                if notification.subscription.service == Subscription.Service.SLACK:
                    if self.__slack_limited < time.time():
                        self.__send_slack_notifications(notification)
                elif notification.subscription.service == Subscription.Service.MAIL:
                    self.__send_email_notifications(notification)
                else:
                    notification.status = Notification.STATUS_ERROR
                    logger.error(
                        'notify failed - %d - bad service %s', notification.pk, notification.subscription.service
                    )
            except Exception as e:
                notification.status = Notification.STATUS_ERROR
                notification.save()
                logger.exception(e)

    def handle(self, *args, **options):
        """
        Main method that starts the infinite loop to fetch for pending notifications.
        When those exists, then it calls its sub methods to send Slack and Email notifications according to their types.
        """
        while True:
            self.handle_tick()
            if options['run_once']:
                break
            time.sleep(1)

    def __send_slack_notifications(self, notification):
        """
        Method responsible for handling slack notifications.
        Provided a single notifications that still is in pending state and that its subscription type is slack,
        then the method sends it using the slackclient module.
        If the notification is sent successfully then it updates its Status field to to Status_SENT. Otherwise,
        the Notification's Status property is changed to STATUS_ERROR.
        :param notification: Set of notifications with SLACK subscription and PENDING status.
        """
        try:
            self.__sc.chat_postMessage(
                # text still required for message preview (in notifications)
                text=notification.message,
                channel=notification.target,
                **notification.slack_options,
            )
            notification.status = Notification.STATUS_SENT
            notification.save(update_fields=['status'])
        except errors.SlackApiError as e:
            if e.response.get('error') == 'ratelimited':
                # handle rate limit
                try:
                    retry_after = int(e.response.headers.get('retry-after')) + 5
                except (ValueError, TypeError):
                    # if no header (weird), wait 15s
                    retry_after = 15
                self.__slack_limited = time.time() + retry_after
                logger.warning('rate limited on %d - waiting %d secs', notification.pk, retry_after)
            else:
                notification.status = Notification.STATUS_ERROR
                logger.error('notify failed - %d - %s', notification.pk, e.response.get('error'))
                notification.save(update_fields=['status'])

    def __send_email_notifications(self, notification):
        """
        Method responsible for sending email notifications.
        Provided a single notification that still is in pending state and that is subscription type mail,
        then the method sends it to the list of targets using the Django.Core.Email dependency.
        If the email is sent successfully, then the Notification's status is changed to STATUS_SENT. Otherwise,
        the Notification's status property is changed to STATUS_ERROR.
        :param notification: Single notification of MAIL subscription with PENDING status.
        """
        email_args = json.loads(notification.options)
        with get_connection() as connection:
            msg = EmailMultiAlternatives(
                subject=email_args.get('subject'),
                body=notification.message,
                from_email=email_args.get('from_email'),
                to=json.loads(notification.target),
                reply_to=email_args.get('reply_to'),
                connection=connection,
            )
            if email_args.get("attachments"):
                MEDIA_ROOT = Path(settings.MEDIA_ROOT).resolve()
                for attach in email_args.get("attachments"):
                    path = Path(attach[1]).resolve()
                    try:
                        # check if path is relative to MEDIA_ROOT
                        path.relative_to(MEDIA_ROOT)
                    except ValueError:
                        logger.error('invalid path for attachment: %s', path)
                        continue

                    if path.exists() and not path.is_dir():
                        with path.open() as attachment:
                            msg.attach(attach[0], attachment.read(), attach[2])
                    else:
                        logger.error('could not open file from path: %s', path)
            if email_args.get('html_message'):
                msg.attach_alternative(email_args.get('html_message'), 'text/html')
            msg.send()
            notification.status = Notification.STATUS_SENT
            notification.save(update_fields=['status'])
