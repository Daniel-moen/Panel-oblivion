import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({ fallback: '200.html' }),
    prerender: {
      entries: [
        '/', '/map', '/prospects', '/agent', '/account', '/online', '/tasks',
        '/leads', '/leads/pipeline', '/leads/properties', '/leads/contacts',
        /* Media. Each one is emitted as ui/build/media/<name>.html, which is
           what webapp.py's /media/<path> route looks for before falling back
           to 200.html. The client share page is NOT here: it is rendered by
           share_page.py so it needs no JavaScript bundle and no auth
           exemption for /_app. */
        '/media', '/media/browse', '/media/search', '/media/tags',
        '/media/duplicates', '/media/shares', '/media/files', '/media/settings',
        /* Zerko 1.2–1.4. Detail views take ?id= rather than a [param] route
           so each one still prerenders to a file webapp.py can find. */
        '/media/shoots', '/media/shoot', '/media/calendar', '/media/edit',
        '/media/hdr', '/media/video'
      ]
    }
  }
};

export default config;
