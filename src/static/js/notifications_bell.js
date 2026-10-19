// Cloche des notifications MGP (layouts/navbar.html) : pastille + menu, rechargés au chargement
// de la page puis toutes les 2 minutes (dashboard.grm.views.NotificationsBellView).
(function ($) {
    var REFRESH_MS = 2 * 60 * 1000;
    var $bell = $('#notifications-bell');
    if (!$bell.length) {
        return;
    }

    function refreshBell() {
        $.getJSON($bell.data('url'))
            .done(function (data) {
                $('#notifications-bell-menu').html(data.html);
                var $count = $('#notifications-bell-count');
                if (data.count > 0) {
                    $count.text(data.count > 99 ? '99+' : data.count).show();
                } else {
                    $count.hide();
                }
            });
    }

    refreshBell();
    setInterval(refreshBell, REFRESH_MS);
})(jQuery);
