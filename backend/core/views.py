from django.http import JsonResponse


def health(request):
    return JsonResponse({'status': 'ok'})


def modules(request):
    from core.module_registry import get_enabled_modules

    return JsonResponse(
        {'data': [module.as_api_dict() for module in get_enabled_modules()]}
    )
