from django.http.response import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from notifications import models, utils


@csrf_exempt
def notify(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'invalid method'}, status=400)

    event = request.POST.get('event')
    if event is None:
        return JsonResponse({'error': 'event not found'}, status=404)
    try:
        ev = models.Event.objects.get(name=event)
    except models.Event.DoesNotExist:
        return JsonResponse({'error': 'event not found'}, status=404)

    if not ev.external_token or ev.external_token != request.POST.get('token'):
        return JsonResponse({'error': 'invalid token'}, status=403)

    if not request.POST.get('message'):
        return JsonResponse({'error': 'missing message'}, status=400)

    c = utils.notify(
        ev.name,
        request.POST.get('message'),
        subject=request.POST.get('subject'),
        html_message=request.POST.get('html_message'),
    )

    return JsonResponse({'notifications': c}, status=200)
