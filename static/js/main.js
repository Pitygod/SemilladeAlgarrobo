document.addEventListener('DOMContentLoaded', () => {
    initToasts();
    initDonationModal();
    initGallery();
    initCarousels();
    initAmountPicker();
});

function initToasts() {
    document.querySelectorAll('.toast[data-auto-dismiss]').forEach(toast => {
        const delay = parseInt(toast.dataset.autoDismiss, 10) || 5000;
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity .3s';
            setTimeout(() => toast.remove(), 300);
        }, delay);
    });
}

function initDonationModal() {
    const modal = document.getElementById('donation-modal');
    const successModal = document.getElementById('success-modal');
    if (!modal) return;

    const form = document.getElementById('donation-form');
    const amountInput = document.getElementById('donation-amount');
    const needIdInput = document.getElementById('donation-need-id');
    const errorEl = document.getElementById('donation-error');

    document.querySelectorAll('.btn-donate').forEach(btn => {
        btn.addEventListener('click', () => {
            const needId = btn.dataset.needId;
            const needTitle = btn.dataset.needTitle;
            const communityName = btn.dataset.communityName;
            const remaining = parseFloat(btn.dataset.remaining);

            needIdInput.value = needId;
            document.getElementById('modal-subtitle').textContent =
                `Ayuda a ${communityName} con su necesidad de ${needTitle.split(' ').slice(-3).join(' ').toLowerCase()}.`;
            document.getElementById('modal-need-title').textContent = needTitle;
            document.getElementById('modal-remaining').textContent =
                '$' + remaining.toLocaleString('es-AR');
            amountInput.value = Math.min(10000, remaining);
            amountInput.max = remaining;
            errorEl.classList.add('hidden');
            modal.classList.remove('hidden');
        });
    });

    document.querySelectorAll('[data-close-modal]').forEach(el => {
        el.addEventListener('click', () => modal.classList.add('hidden'));
    });

    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            amountInput.value = btn.dataset.amount;
        });
    });

    form?.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.classList.add('hidden');

        const needId = needIdInput.value;
        const url = window.DONATE_URL_TEMPLATE.replace('{id}', needId);
        const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': csrf,
                },
                body: new URLSearchParams({ amount: amountInput.value }),
            });

            const data = await response.json();

            if (!data.success) {
                errorEl.textContent = data.error || 'Error al procesar la donación.';
                errorEl.classList.remove('hidden');
                return;
            }

            modal.classList.add('hidden');
            showSuccessModal(data);
        } catch {
            errorEl.textContent = 'Error de conexión. Intentá de nuevo.';
            errorEl.classList.remove('hidden');
        }
    });

    document.querySelectorAll('[data-close-success]').forEach(el => {
        el.addEventListener('click', () => {
            successModal.classList.add('hidden');
            window.location.reload();
        });
    });
}

function showSuccessModal(data) {
    const successModal = document.getElementById('success-modal');
    document.getElementById('success-message').textContent =
        `Gracias por tu generosidad. Tu donación ayudará a ${data.community}.`;
    document.getElementById('success-amount').textContent =
        '$' + data.amount.toLocaleString('es-AR');
    document.getElementById('success-community').textContent = data.community;
    document.getElementById('success-need').textContent = data.need;
    document.getElementById('success-code').value = data.confirmation_code;
    successModal.classList.remove('hidden');
}

function showToast(message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast toast-show';
    toast.innerHTML = `<span class="toast-icon">✓</span><span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}


/* ---------------------------------------------------------------------------
 * Galería de la comunidad: miniaturas + visor ampliado (lightbox).
 * ------------------------------------------------------------------------- */
function initGallery() {
    const gallery = document.querySelector('[data-gallery]');
    if (!gallery) return;
    const mainImg = gallery.querySelector('[data-gallery-main]');
    const caption = gallery.querySelector('[data-gallery-caption]');
    const thumbs = Array.from(gallery.querySelectorAll('[data-gallery-thumb]'));
    const lightbox = document.querySelector('[data-lightbox]');
    const itemsEl = lightbox?.querySelector('[data-gallery-items]');
    let items = [];
    try { items = itemsEl ? JSON.parse(itemsEl.textContent) : []; } catch { items = []; }
    let current = 0;

    function show(index) {
        if (!items.length) return;
        current = (index + items.length) % items.length;
        const item = items[current];
        if (mainImg) { mainImg.src = item.src; mainImg.alt = item.alt; }
        if (caption) caption.textContent = item.caption || '';
        thumbs.forEach((t, i) => {
            t.classList.toggle('is-active', i === current);
            if (i === current) t.setAttribute('aria-current', 'true'); else t.removeAttribute('aria-current');
        });
        if (lightbox?.open) renderLightbox();
    }

    function renderLightbox() {
        const item = items[current];
        lightbox.querySelector('[data-lightbox-img]').src = item.src;
        lightbox.querySelector('[data-lightbox-img]').alt = item.alt;
        lightbox.querySelector('[data-lightbox-caption]').textContent =
            (item.caption ? item.caption + ' · ' : '') + (current + 1) + ' / ' + items.length;
    }

    thumbs.forEach(t => t.addEventListener('click', () => show(parseInt(t.dataset.index, 10))));

    gallery.querySelector('[data-gallery-open]')?.addEventListener('click', () => {
        if (!lightbox || typeof lightbox.showModal !== 'function') return;
        renderLightbox();
        lightbox.showModal();
    });
    lightbox?.querySelector('[data-lightbox-close]')?.addEventListener('click', () => lightbox.close());
    lightbox?.querySelectorAll('[data-lightbox-step]').forEach(btn =>
        btn.addEventListener('click', () => show(current + parseInt(btn.dataset.lightboxStep, 10))));
    lightbox?.addEventListener('click', (e) => { if (e.target === lightbox) lightbox.close(); });
    lightbox?.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight') show(current + 1);
        if (e.key === 'ArrowLeft') show(current - 1);
    });

    // Deslizar con el dedo en el visor (celulares).
    let startX = null;
    lightbox?.addEventListener('touchstart', (e) => { startX = e.touches[0].clientX; }, { passive: true });
    lightbox?.addEventListener('touchend', (e) => {
        if (startX === null) return;
        const dx = e.changedTouches[0].clientX - startX;
        if (Math.abs(dx) > 40) show(current + (dx < 0 ? 1 : -1));
        startX = null;
    });
}

/* ---------------------------------------------------------------------------
 * Carrusel horizontal (scroll-snap) con botones anterior / siguiente.
 * ------------------------------------------------------------------------- */
function initCarousels() {
    document.querySelectorAll('[data-carousel-controls]').forEach(controls => {
        const track = document.getElementById(controls.dataset.carouselControls);
        if (!track) return;
        controls.querySelectorAll('[data-dir]').forEach(btn => {
            btn.addEventListener('click', () => {
                const card = track.querySelector('.carousel-item');
                const step = card ? card.getBoundingClientRect().width + 20 : track.clientWidth * 0.8;
                track.scrollBy({ left: step * parseInt(btn.dataset.dir, 10), behavior: 'smooth' });
            });
        });
        const update = () => {
            const max = track.scrollWidth - track.clientWidth - 4;
            controls.querySelector('[data-dir="-1"]').disabled = track.scrollLeft <= 4;
            controls.querySelector('[data-dir="1"]').disabled = track.scrollLeft >= max;
            controls.hidden = track.scrollWidth <= track.clientWidth + 4;
        };
        track.addEventListener('scroll', update, { passive: true });
        window.addEventListener('resize', update);
        update();
    });
}

/* ---------------------------------------------------------------------------
 * Donación única: muestra el campo "Otro importe" solo cuando corresponde.
 * (Solo mejora la interfaz: el importe se valida siempre en el servidor.)
 * ------------------------------------------------------------------------- */
function initAmountPicker() {
    const custom = document.querySelector('[data-custom-amount]');
    if (!custom) return;
    const radios = document.querySelectorAll('input[name="amount_choice"]');
    const input = custom.querySelector('input');
    const sync = () => {
        const selected = document.querySelector('input[name="amount_choice"]:checked');
        const isOther = selected && selected.value === 'otro';
        custom.hidden = !isOther && !custom.querySelector('.field-error');
        if (isOther) input?.focus({ preventScroll: true });
    };
    radios.forEach(r => r.addEventListener('change', sync));
    sync();
}
