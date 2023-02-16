import json

from django.db import models
from django.template.defaultfilters import truncatechars


class EventRef:
    """
    EventRef is not a model but instead a reference to current (or future, if not yet migrated) Event.
    This allows hardcoded events to be statically referenced and automatically provisioned
    (instead of requiring a data-only migration or the event to be manually added before code is used)
    """

    __refs = []

    def __init__(self, name, description):
        self.__class__.__refs.append(self)
        self.name = name
        self.description = description

    def __repr__(self) -> str:
        # to be able to use EventRef directly in Event.name queries
        return self.name

    def get_event(self) -> 'Event':
        return Event.objects.get(name=self)

    @classmethod
    def get_references(cls):
        # return a copy of the references
        return cls.__refs[:]


class Event(models.Model):
    name = models.CharField(max_length=50, primary_key=True)
    description = models.TextField(blank=True)
    external_token = models.CharField(
        max_length=50, null=True, blank=True, help_text="If set, notifications be posted to this event through the API"
    )
    slack_username = models.CharField(
        max_length=50, null=True, blank=True, help_text='Choose a display name for Slack bot (instead of default)'
    )
    slack_icon = models.CharField(
        max_length=50, null=True, blank=True, help_text='Choose an icon for Slack bot (instead of default)'
    )
    slack_unfurl_links = models.BooleanField(
        default=True, help_text='Pass true to enable unfurling of primarily text-based content on Slack'
    )
    mail_from = models.CharField(
        max_length=200, null=True, blank=True, help_text='Choose the sender address of the email (instead of default)'
    )
    mail_reply_to = models.CharField(
        max_length=200, null=True, blank=True, help_text='Choose the reply-to address of the email (instead of none)'
    )

    def __str__(self) -> str:
        return self.name

    def slack_api_kwargs(self):
        api_kwargs = {}
        if not self.slack_unfurl_links:
            api_kwargs['unfurl_links'] = 0
        if self.slack_username:
            api_kwargs['username'] = self.slack_username
            api_kwargs['as_user'] = 0
        else:
            api_kwargs['as_user'] = 1
        if self.slack_icon:
            api_kwargs['icon_emoji'] = self.slack_icon
        return api_kwargs

    class Meta:
        verbose_name = 'Event'
        verbose_name_plural = 'Events'


class Subscription(models.Model):
    class Service(models.TextChoices):
        SLACK = 'S'
        MAIL = 'M'

    event = models.ForeignKey('Event', null=True, on_delete=models.CASCADE)
    service = models.CharField(max_length=1, choices=Service.choices)
    target = models.TextField(blank=True, help_text='You can specify multiple targets, one per line.')
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f'[{self.event}] {self.get_service_display()}: {truncatechars(self.target, 10)}'

    class Meta:
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'


class Notification(models.Model):
    STATUS_ERROR = -1
    STATUS_PENDING = 0
    STATUS_SENT = 1

    STATUS_TYPES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_ERROR, 'Error'),
    )
    time = models.DateTimeField(auto_now_add=True)
    subscription = models.ForeignKey('notifications.Subscription', null=True, on_delete=models.deletion.SET_NULL)
    message = models.TextField()
    status = models.IntegerField(default=0, choices=STATUS_TYPES)
    target = models.TextField(null=True, default=None)
    options = models.TextField(null=True, default=None)

    def __str__(self) -> str:
        return f'[{self.get_status_display()}] {self.subscription}'

    @property
    def options_dict(self):
        if self.options:
            return json.loads(self.options)
        return {}

    @property
    def slack_options(self):
        options = self.options_dict
        if 'blocks' not in options:
            options['blocks'] = [{"type": "section", "text": {"type": "mrkdwn", "text": self.message}}]
        return options

    class Meta:
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
