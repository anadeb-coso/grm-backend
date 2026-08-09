(function ($) {
    var AUDIO_MIME = { mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4', ogg: 'audio/ogg', aac: 'audio/aac' };
    var VIDEO_MIME = { mp4: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm' };
    var IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'];
    // `.3gp`/`.amr` : format produit par les enregistrements vocaux de l'app mobile (codec AMR) —
    // vérifié sur des pièces jointes réelles en base (`Attachment.file_name` se termine en `.3gp`,
    // le champ `content_type` stocké dit "audio/m4a" mais est trompeur, il ne reflète pas le vrai
    // codec). Aucun navigateur de bureau (Chrome/Firefox/Edge/Safari) ne sait décoder l'AMR
    // nativement : ce n'est pas une erreur de lecture accidentelle, la lecture est structurellement
    // impossible tant que le fichier n'est pas transcodé — inutile donc de tenter un <audio> qui
    // échouera systématiquement, mieux vaut prévenir tout de suite plutôt que laisser un lecteur
    // muet sans explication.
    var KNOWN_UNPLAYABLE_EXTS = ['3gp', 'amr'];

    function fileExtension(nameOrUrl) {
        if (!nameOrUrl) return '';
        var withoutQuery = nameOrUrl.split('?')[0].split('#')[0];
        var parts = withoutQuery.split('.');
        return parts.length > 1 ? parts.pop().toLowerCase() : '';
    }

    // La simple navigation vers l'URL du fichier (ce que fait target=_blank) ne télécharge pas :
    // le navigateur affiche inline tout ce qu'il sait rendre (image, PDF...). Forcer un vrai
    // téléchargement cross-origin exige un header `Content-Disposition: attachment` dans la
    // réponse HTTP elle-même — impossible à obtenir en ajoutant un paramètre à une URL S3 anonyme
    // (`response-content-disposition` y est refusé : "cannot be used for anonymous GET requests").
    // `downloadUrl` doit donc toujours pointer vers l'endpoint Django `attachments:get-attachment`
    // avec `?download=1`, qui relaie le fichier avec le bon header (cf. attachments/views.py) —
    // fourni par les templates via `data-download-url`, à défaut on retombe sur `url` (best effort,
    // ex. flux "pièce jointe chiffrée" qui ne passe pas encore par cet endpoint).
    function buildDownloadUrl(downloadUrl, url) {
        var target = downloadUrl || url;
        var sep = target.indexOf('?') !== -1 ? '&' : '?';
        return target + (downloadUrl ? '' : sep + 'download=1');
    }

    // `<a download>` seul (comportement précédent) télécharge bien le fichier, mais en passant
    // entièrement par la gestion native du navigateur : aucun événement JS n'est déclenché pour
    // suivre l'avancement ni détecter la fin — l'utilisateur cliquait sans plus jamais savoir si
    // le téléchargement avait réellement abouti. On reproduit donc le téléchargement nous-mêmes
    // via fetch()/ReadableStream (en lisant `Content-Length`, fourni par `FileResponse`, cf.
    // attachments/views.py::GetAttachmentAPIView) pour afficher une progression, puis on déclenche
    // la sauvegarde du fichier via un lien `Blob` temporaire — le résultat final pour l'utilisateur
    // (boîte de dialogue "Enregistrer sous"/fichier dans ses téléchargements) est identique.
    function setDownloadStatus(html, cssClass) {
        $('#attachmentPreviewDownloadStatus')
            .removeClass('d-none text-muted text-success text-danger')
            .addClass(cssClass)
            .html(html);
    }

    function resetDownloadStatus() {
        $('#attachmentPreviewDownloadStatus').addClass('d-none').empty();
    }

    function downloadWithProgress(url, filename) {
        var $link = $('#attachmentPreviewDownloadLink');
        if ($link.hasClass('disabled')) return; // téléchargement déjà en cours, ignore le double-clic

        $link.addClass('disabled').attr('aria-disabled', 'true');
        setDownloadStatus('<i class="fas fa-spinner fa-spin mr-1"></i>' + attachmentPreviewDownloadingMessage, 'text-muted');

        fetch(url, { credentials: 'same-origin' })
            .then(function (response) {
                if (!response.ok || !response.body) {
                    throw new Error('HTTP ' + response.status);
                }
                var total = parseInt(response.headers.get('Content-Length') || '0', 10);
                var loaded = 0;
                var reader = response.body.getReader();
                var chunks = [];

                function pump() {
                    return reader.read().then(function (result) {
                        if (result.done) {
                            return new Blob(chunks);
                        }
                        chunks.push(result.value);
                        loaded += result.value.length;
                        // Sans `Content-Length` (ex. réponse chunked), on garde le message générique
                        // "Téléchargement en cours..." plutôt qu'un pourcentage impossible à calculer.
                        if (total > 0) {
                            var percent = Math.min(100, Math.round((loaded / total) * 100));
                            setDownloadStatus(
                                '<i class="fas fa-spinner fa-spin mr-1"></i>' + attachmentPreviewDownloadingMessage + ' (' + percent + '%)',
                                'text-muted'
                            );
                        }
                        return pump();
                    });
                }
                return pump();
            })
            .then(function (blob) {
                var blobUrl = URL.createObjectURL(blob);
                var $tempLink = $('<a></a>').attr({ href: blobUrl, download: filename || 'download' });
                $('body').append($tempLink);
                $tempLink[0].click();
                $tempLink.remove();
                // Délai avant révocation : certains navigateurs lisent l'URL blob de façon asynchrone
                // pour amorcer le téléchargement, la révoquer immédiatement peut l'interrompre.
                setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 30000);

                setDownloadStatus('<i class="fas fa-check-circle mr-1"></i>' + attachmentPreviewDownloadedMessage, 'text-success');
                setTimeout(resetDownloadStatus, 4000);
            })
            .catch(function (err) {
                console.error('Attachment download failed', err);
                setDownloadStatus('<i class="fas fa-exclamation-triangle mr-1"></i>' + attachmentPreviewDownloadErrorMessage, 'text-danger');
            })
            .finally(function () {
                $link.removeClass('disabled').attr('aria-disabled', 'false');
            });
    }

    // Exposée globalement : réutilisée par le flux "pièce jointe chiffrée" (voir issue_detail.html,
    // `.show-data` -> vérification du mot de passe -> ouverture du fichier déchiffré), qui ne peut
    // pas passer par la délégation de clic sur `.attachment-link` ci-dessous puisque l'URL finale
    // n'est connue qu'après confirmation du mot de passe.
    window.openAttachmentPreview = function (url, name, downloadUrl) {
        var $modal = $('#attachmentPreviewModal');
        if ($modal.length === 0 || !url) return;

        var $body = $('#attachmentPreviewModalBody');
        var ext = fileExtension(name) || fileExtension(url);

        $('#attachmentPreviewModalLabel').text(name || '');
        // Le lien "Ouvrir dans un nouvel onglet" garde l'ancien comportement (target=_blank, URL
        // telle quelle) ; le lien "Download" pointe vers l'endpoint qui force réellement le
        // téléchargement (cf. buildDownloadUrl ci-dessus) et porte aussi le nom de fichier à
        // utiliser pour la sauvegarde locale (cf. downloadWithProgress, déclenché au clic).
        $('#attachmentPreviewDownloadLink')
            .attr('href', buildDownloadUrl(downloadUrl, url))
            .data('filename', name || '');
        $('#attachmentPreviewOpenLink').attr('href', url);
        resetDownloadStatus();
        $body.empty();

        if (IMAGE_EXTS.indexOf(ext) !== -1) {
            $body.html('<img src="" class="img-fluid" alt="">').find('img').attr('src', url).attr('alt', name || '');
        } else if (KNOWN_UNPLAYABLE_EXTS.indexOf(ext) !== -1) {
            $body.html('<p class="text-muted" style="color: red !important;">' + attachmentPreviewFormatUnsupportedMessage + '</p>');
        } else if (AUDIO_MIME[ext] || VIDEO_MIME[ext]) {
            var isAudio = !!AUDIO_MIME[ext];
            var tag = isAudio ? 'audio' : 'video';
            var mime = isAudio ? AUDIO_MIME[ext] : VIDEO_MIME[ext];
            // Un <source type="..."> explicite est nécessaire en plus de l'URL : sans lui, le
            // navigateur doit deviner le format uniquement à partir du Content-Type renvoyé par le
            // serveur (souvent générique/absent ici, `attachments:get-attachment` faisant une simple
            // redirection HTTP 302 vers le stockage réel) — sans indice de type fiable, certains
            // navigateurs (notamment Chrome) refusent silencieusement de lire l'audio/vidéo, sans
            // déclencher d'erreur visible. `.load()` force par ailleurs le lecteur à réévaluer sa
            // source : nécessaire ici car l'élément est injecté dynamiquement après coup.
            var $media = $(
                '<' + tag + ' controls style="width:100%;' + (isAudio ? 'margin-top:20px;' : 'max-height:75vh;') + '">' +
                '<source src="' + url + '" type="' + mime + '">' +
                '</' + tag + '>'
            );
            // Filet de sécurité pour un format inattendu qui échoue quand même à charger (fichier
            // corrompu, ou extension mal détectée) — les formats connus pour ne jamais fonctionner
            // (3gp/amr) sont déjà écartés plus haut, sans même tenter de lecture.
            $media.on('error', function () {
                $body.html('<p class="text-muted">' + attachmentPreviewGenericErrorMessage + '</p>');
            });
            $body.append($media);
            $media[0].load();
        } else if (ext === 'pdf') {
            // <embed> plutôt que <iframe> pour les PDF : évite le warning console Chrome
            // "Permissions policy violation: unload is not allowed in this document" émis par le
            // visualiseur PDF interne du navigateur lorsqu'il tourne dans un <iframe> (bénin, mais
            // évitable). Sans incidence fonctionnelle, l'affichage était déjà correct avec <iframe>.
            $body.html('<embed src="" type="application/pdf" style="width:100%;height:75vh;">')
                .find('embed').attr('src', url);
        } else {
            // Word/Excel et tout type non reconnu (ex. fichier déchiffré dont le nom n'est pas
            // toujours disponible) : un <iframe> laisse le navigateur proposer un téléchargement
            // pour ce qu'il ne sait pas afficher nativement — dégradation correcte sans dépendance
            // supplémentaire (pas de visualiseur Office/PDF.js).
            $body.html('<iframe src="" style="width:100%;height:75vh;border:0;"></iframe>')
                .find('iframe').attr('src', url);
        }

        $modal.modal('show');
    };

    $(document).on('click', '.attachment-link', function (e) {
        var href = $(this).attr('href');
        if (!href || href === '#!') return; // pièce jointe pas encore synchronisée : pas de fichier à montrer
        e.preventDefault();
        window.openAttachmentPreview(href, $(this).data('filename'), $(this).data('download-url'));
    });

    $(document).on('click', '#attachmentPreviewDownloadLink', function (e) {
        e.preventDefault();
        var $this = $(this);
        var href = $this.attr('href');
        if (!href || $this.hasClass('disabled')) return;
        downloadWithProgress(href, $this.data('filename'));
    });

    // Vide le lecteur (surtout utile pour l'audio/vidéo : arrête la lecture) et le statut de
    // téléchargement à la fermeture.
    $(document).on('hidden.bs.modal', '#attachmentPreviewModal', function () {
        $('#attachmentPreviewModalBody').empty();
        resetDownloadStatus();
    });

    // Cas "checkPasswordModal -> openAttachmentPreview" (issue_detail.html) : la modale mot de
    // passe est fermée puis attachmentPreviewModal est ouverte immédiatement par-dessus, pendant
    // que la première termine encore son animation de fermeture. Quand son hidden.bs.modal se
    // déclenche (après la transition CSS), Bootstrap 4 retire la classe `modal-open` du <body>
    // sans savoir qu'une autre modale (attachmentPreviewModal) est encore affichée — Bootstrap 4
    // ne gère pas nativement l'empilement de modales. Or c'est cette classe qui active la règle
    // `.modal-open .modal { overflow-y: auto; }` : sans elle, le contenu long (PDF, vidéo...) de
    // la modale restante déborde sans barre de défilement possible. On la restaure donc si une
    // modale est encore visible.
    $(document).on('hidden.bs.modal', '.modal', function () {
        if ($('.modal.show').length) {
            $('body').addClass('modal-open');
        }
    });
})(jQuery);