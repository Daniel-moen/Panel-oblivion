/* A listing key is data, not a file: this page is never prerendered. Flask
   (property_view.py) serves the 200.html shell for /property/<key> and the
   client reads the real URL, like /leads/properties/<gid>. */
export const prerender = false;
