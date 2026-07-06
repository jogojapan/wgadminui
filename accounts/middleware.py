from django.utils import translation

class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and getattr(request.user, 'language', None):
            translation.activate(request.user.language)
            request.LANGUAGE_CODE = translation.get_language()
            
        response = self.get_response(request)
        return response
