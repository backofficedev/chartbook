// Rewrite <time class="cb-relative-time" datetime="..."> as "2 days ago".
//
// The site is static, so "how long ago" has to be worked out when a page is
// read, not when it was built. The build writes the timestamp; this turns it
// into plain relative wording. The absolute time stays in the element's title
// attribute (shown on hover), and is the text shown if this script never runs.
(function () {
    var UNITS = [
        ['year', 31536000],
        ['month', 2592000],
        ['week', 604800],
        ['day', 86400],
        ['hour', 3600],
        ['minute', 60]
    ];

    function relative(seconds) {
        if (seconds < 60) {
            return 'just now';
        }
        for (var i = 0; i < UNITS.length; i++) {
            var count = Math.floor(seconds / UNITS[i][1]);
            if (count >= 1) {
                return count + ' ' + UNITS[i][0] + (count === 1 ? '' : 's') + ' ago';
            }
        }
        return 'just now';
    }

    function refresh() {
        var nodes = document.querySelectorAll('time.cb-relative-time');
        for (var i = 0; i < nodes.length; i++) {
            var then = Date.parse(nodes[i].getAttribute('datetime'));
            if (!isNaN(then)) {
                nodes[i].textContent = relative((Date.now() - then) / 1000);
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', refresh);
    } else {
        refresh();
    }
})();
