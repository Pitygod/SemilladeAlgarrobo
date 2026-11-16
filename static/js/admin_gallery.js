// Vista previa de imágenes en el admin de comunidades antes de guardar.
(function () {
    'use strict';

    function renderPreview(input) {
        let box = input.parentNode.querySelector('.gallery-upload-preview');
        if (!box) {
            box = document.createElement('div');
            box.className = 'gallery-upload-preview';
            box.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:8px';
            input.parentNode.appendChild(box);
        }
        box.innerHTML = '';
        Array.from(input.files || []).forEach(function (file) {
            if (!file.type.startsWith('image/')) return;
            const figure = document.createElement('figure');
            figure.style.cssText = 'margin:0;width:120px;font-size:11px;text-align:center';
            const img = document.createElement('img');
            img.alt = '';
            img.style.cssText = 'width:120px;height:80px;object-fit:cover;border-radius:6px;display:block';
            img.src = URL.createObjectURL(file);
            img.onload = function () { URL.revokeObjectURL(img.src); };
            const caption = document.createElement('figcaption');
            caption.textContent = file.name + ' (' + Math.round(file.size / 1024) + ' KB)';
            caption.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
            figure.appendChild(img);
            figure.appendChild(caption);
            box.appendChild(figure);
        });
    }

    document.addEventListener('change', function (event) {
        const input = event.target;
        if (input instanceof HTMLInputElement && input.type === 'file') {
            renderPreview(input);
        }
    });

    // Los <input type=file> de la galería no traen accept por defecto en filas nuevas.
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('input[type=file]').forEach(function (input) {
            if (!input.accept) input.accept = 'image/*';
        });
    });
})();
