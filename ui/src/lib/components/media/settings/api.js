/* The Media › Settings calls. Each one is guarded server-side too; the page
   only hides what the viewer's role cannot use (see /api/me). Keys are write
   only: the backend answers with a hint ("...abcd"), never the key. */
import { mfetch, post, put } from '$lib/media.js';

export const settingsApi = {
  ai: () => mfetch('/api/ai/settings'),
  saveAi: (body) => put('/api/ai/settings', body),
  aiModels: () => mfetch('/api/ai/models'),
  testAi: () => post('/api/ai/test'),

  image: () => mfetch('/api/ai/image/settings'),
  saveImage: (body) => put('/api/ai/image/settings', body),
  testImage: () => post('/api/ai/image/test'),

  captions: () => mfetch('/api/captions/settings'),
  saveCaptions: (body) => put('/api/captions/settings', body),

  trash: () => mfetch('/api/trash'),
  saveTrash: (auto_days) => post('/api/trash/settings', { auto_days }),

  libraryCheck: () => post('/api/library-check'),
  libraryStatus: () => mfetch('/api/library-check/status'),
  libraryApply: (body) => post('/api/library-check/apply', body),

  tagRules: () => mfetch('/api/tags/custom-rules'),
  addRule: (body) => post('/api/tags/custom-rules', body),
  editRule: (id, body) => mfetch(`/api/tags/custom-rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  delRule: (id) => mfetch(`/api/tags/custom-rules/${id}`, { method: 'DELETE' }),
  toggleBuiltin: (tag, enabled) => post(`/api/tags/builtin-rules/${encodeURIComponent(tag)}`, { enabled }),
  previewRule: (phrases, min_hits = 1) => post('/api/tags/rules/preview', { phrases, min_hits })
};
