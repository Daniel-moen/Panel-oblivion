import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter({ fallback: '200.html' }),
    prerender: { entries: ['/', '/map', '/prospects', '/agent', '/leads', '/leads/pipeline', '/leads/properties', '/leads/contacts'] }
  }
};

export default config;
