/* Espace « Forfaits internet CVGP » : pad de signature des exports PDF (sans dépendance). */
(function ($) {
    'use strict';

    function SignaturePad(wrapper) {
        var canvas = wrapper.querySelector('canvas');
        var ctx = canvas.getContext('2d');
        var drawing = false;
        var dirty = false;
        var last = null;

        function clear() {
            ctx.save();
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.restore();
            dirty = false;
        }

        // Le canvas est dans une modale masquée au chargement : sa taille n'est connue qu'une
        // fois affiché, d'où un redimensionnement explicite à chaque affichage.
        function resize() {
            var rect = canvas.getBoundingClientRect();
            if (!rect.width) return;
            var ratio = window.devicePixelRatio || 1;
            canvas.width = Math.round(rect.width * ratio);
            canvas.height = Math.round(rect.height * ratio);
            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            ctx.lineWidth = 2.2;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.strokeStyle = '#111111';
            clear();
        }

        function position(event) {
            var rect = canvas.getBoundingClientRect();
            return {x: event.clientX - rect.left, y: event.clientY - rect.top};
        }

        canvas.addEventListener('pointerdown', function (event) {
            drawing = true;
            last = position(event);
            canvas.setPointerCapture(event.pointerId);
            event.preventDefault();
        });
        canvas.addEventListener('pointermove', function (event) {
            if (!drawing) return;
            var point = position(event);
            ctx.beginPath();
            ctx.moveTo(last.x, last.y);
            ctx.lineTo(point.x, point.y);
            ctx.stroke();
            last = point;
            dirty = true;
            event.preventDefault();
        });
        ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (name) {
            canvas.addEventListener(name, function () { drawing = false; });
        });
        wrapper.querySelector('.ic-pad-clear').addEventListener('click', clear);

        return {
            resize: resize,
            isEmpty: function () { return !dirty; },
            toDataURL: function () { return canvas.toDataURL('image/png'); }
        };
    }

    $('.ic-export-form').each(function () {
        var form = $(this);
        var wrapper = form.find('.ic-pad-wrapper');
        var pad = new SignaturePad(wrapper.get(0));

        function mode() {
            return form.find('.ic-signature-mode:checked').val();
        }

        function togglePad() {
            var drawn = mode() === 'drawn';
            wrapper.toggle(drawn);
            if (drawn) pad.resize();
        }

        form.find('.ic-signature-mode').on('change', togglePad);
        form.closest('.modal').on('shown.bs.modal', togglePad);

        form.on('submit', function (event) {
            var hidden = form.find('.ic-drawn-signature');
            hidden.val('');
            if (mode() === 'drawn') {
                if (pad.isEmpty()) {
                    event.preventDefault();
                    form.find(':submit').prop('disabled', false);  // déjà désactivé par disableOnSubmit.js
                    alert(wrapper.data('empty-message'));
                    return false;
                }
                hidden.val(pad.toDataURL());
            }
            // La réponse est un fichier téléchargé : la page ne se recharge pas. On réactive donc
            // le bouton désactivé par disableOnSubmit.js et on referme la modale.
            setTimeout(function () {
                form.find(':submit').prop('disabled', false);
                form.closest('.modal').modal('hide');
            }, 1500);
        });
    });
})(jQuery);
