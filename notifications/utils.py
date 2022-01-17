import json
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection, message
from templated_email import get_templated_mail
from typing import NamedTuple, Optional

from notifications.models import Event, Notification, Subscription
from . import blocks

logger = logging.getLogger(__name__)


class Attachment(NamedTuple):
    file_name: str
    file_path: str  # Only accepts files from MEDIA_ROOT
    file_type: str


def send_event_email(event, subject, message, recipient_list, html_message=None):
    with get_connection() as connection:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=event.mail_from or settings.NOTIFICATIONS_MAIL_FROM,
            to=recipient_list,
            reply_to=[event.mail_reply_to] if event.mail_reply_to else None,  # None by default
            connection=connection,
        )
        if html_message:
            msg.attach_alternative(html_message, 'text/html')
        return bool(msg.send())


def notify_templated(event_name, template, context, **kwargs):
    return notify(
        event_name,
        None,
        template=template,
        context=context,
        **kwargs,
    )


def __notify_blocks(event_name, block, queryset=None):
    """
    ALPHA method to experiment with block building to simplify all the extra options
    check blocks.py for the supported blocks!
    """
    if event_name is not None:
        event = Event.objects.get(name=event_name)
        if queryset is None:
            queryset = event.subscription_set
    elif queryset:
        # enabled flag does not really matter here
        event = queryset.first().event
    else:
        return 0

    count = 0

    queryset = queryset.filter(enabled=True)
    targets = queryset.filter(service=Subscription.Service.SLACK)
    if targets:
        api_kwargs = event.slack_api_kwargs()
        message, extra_kwargs = block.render_slack()
        api_kwargs.update(extra_kwargs)
        for subscription in targets:
            for target in subscription.target.split('\n'):
                Notification.objects.create(
                    subscription=subscription, message=message, target=target.strip(), options=json.dumps(api_kwargs)
                )
                count += 1

    targets = queryset.filter(service=Subscription.Service.MAIL)
    if targets:
        try:
            recipient_list = {
                mail.strip() for target in targets.values_list('target', flat=True) for mail in target.split('\n')
            }
            mail_body, options = block.render_mail(
                from_email=event.mail_from or settings.NOTIFICATIONS_MAIL_FROM,
                recipient_list=recipient_list,
            )
            recipient_list.update(set(options.get('recipient_list', [])))
            recipient_list = list(recipient_list)
            options['reply_to'] = [event.mail_reply_to] if event.mail_reply_to else None

            # FIXME: add html_message and attachments!

            for target in targets:
                Notification.objects.create(
                    subscription=target,
                    target=json.dumps(recipient_list),
                    message=mail_body,
                    options=json.dumps(options),
                    status=Notification.STATUS_PENDING,
                )
        except Exception:
            logger.exception('error notifying %s', event.name)
        count += targets.count()

    return count


def notify(
    event_name,
    message,
    subject=None,
    html_message=None,
    queryset=None,
    template=None,
    context=None,
    create_link=False,
    additional_email_targets=None,
    attachments: Optional[list[Attachment]] = None,
    slack_attachments=None,
) -> int:
    if isinstance(message, blocks.Block):
        # temporarily support both calls (eventually deprecate non-blocks and this method)
        return __notify_blocks(event_name, message)

    count = 0

    if event_name is not None:
        event = Event.objects.get(name=event_name)
        if queryset is None:
            queryset = event.subscription_set
    elif queryset:
        # enabled flag does not really matter here
        event = queryset.first().event
    else:
        return 0

    queryset = queryset.filter(enabled=True)

    slack_text = f'{subject}: {message}' if subject else message
    api_kwargs = event.slack_api_kwargs()
    if slack_attachments:
        # TODO: can this be taken from a more "generic" arg and also use it in email?
        api_kwargs['attachments'] = slack_attachments
    for subscription in queryset.filter(service=Subscription.Service.SLACK):
        for target in subscription.target.split('\n'):
            Notification.objects.create(
                subscription=subscription, message=slack_text, target=target.strip(), options=json.dumps(api_kwargs)
            )
            count += 1

    targets = queryset.filter(service=Subscription.Service.MAIL)
    if targets:
        try:
            recipient_list = {
                mail.strip() for target in targets.values_list('target', flat=True) for mail in target.split('\n')
            }

            if additional_email_targets:
                recipient_list.update(set(additional_email_targets))

            recipient_list = list(recipient_list)

            mail_body = message
            mail_options = dict(
                subject=subject,
                from_email=event.mail_from or settings.NOTIFICATIONS_MAIL_FROM,
                reply_to=[event.mail_reply_to] if event.mail_reply_to else None,
                html_message=html_message,
                attachments=attachments,
            )

            prepare_and_store_notifications(
                template=template,
                event=event,
                create_link=create_link,
                recipient_list=recipient_list,
                context=context,
                mail_options=mail_options,
                targets=targets,
                mail_body=mail_body,
            )
        except Exception:
            logger.exception('error notifying %s', event.name)
        count += targets.count()

    return count


def prepare_and_store_notifications(
    template: str,
    event: Event,
    create_link: bool,
    recipient_list: list,
    context: str,
    mail_options: dict,
    targets: list,
    mail_body: str,
) -> None:
    if template:
        template_message = get_templated_mail(
            template_name=template,
            context=context,
            from_email=event.mail_from or settings.NOTIFICATIONS_MAIL_FROM,
            create_link=create_link,
            to=recipient_list,
        )
        mail_options["subject"] = template_message.subject
        mail_body = template_message.body
        for alt in template_message.alternatives:
            if alt[1] == 'text/html':
                mail_options["html_message"] = alt[0]
                break
    for target in targets:
        Notification.objects.create(
            subscription=target,
            target=json.dumps(recipient_list),
            message=mail_body,
            options=json.dumps(mail_options),
            status=Notification.STATUS_PENDING,
        )
