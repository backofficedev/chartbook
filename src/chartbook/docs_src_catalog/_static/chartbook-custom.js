// Add class to body for chart pages to enable custom CSS
document.addEventListener('DOMContentLoaded', function() {
    // Check if DOCUMENTATION_OPTIONS exists and has pagename
    if (typeof DOCUMENTATION_OPTIONS !== 'undefined' && DOCUMENTATION_OPTIONS.pagename) {
        var pagename = DOCUMENTATION_OPTIONS.pagename;

        // Add class for chart pages
        if (pagename.indexOf('charts/') !== -1) {
            document.body.classList.add('chartbook-chart-page');
        }

        // Add class for charts listing page
        if (pagename === 'charts' || pagename.endsWith('/charts')) {
            document.body.classList.add('chartbook-charts-listing');
        }

        // Add class for dataframe pages
        if (pagename.indexOf('dataframes/') !== -1 || pagename === 'dataframes') {
            document.body.classList.add('chartbook-full-width-page');
        }

        // Add class for pipeline pages
        if (pagename.indexOf('pipelines') !== -1) {
            document.body.classList.add('chartbook-full-width-page');
        }

        // Add class for diagnostics pages
        if (pagename.indexOf('diagnostics') !== -1) {
            document.body.classList.add('chartbook-full-width-page');
        }

        // Add data attribute with pagename for CSS targeting
        document.body.setAttribute('data-pagename', pagename);
    }
}); 