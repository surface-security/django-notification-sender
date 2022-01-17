## Notifications

Pluggable app to centralize notification configuration.


Available settings:

* `NOTIFICATIONS_MAIL_FROM` - sender for mail notifications (falls back to `settings.DEFAULT_FROM_EMAIL`)
* `NOTIFICATIONS_SLACK_APP_TOKEN` - Slack app token to be used to post the notifications using API, not incoming webhook (no default, set it or slack won't work!)


To use external notifications make sure to update your project `urls.py` to add a valid path for notifications

```
urlpatterns = [
    ...
    path(
        'api/notifications/', include(('notifications.urls', 'notifications'), namespace='notifications')
    ),
    ...
]
```

This would allow external notifications to be POSTed to `api/notifications/notify/`
