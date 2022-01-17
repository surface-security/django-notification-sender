from django.apps import AppConfig
from django.conf import settings

# IMPORT do not use "app_settings.py strategy" as that is not compatible with @override_settings (unittests)
# this strategy is
APP_SETTINGS = dict(
    MAIL_FROM=None,
    SLACK_APP_TOKEN=None,
    SLACK_TEAM=None,
)


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        for k, v in APP_SETTINGS.items():
            _k = 'NOTIFICATIONS_%s' % k
            if not hasattr(settings, _k):
                setattr(settings, _k, v)
