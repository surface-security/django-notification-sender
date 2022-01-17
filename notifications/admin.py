import json

from django.contrib import admin
from django.contrib.admin.widgets import AdminTextInputWidget
from django import forms
from django.conf import settings
from django.contrib.admin.utils import unquote
from django.template.defaultfilters import truncatechars
from django.template.response import TemplateResponse
from django.http.response import HttpResponseNotFound
from django.core.exceptions import PermissionDenied
from django.utils.html import format_html_join
from django.utils.text import capfirst

from notifications import models, utils


class RandomTokenWidget(AdminTextInputWidget):
    template_name = 'django/forms/widgets/randomgeneratetext.html'

    class Media:
        js = ('django/forms/widgets/randomgeneratetext.js',)


@admin.register(models.Event)
class EventAdmin(admin.ModelAdmin):
    fieldsets = (
        (None, {'fields': ('name', 'external_token')}),
        ('Slack only', {'fields': ('slack_username', 'slack_icon', 'slack_unfurl_links')}),
        ('Mail only', {'fields': ('mail_from', 'mail_reply_to')}),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        ff = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'external_token':
            ff.widget = RandomTokenWidget()
        return ff


class SubscriptionAdminForm(forms.ModelForm):
    def __validate_email_target(self):
        for x in self.cleaned_data.get('target', '').splitlines():
            if x and '@' not in x:
                self.add_error('target', f'{x} is not a valid email.')

    def __validate_slack_target(self):
        # faster cold boot
        import slack_sdk

        slackclient = slack_sdk.WebClient(token=settings.NOTIFICATIONS_SLACK_APP_TOKEN)
        # API only allows query user/channel by ID
        # using list to be able to validate on names will return near 10k records on each of the endpoints
        # easiest (and most accurate): post test message and check error message
        old_targets = set(self.initial.get('target', '').splitlines())
        new_targets = set(self.cleaned_data.get('target', '').splitlines())
        to_check = new_targets - old_targets
        for x in to_check:
            try:
                slackclient.chat_postMessage(
                    channel=x,
                    text=f':mega:  This channel just subscribed event *{self.cleaned_data.get("event")}* :newspaper:',
                    as_user=1,
                )
            except slack_sdk.errors.SlackApiError as e:
                self.add_error(
                    'target', f'{x} is not a valid slack channel/user (or it is private) - {e.response.data["error"]}'
                )

    def clean(self):
        if 'target' in self.changed_data:
            _s = self.cleaned_data.get('service')
            if _s == models.Subscription.Service.MAIL:
                self.__validate_email_target()
            elif _s == models.Subscription.Service.SLACK:
                self.__validate_slack_target()
        return self.cleaned_data


@admin.register(models.Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    form = SubscriptionAdminForm
    list_display = ('event', 'service', 'target', 'enabled')
    list_filter = ('event', 'service', 'target', 'enabled')
    search_fields = ('event__name', 'target')
    list_select_related = ('event',)
    actions = ['test_notification']

    def test_notification(self, request, queryset):
        count = utils.notify(None, 'Test notification', queryset=queryset)
        self.message_user(request, '%d notifications created' % count)

    test_notification.short_description = 'Send test notification'

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser and 'test_notification' in actions:
            del actions['test_notification']
        return actions


@admin.register(models.Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'subscription', 'time', 'status', 'get_target')
    list_filter = (
        'time',
        'subscription',
        'status',
        'subscription__event',
        'subscription__service',
    )
    list_filter_select_related = {'subscription': ('event',)}
    readonly_fields = ('time', 'subscription', 'status', 'message', 'target', 'options')
    list_select_related = ('subscription', 'subscription__event')
    no_global_search = True

    def get_urls(self):
        from django.urls import path

        urls = super().get_urls()
        urls.insert(
            0,
            path(
                '<path:object_id>/preview/',
                self.admin_site.admin_view(self.preview_view),
                name='notifications_notification_preview',
            ),
        )
        return urls

    def preview_view(self, request, object_id, extra_context=None):
        # ref: ModelAdmin.history_view
        # First check if the user can view this notification.
        model = self.model
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            return self._get_obj_does_not_exist_redirect(request, model._meta, object_id)
        if not self.has_view_permission(request):
            raise PermissionDenied

        opts = model._meta
        context = {
            **self.admin_site.each_context(request),
            'title': 'Preview: %s' % obj,
            'module_name': str(capfirst(opts.verbose_name_plural)),
            'object_id': object_id,
            'original': obj,
            'object': obj,
            'message': obj.message,
            'opts': opts,
            'preserved_filters': self.get_preserved_filters(request),
            'has_view_permission': True,
            **(extra_context or {}),
        }
        request.current_app = self.admin_site.name

        if obj.subscription.service == models.Subscription.Service.SLACK:
            # block-builder preview limit is 3000 per full payload
            # TODO: improve this truncation in the future (for multiple blocks / attachments)
            # for now, truncate "text" to 1000..
            extra_options = obj.slack_options
            message_blocks = extra_options['blocks']
            message_blocks[0]['text']['text'] = truncatechars(message_blocks[0]['text']['text'], 1000)
            message_blocks = json.dumps({'blocks': message_blocks})
            attachment_blocks = [
                (json.dumps(_a['blocks'], indent=4), json.dumps(_a))
                for _a in extra_options.get('attachments', [])
                if 'blocks' in _a
            ]
            context.update(
                {
                    'message_blocks': message_blocks,
                    'slack_team': settings.NOTIFICATIONS_SLACK_TEAM or '',
                    'attachments': attachment_blocks,
                }
            )
            return TemplateResponse(request, "admin/notifications/notification/preview_slack.html", context)
        elif obj.subscription.service == models.Subscription.Service.MAIL:
            context['html_message'] = obj.options_dict.get('html_message')
            return TemplateResponse(request, "admin/notifications/notification/preview_mail.html", context)
        else:
            raise HttpResponseNotFound(f'{obj.subscription.service} not supported')

    def get_target(self, obj):
        targets = [obj.target]
        if obj.target and obj.target[:2] == '["':
            try:
                targets = json.loads(obj.target)
            except Exception:
                # let it be treated as single target
                pass
        return format_html_join('', '<span class="badge">{}</span>', ((target,) for target in targets))

    get_target.short_description = 'Target'
    get_target.admin_order_field = 'target'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
