from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .forms import LoginForm, RegisterForm


def _safe_next(request):
    """Destino tras iniciar sesión (?next=), solo si es una URL de este sitio."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return ''


@require_http_methods(['GET', 'POST'])
def auth_view(request):
    next_url = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(next_url or 'communities:list')

    tab = request.POST.get('tab') or request.GET.get('tab', 'login')
    login_form = LoginForm(request, data=request.POST if request.method == 'POST' and tab == 'login' else None)
    register_form = RegisterForm(request.POST if request.method == 'POST' and tab == 'register' else None)

    if request.method == 'POST':
        if tab == 'login' and login_form.is_valid():
            login(request, login_form.get_user())
            messages.success(request, f'Bienvenido, {request.user.get_display_name()}!')
            return redirect(next_url or 'communities:list')

        if tab == 'register' and register_form.is_valid():
            user = register_form.save()
            login(request, user)
            messages.success(request, 'Cuenta creada exitosamente.')
            return redirect(next_url or 'communities:list')

        if tab == 'register' and register_form.errors:
            tab = 'register'
        elif tab == 'login' and login_form.errors:
            tab = 'login'

    return render(request, 'accounts/auth.html', {
        'tab': tab,
        'login_form': login_form,
        'register_form': register_form,
        'next': next_url,
    })


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, 'Sesión cerrada correctamente.')
    return redirect('home')
