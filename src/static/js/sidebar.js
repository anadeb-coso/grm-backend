/**
 * Handles the [data-widget="pushmenu"] buttons (navbar burger and "Toggle Sidebar").
 * adminlte.js is not shipped with this project, so this reproduces its PushMenu behaviour:
 * collapse to icons on large screens, off-canvas sidebar with overlay below 992px.
 * The state chosen on large screens is remembered across page loads.
 */
(function () {
    const AUTO_COLLAPSE_SIZE = 992;
    const STORAGE_KEY = "grm.sidebar";
    const COLLAPSED = "sidebar-collapse", OPEN = "sidebar-open", CLOSED = "sidebar-closed";
    const $body = $("body");

    if (!$('[data-widget="pushmenu"]').length) {
        return;
    }

    function isSmallScreen() {
        return $(window).width() <= AUTO_COLLAPSE_SIZE;
    }

    function rememberedState() {
        try {
            return localStorage.getItem(STORAGE_KEY);
        } catch (e) {
            return null;
        }
    }

    function rememberState(state) {
        try {
            localStorage.setItem(STORAGE_KEY, state);
        } catch (e) {
            // storage unavailable (private mode...): the toggle still works for the current page
        }
    }

    function expand() {
        if (isSmallScreen()) {
            $body.addClass(OPEN);
        }
        $body.removeClass(COLLAPSED).removeClass(CLOSED);
    }

    function collapse() {
        if (isSmallScreen()) {
            $body.removeClass(OPEN).addClass(CLOSED);
        }
        $body.addClass(COLLAPSED);
    }

    function applyLargeScreenState() {
        $body.removeClass(OPEN).removeClass(CLOSED);
        $body.toggleClass(COLLAPSED, rememberedState() === COLLAPSED);
    }

    function applyInitialState() {
        if (isSmallScreen()) {
            collapse();
        } else {
            applyLargeScreenState();
        }
    }

    $(".wrapper").append($("<div />", {id: "sidebar-overlay"}).on("click", collapse));

    $(document).on("click", '[data-widget="pushmenu"]', function (event) {
        event.preventDefault();
        if ($body.hasClass(COLLAPSED)) {
            expand();
        } else {
            collapse();
        }
        if (!isSmallScreen()) {
            rememberState($body.hasClass(COLLAPSED) ? COLLAPSED : OPEN);
        }
    });

    let wasSmallScreen = isSmallScreen();
    $(window).on("resize", function () {
        if (isSmallScreen() !== wasSmallScreen) {
            wasSmallScreen = isSmallScreen();
            applyInitialState();
        }
    });

    applyInitialState();
    // body starts with "hold-transition" (no animation while the initial state is applied)
    $(window).on("load", function () {
        $body.removeClass("hold-transition");
    });
})();
